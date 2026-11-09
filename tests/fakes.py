"""A scripted stand-in for the model: writes honest cards from the sources, with scripted faults on request.

Used by the tests and by tests/make_fixture_store.py, which records its answers as the replay fixture.
"""
from __future__ import annotations

import re
from typing import Any

from runbook_cards.llm import Reply, Request
from runbook_cards.packs.base import Unit, detection_fields, parse_rule

USAGE = {"input_tokens": 3000, "output_tokens": 400}


def span(unit: Unit, quote: str) -> dict[str, Any]:
    """The shortest line range (up to 4 lines) of any unit doc whose whitespace-normalised text holds the quote."""
    want = " ".join(quote.split())
    for width in range(1, 5):
        for d in unit.docs:
            for start in range(1, len(d.lines) - width + 2):
                if want in " ".join(" ".join(d.lines[start - 1:start - 1 + width]).split()):
                    return {"doc_id": d.doc_id, "start_line": start, "end_line": start + width - 1, "quote": quote}
    raise AssertionError(f"quote not in {unit.unit_id}: {quote!r}")


def honest(unit: Unit) -> dict[str, Any]:
    """A tool input whose every field is a near-copy of one source line, with a span for it."""
    cites: dict[str, list[dict[str, Any]]] = {}
    if unit.pack == "security":
        rule = parse_rule(unit.primary)
        desc, title = rule["description"].strip(), rule["title"].strip()
        out: dict[str, Any] = {"what_it_is": desc, "why_it_flags": title}
        cites["what_it_is"] = [span(unit, desc)]
        cites["why_it_flags"] = [span(unit, title)]
        out["key_fields"] = detection_fields(rule)
        for i, f in enumerate(out["key_fields"]):
            cites[f"key_fields[{i}]"] = [span(unit, f)]
        fp = (rule.get("falsepositives") or [desc])[0]
        out["triage_tips"] = [f"Check this first: {fp}"]
        cites["triage_tips[0]"] = [span(unit, fp)]
    else:
        text = "\n".join(unit.primary.lines)
        purpose = re.search(r"^Purpose:\s*(.+)$", text, re.M)
        what = purpose.group(1).strip() if purpose else unit.unit_id
        steps = [m.group(1).strip() for m in re.finditer(r"^(?:Step\s*)?\d+[.):]\s*(.+)$", text, re.M)][:6]
        checks = [m.group(1).strip() for m in re.finditer(r"^Checks?:\s*(.+)$", text, re.M)][:1]
        esc = re.search(r"^Escalate to:\s*(.+)$", text, re.M)
        out = {"what_it_is": what, "when_to_use": what, "steps": steps, "checks": checks,
               "escalate_to": esc.group(1).strip() if esc else ""}
        cites["what_it_is"] = cites["when_to_use"] = [span(unit, what)] if purpose else []
        if not purpose:
            cites["what_it_is"] = cites["when_to_use"] = [span(unit, unit.primary.lines[0])]
            out["what_it_is"] = out["when_to_use"] = unit.primary.lines[0]
        for i, s in enumerate(steps):
            cites[f"steps[{i}]"] = [span(unit, s)]
        for i, c in enumerate(checks):
            cites[f"checks[{i}]"] = [span(unit, c)]
        if esc:
            cites["escalate_to"] = [span(unit, esc.group(1).strip())]
    out["citations"] = cites
    out["injection_found"] = []
    return out


class FakeModel:
    """Implements the Client protocol. `script[unit_id]` may hold: draft/redraft = "bad"; ground = [[claims], ...];
    inject = (quote, "report" | "skip" | "follow")."""
    live = True

    def __init__(self, units: dict[str, Unit], script: dict[str, dict[str, Any]] | None = None, group_size: int | None = 4):
        self.units, self.script = units, script or {}
        self.group_size = group_size
        self.calls: list[Request] = []
        self._ground_calls: dict[str, int] = {}

    def count_tokens(self, body: dict[str, Any]) -> int | None:
        return 3000

    def _tool_input(self, req: Request) -> dict[str, Any]:
        unit, sc = self.units[req.unit_id], self.script.get(req.unit_id, {})
        if req.phase == "ground":
            n = self._ground_calls[req.unit_id] = self._ground_calls.get(req.unit_id, 0) + 1
            rounds = sc.get("ground", [])
            return {"unsupported": rounds[n - 1] if n <= len(rounds) else []}
        data = honest(unit)
        if req.phase == "redraft-unsupported":  # a real redraft would reword; an identical card would hit the cache
            data["what_it_is"] = "Summary: " + data["what_it_is"]
        if sc.get(req.phase) == "bad":
            if unit.pack == "security":
                data["key_fields"] = [*data["key_fields"], "NoSuchField"]
                data["citations"]["key_fields[%d]" % (len(data["key_fields"]) - 1)] = [span(unit, unit.primary.lines[0])]
            else:
                data["what_it_is"] = "see " + "http" + "s://host.example/x"
        inj = sc.get("inject")
        if inj:
            quote, mode = inj
            if mode in {"report", "follow"}:
                data["injection_found"] = [span(unit, quote)]
            if mode == "follow":
                key = "triage_tips" if unit.pack == "security" else "checks"
                data[key] = [*data[key], quote[:200]]
                data["citations"][f"{key}[{len(data[key]) - 1}]"] = [span(unit, quote[:200])]
        return data

    def submit(self, requests: list[Request]) -> list[Reply]:
        self.calls.extend(requests)
        return [Reply(self._tool_input(r), dict(USAGE), None) for r in requests]
