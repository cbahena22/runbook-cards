"""Clients, the request-hash store and the gateway that ties them to the budget.

One store serves as cache and as replay: `<dir>/requests.jsonl`, `responses.jsonl`, `usage.json`.
A request hash covers the model, prompt version, schema version and the full request body; no header is
ever stored. A hash hit is reused. A miss under replay is an error, never a live call.
`anthropic` is imported lazily inside the live clients, so demo, build, check and replay never load it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .budget import Budget, estimate_tokens, usage_cost
from .config import Config

TOOL_ERRORS = {"timeout", "budget", "error"}
PARTIAL_EDGE = 400  # characters kept from each end of an output that stopped at max_tokens
SDK_MAX_RETRIES = 2  # per request; a timed-out request may have been attempted 1 + SDK_MAX_RETRIES times


class LlmError(Exception):
    """A run-level failure (refused option, authentication refused, missing key)."""


class NotRecorded(LlmError):
    """Replay was asked for a request that is not in the store."""


class StoreError(LlmError):
    pass


@dataclass(frozen=True)
class Request:
    unit_id: str
    phase: str
    body: dict[str, Any]


@dataclass
class Reply:
    tool_input: dict[str, Any] | None
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    error: str | None = None  # "timeout" | "budget" | "error" | None
    stop_reason: str | None = None  # provider stop reason, kept for a failed reply so the cause is visible in the store
    detail: str | None = None  # a failed call: exception class, HTTP status and a bounded part of the provider's error text
    partial: str | None = None  # first + last PARTIAL_EDGE characters of an unfinished output (max_tokens), else None


@dataclass
class Result:
    unit_id: str
    phase: str
    hash: str
    reply: Reply
    cached: bool = False


def request_hash(body: dict[str, Any], prompt_version: str, schema_version: str) -> str:
    blob = json.dumps({"prompt_version": prompt_version, "schema_version": schema_version, "body": body},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Store:
    """Append-only JSONL store. `readonly` (replay) never writes."""

    def __init__(self, directory: Path, readonly: bool = False):
        self.dir = Path(directory)
        self.readonly = readonly
        self.responses: dict[str, dict[str, Any]] = {}
        self._requests: set[str] = set()
        self._spent = {"input_tokens": 0, "output_tokens": 0}  # every record ever written, not just the last per hash
        self._records = 0
        if readonly and not self.dir.is_dir():
            raise StoreError("replay directory not found")
        self._load()

    def _read_lines(self, name: str) -> list[dict[str, Any]]:
        path = self.dir / name
        if not path.is_file():
            return []
        out = []
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                raise StoreError(f"{name}:{n}: not valid JSON") from None
            if not isinstance(rec, dict) or not isinstance(rec.get("hash"), str):
                raise StoreError(f"{name}:{n}: not a store record")
            usage = rec.get("usage")
            if usage is not None:  # a reused store feeds the spend total: refuse values that could lower or break it
                if not isinstance(usage, dict) or any(
                        k in usage and (type(usage[k]) is not int or usage[k] < 0) for k in ("input_tokens", "output_tokens")):
                    raise StoreError(f"{name}:{n}: usage must hold non-negative integers")
            out.append(rec)
        return out

    def _load(self) -> None:
        for rec in self._read_lines("responses.jsonl"):
            self.responses[rec["hash"]] = rec  # lookups see the last record of a hash
            self._count(rec)
        self._requests = {r["hash"] for r in self._read_lines("requests.jsonl")}

    def _count(self, rec: dict[str, Any]) -> None:
        # a retried hash is billed again: the spend total keeps the earlier records too, so a resumed run never forgets them
        self._records += 1
        for k in self._spent:
            self._spent[k] += int((rec.get("usage") or {}).get(k, 0))

    def get(self, h: str) -> dict[str, Any] | None:
        return self.responses.get(h)

    def _append(self, name: str, rec: dict[str, Any]) -> None:
        # ensure_ascii: a rejected draft with hidden (Cf) characters must reach the committed store as visible escapes
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / name).open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=True) + "\n")

    def put(self, req: Request, h: str, reply: Reply) -> None:
        if self.readonly:
            raise StoreError("the store is read-only")
        if h not in self._requests:
            self._append("requests.jsonl", {"hash": h, "unit_id": req.unit_id, "phase": req.phase,
                                            "model": req.body.get("model"), "max_tokens": req.body.get("max_tokens")})
            self._requests.add(h)
        rec = {"hash": h, "unit_id": req.unit_id, "phase": req.phase, "tool_input": reply.tool_input,
               "usage": reply.usage, "error": reply.error}
        if reply.stop_reason is not None:  # only a failed reply carries these, so a clean store is byte-for-byte unchanged
            rec["stop_reason"] = reply.stop_reason
        if reply.partial is not None:
            rec["partial"] = reply.partial
        if reply.detail is not None:
            rec["detail"] = reply.detail
        self._append("responses.jsonl", rec)
        self.responses[h] = rec
        self._count(rec)

    def total_usage(self) -> dict[str, int]:
        return dict(self._spent)

    def total_cost(self, cfg: Config) -> float:
        return usage_cost(self.total_usage(), cfg.price_in, cfg.price_out)

    def save_usage(self, cfg: Config) -> None:
        if self.readonly:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        u = self.total_usage()
        data = {**u, "requests": self._records, "model": cfg.model, "price_per_mtok": [cfg.price_in, cfg.price_out],
                "cost_usd": round(self.total_cost(cfg), 6)}
        (self.dir / "usage.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


class Client(Protocol):
    live: bool
    group_size: int | None  # requests per submit; None = all misses of a phase in one submit

    def count_tokens(self, body: dict[str, Any]) -> int | None: ...
    def submit(self, requests: list[Request]) -> list[Reply]: ...


class Replay:
    """No network: every miss is an error."""
    live = False
    group_size = None

    def count_tokens(self, body: dict[str, Any]) -> int | None:
        return None

    def submit(self, requests: list[Request]) -> list[Reply]:
        raise NotRecorded("not recorded: " + ", ".join(sorted({r.unit_id for r in requests})[:5]))


def partial_snippet(msg: Any) -> str | None:
    """What an unfinished message holds, as text, cut to its first and last PARTIAL_EDGE characters (bounded, never the whole)."""
    parts: list[str] = []
    for block in getattr(msg, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "tool_use":
            parts.append(json.dumps(getattr(block, "input", None), ensure_ascii=True, default=str, separators=(",", ":")))
        elif kind == "text":
            parts.append(str(getattr(block, "text", "")))
    text = "\n".join(parts)
    if not text:
        return None
    if len(text) <= 2 * PARTIAL_EDGE:
        return text
    return f"{text[:PARTIAL_EDGE]} ...[{len(text) - 2 * PARTIAL_EDGE} chars omitted]... {text[-PARTIAL_EDGE:]}"


def reply_from_message(msg: Any) -> Reply:
    """A provider message -> Reply: the first tool_use block's input, plus usage.

    A message that stopped at max_tokens is an error, never a card; it keeps its stop reason and a bounded snippet of what
    it wrote, so the cause (a loop, an oversized field, a long citation list) can be read from the store."""
    u = getattr(msg, "usage", None)
    usage = {"input_tokens": int(getattr(u, "input_tokens", 0) or 0), "output_tokens": int(getattr(u, "output_tokens", 0) or 0)}
    stop = getattr(msg, "stop_reason", None)
    stop = stop if isinstance(stop, str) else None
    if stop == "max_tokens":
        return Reply(None, usage, "error", stop_reason=stop, partial=partial_snippet(msg))
    for block in getattr(msg, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            data = getattr(block, "input", None)
            if isinstance(data, dict):
                return Reply(data, usage, None)
            return Reply(None, usage, "error", stop_reason=stop)
    return Reply(None, usage, "error", stop_reason=stop, partial=partial_snippet(msg))


def _make_sdk() -> Any:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LlmError("ANTHROPIC_API_KEY is not set in the environment")
    import anthropic  # lazy: only the live clients load the SDK

    # the SDK backs off on 429 and 5xx. A timeout is retried too and each attempt is billed, so Gateway checks and charges
    # the bound x (1 + SDK_MAX_RETRIES) on a timeout.
    return anthropic.Anthropic(api_key=key, max_retries=SDK_MAX_RETRIES, timeout=120.0)


DETAIL_MAX = 300


def exc_detail(exc: BaseException) -> str:
    """Why a call failed, for the store: class name, HTTP status and a bounded part of the provider's error text
    (the `error.message` of the response body, never the request). It is written to the store file only, never into a prompt."""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    text = err.get("message") if isinstance(err, dict) else None
    out = type(exc).__name__ + (f" {status}" if isinstance(status, int) else "")
    if isinstance(text, str) and text:
        out += ": " + text[:DETAIL_MAX]
    return out


def _is_fatal(exc: BaseException) -> bool:
    return type(exc).__name__ in {"AuthenticationError", "PermissionDeniedError"}


class LiveSync:
    """Messages API, `concurrency` requests at a time."""
    live = True

    def __init__(self, cfg: Config, sdk: Any = None):
        self.group_size = cfg.concurrency
        self.sdk = sdk if sdk is not None else _make_sdk()

    def count_tokens(self, body: dict[str, Any]) -> int | None:
        try:
            keys = ("model", "system", "messages", "tools", "tool_choice", "thinking")
            return int(self.sdk.messages.count_tokens(**{k: body[k] for k in keys if k in body}).input_tokens)
        except Exception:  # noqa: BLE001 - the budget falls back to its own estimate
            return None

    def _one(self, req: Request) -> Reply:
        try:
            return reply_from_message(self.sdk.messages.create(**req.body))
        except Exception as exc:  # noqa: BLE001
            if _is_fatal(exc):
                raise LlmError("the provider refused the credentials") from None
            name = type(exc).__name__
            return Reply(None, error="timeout" if "Timeout" in name else "error", detail=exc_detail(exc))

    def submit(self, requests: list[Request]) -> list[Reply]:
        with ThreadPoolExecutor(max_workers=self.group_size) as pool:
            return list(pool.map(self._one, requests))


class LiveBatch:
    """Message Batches API: one batch per phase, polled with a 2 h cap, then cancelled."""
    live = True
    group_size = None

    def __init__(self, cfg: Config, sdk: Any = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.sdk = sdk if sdk is not None else _make_sdk()
        self.sleep, self.clock = sleep, clock

    def count_tokens(self, body: dict[str, Any]) -> int | None:
        return LiveSync.count_tokens(self, body)  # type: ignore[arg-type]

    def submit(self, requests: list[Request]) -> list[Reply]:
        ids = [f"r{i}" for i in range(len(requests))]
        try:
            return self._submit(requests, ids)
        except LlmError:
            raise
        except Exception as exc:  # noqa: BLE001 - never echo the provider's response text
            if _is_fatal(exc):
                raise LlmError("the provider refused the credentials") from None
            raise LlmError(f"batch request failed ({type(exc).__name__})") from None

    def _submit(self, requests: list[Request], ids: list[str]) -> list[Reply]:
        batch = self.sdk.messages.batches.create(
            requests=[{"custom_id": cid, "params": r.body} for cid, r in zip(ids, requests)])
        start, delay = self.clock(), 1.0
        while getattr(batch, "processing_status", "") != "ended":
            if self.clock() - start >= self.cfg.batch_cap_seconds:
                try:
                    self.sdk.messages.batches.cancel(batch.id)  # the units are marked timeout either way
                except Exception:  # noqa: BLE001  # nosec B110
                    pass
                return [Reply(None, error="timeout") for _ in requests]
            self.sleep(min(delay, self.cfg.batch_poll_seconds))
            delay = min(delay * 2, self.cfg.batch_poll_seconds)
            batch = self.sdk.messages.batches.retrieve(batch.id)
        by_id: dict[str, Reply] = {}
        for entry in self.sdk.messages.batches.results(batch.id):
            res = entry.result
            if getattr(res, "type", "") == "succeeded":
                by_id[entry.custom_id] = reply_from_message(res.message)
            else:
                kind = str(getattr(res, "type", ""))
                msg = getattr(getattr(getattr(res, "error", None), "error", None), "message", None)
                by_id[entry.custom_id] = Reply(None, error="timeout" if kind == "expired" else "error",
                                               detail=f"batch result {kind[:40]}" + (f": {msg[:DETAIL_MAX]}" if isinstance(msg, str) else ""))
        return [by_id.get(cid, Reply(None, error="error")) for cid in ids]


class Gateway:
    """store lookup -> budget check -> client submit -> store. One call per phase."""

    def __init__(self, client: Client, store: Store, cfg: Config, budget: Budget | None = None):
        if client.live and budget is None:
            raise LlmError("a live run needs a budget")
        self.client, self.store, self.cfg, self.budget = client, store, cfg, budget
        self.ledger: list[Result] = []  # every result this gateway returned, for the cost line

    def run(self, requests: list[Request]) -> list[Result]:
        hashes = [request_hash(r.body, self.cfg.prompt_version, self.cfg.schema_version) for r in requests]
        results: list[Result | None] = [None] * len(requests)
        misses: list[int] = []
        for i, (r, h) in enumerate(zip(requests, hashes)):
            rec = self.store.get(h)
            # a live run retries recorded failures; replay reuses them as they were
            if rec is not None and (rec.get("error") is None or not self.client.live):
                results[i] = Result(r.unit_id, r.phase, h, Reply(rec.get("tool_input"), rec.get("usage") or {}, rec.get("error"),
                                                              rec.get("stop_reason"), rec.get("detail"), rec.get("partial")), True)
            else:
                misses.append(i)
        if misses and not self.client.live:
            raise NotRecorded("not recorded: " + ", ".join(sorted({requests[i].unit_id for i in misses})[:5]))
        size = self.client.group_size or max(len(misses), 1)
        pos = 0
        while pos < len(misses):
            group = misses[pos:pos + size]
            if self.budget is None:
                raise LlmError("a live run needs a budget")
            counted = {i: self.client.count_tokens(requests[i].body) for i in group}
            # the SDK may retry a request SDK_MAX_RETRIES times and every attempt can be billed, so the worst case is x (1 + SDK_MAX_RETRIES)
            bound = (1 + SDK_MAX_RETRIES) * sum(self.budget.bound(requests[i].body, counted[i]) for i in group)
            if not self.budget.allows(bound):
                for i in misses[pos:]:  # nothing is sent; the rest of the phase is marked
                    reply = Reply(None, error="budget")
                    self.store.put(requests[i], hashes[i], reply)
                    results[i] = Result(requests[i].unit_id, requests[i].phase, hashes[i], reply)
                break
            replies = self.client.submit([requests[i] for i in group])
            for i, reply in zip(group, replies):
                if reply.error and not any(reply.usage.values()):
                    # billed work with no usage figure (timeout, 5xx, cancelled batch): charge the bound, never $0
                    tin = counted[i] if counted[i] is not None else estimate_tokens(requests[i].body)
                    attempts = 1 + SDK_MAX_RETRIES if reply.error == "timeout" else 1  # each retried timeout is billed
                    reply.usage = {"input_tokens": tin * attempts, "output_tokens": int(requests[i].body["max_tokens"]) * attempts}
                self.budget.add(reply.usage)
                self.store.put(requests[i], hashes[i], reply)
                results[i] = Result(requests[i].unit_id, requests[i].phase, hashes[i], reply)
            self.store.save_usage(self.cfg)
            pos += size
        self.store.save_usage(self.cfg)
        done = [r for r in results if r is not None]
        self.ledger.extend(done)
        return done
