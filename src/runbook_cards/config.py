"""config.toml: model id, prompt version, price table, limits."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import CONFIG


@dataclass(frozen=True)
class Config:
    model: str
    prompt_version: str
    schema_version: str
    price_in: float  # USD per million input tokens (non-batch)
    price_out: float
    draft_max_tokens: int
    grounding_max_tokens: int
    concurrency: int
    batch_cap_seconds: int
    batch_poll_seconds: int
    tool_choice: str = "auto"  # "auto" (the prompt asks for the one tool call) | "forced" (tool_choice names the tool)
    strict: bool = True  # tools are sent with strict: true
    thinking: str = "between_tools"  # "between_tools" (no thinking before the tool call) | "omit" (the model's default)


def load_config(path: Path | None = None) -> Config:
    data = tomllib.loads(Path(path or CONFIG).read_text(encoding="utf-8"))
    m, pr, lim = data["model"], data["price_per_mtok"], data["limits"]
    cfg = Config(str(m["id"]), str(m["prompt_version"]), str(m["schema_version"]), float(pr["input"]), float(pr["output"]),
                 int(lim["draft_max_tokens"]), int(lim["grounding_max_tokens"]), int(lim["concurrency"]),
                 int(lim["batch_cap_seconds"]), int(lim["batch_poll_seconds"]))
    req = data.get("request", {})
    cfg = Config(**{**cfg.__dict__, "tool_choice": str(req.get("tool_choice", cfg.tool_choice)),
                    "thinking": str(req.get("thinking", cfg.thinking)),
                    "strict": req.get("strict", cfg.strict)})
    if not isinstance(cfg.strict, bool):
        raise ValueError("config.toml: [request] strict is true or false")
    if cfg.tool_choice not in {"auto", "forced"} or cfg.thinking not in {"between_tools", "omit"}:
        raise ValueError("config.toml: [request] tool_choice is auto or forced, thinking is between_tools or omit")
    if min(cfg.price_in, cfg.price_out) < 0 or min(cfg.draft_max_tokens, cfg.grounding_max_tokens, cfg.concurrency) < 1:
        raise ValueError("config.toml: prices must be >= 0 and limits >= 1")
    return cfg


def request_extras(cfg: Config, tool_name: str) -> dict[str, Any]:
    """The request fields that depend on the model's rules for tools and thinking (see config.toml [request]).

    Some current models reject a forced tool_choice (HTTP 400) and think before they answer, which spends max_tokens
    before the tool call is written. "auto" plus a prompt that asks for the one call, and no thinking, avoid both."""
    out: dict[str, Any] = {"tool_choice": {"type": "tool", "name": tool_name} if cfg.tool_choice == "forced" else {"type": "auto"}}
    if cfg.thinking == "between_tools":
        out["thinking"] = {"type": "between_tools"}
    return out


# JSON Schema keywords that a strict tool cannot carry. The caps stay in our own validator and move into the description.
_NOT_STRICT = ("maxLength", "minLength", "maximum", "minimum", "maxItems")


def strict_variant(schema: Any) -> Any:
    """A copy of the schema for `strict: true` tools: the keywords strict decoding refuses are dropped and written into the
    description (the model still reads the cap; our jsonschema check still enforces it on the reply)."""
    if isinstance(schema, list):
        return [strict_variant(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: v for k, v in schema.items() if k not in _NOT_STRICT and k not in ("properties", "items")}
    if "properties" in schema:
        out["properties"] = {k: strict_variant(v) for k, v in schema["properties"].items()}
    if "items" in schema:
        out["items"] = strict_variant(schema["items"])
    notes = []
    if "maxLength" in schema:
        notes.append(f"at most {schema['maxLength']} characters")
    if "maxItems" in schema:
        notes.append(f"at most {schema['maxItems']} items")
    if "maximum" in schema:
        notes.append(f"at most {schema['maximum']}")
    if "minimum" in schema:
        notes.append(f"at least {schema['minimum']}")
    if schema.get("minItems", 0) > 1:
        out.pop("minItems")
        notes.append(f"at least {schema['minItems']} items")
    if notes:
        out["description"] = (out["description"] + "; " if out.get("description") else "") + ", ".join(notes)
    return out


def tool_definition(cfg: Config, name: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    """One tool entry for the request body. Strict mode (config.toml [request] strict) makes the reply match the schema's shape."""
    if not cfg.strict:
        return {"name": name, "description": description, "input_schema": schema}
    return {"name": name, "description": description, "strict": True, "input_schema": strict_variant(schema)}
