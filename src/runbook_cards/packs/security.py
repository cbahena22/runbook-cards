"""Security pack: one unit per detection rule; runbooks join units through their `covers:` line."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..convert import BACKENDS, convert
from ..paths import PACKS_DIR
from .base import (PackError, SourceDoc, Unit, attack_ids, detection_fields, header_ids, load_dir, parse_rule,
                   prose_schema)


class SecurityPack:
    name = "security"
    prose_fields = ["what_it_is", "why_it_flags", "key_fields", "triage_tips"]
    string_fields = ["what_it_is", "why_it_flags"]
    list_fields = ["key_fields", "triage_tips"]

    def load(self, root: Path | None = None) -> list[SourceDoc]:
        root = Path(root) if root is not None else PACKS_DIR / self.name
        docs = load_dir(root, "sources/rules", "rule", ".yml") + load_dir(root, "sources/runbooks", "runbook", ".md")
        seen: set[str] = set()
        for d in docs:
            if d.doc_id in seen:
                raise PackError(f"{d.path}: duplicate document id {d.doc_id!r}")
            seen.add(d.doc_id)
        for d in docs:
            if d.kind == "rule":
                parse_rule(d)  # shape check at load time
        return docs

    def units(self, docs: list[SourceDoc]) -> list[Unit]:
        rules = {d.doc_id: d for d in docs if d.kind == "rule"}
        covering: dict[str, list[SourceDoc]] = {rid: [] for rid in rules}
        for rb in sorted((d for d in docs if d.kind == "runbook"), key=lambda d: d.doc_id):
            ids = header_ids(rb, "covers")
            if not ids:
                raise PackError(f"{rb.path}: runbook has no `covers:` line")
            for rid in ids:
                if rid not in rules:
                    raise PackError(f"{rb.path}: covers unknown rule {rid!r}")
                covering[rid].append(rb)
        return [Unit(rid, self.name, "alert", [rules[rid], *covering[rid]]) for rid in sorted(rules)]

    def deterministic_fields(self, unit: Unit) -> dict[str, Any]:
        rule = parse_rule(unit.primary)
        fields = detection_fields(rule)
        runbooks = [d for d in unit.docs if d.kind == "runbook"]
        return {
            "card_id": unit.unit_id,
            "pack": self.name,
            "kind": unit.kind,
            "title": rule["title"],
            "queries": {b: convert(rule, b, fields).to_dict() for b in BACKENDS},
            "attack": attack_ids(rule),
            "playbook_link": runbooks[0].doc_id if runbooks else None,
            "source_shas": [{"doc_id": d.doc_id, "sha256": d.sha256} for d in unit.docs],
        }

    def rule_fields(self, unit: Unit) -> list[str]:
        return detection_fields(parse_rule(unit.primary))

    def tool_schema(self) -> dict[str, Any]:
        return prose_schema(self.string_fields, self.list_fields)
