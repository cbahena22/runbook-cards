"""Helpdesk pack: one unit per SOP; the `related:` line joins another SOP into the unit's context."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import PACKS_DIR
from .base import PackError, SourceDoc, Unit, header_ids, load_dir, prose_schema


class HelpdeskPack:
    name = "helpdesk"
    prose_fields = ["what_it_is", "when_to_use", "steps", "checks", "escalate_to"]
    string_fields = ["what_it_is", "when_to_use", "escalate_to"]
    list_fields = ["steps", "checks"]

    def load(self, root: Path | None = None) -> list[SourceDoc]:
        root = Path(root) if root is not None else PACKS_DIR / self.name
        docs = load_dir(root, "sources/sops", "sop", ".md")
        if len({d.doc_id for d in docs}) != len(docs):
            raise PackError("duplicate SOP ids")
        return docs

    def units(self, docs: list[SourceDoc]) -> list[Unit]:
        by_id = {d.doc_id: d for d in docs}
        out = []
        for sid in sorted(by_id):
            sop = by_id[sid]
            rel = header_ids(sop, "related")
            for r in rel:
                if r not in by_id or r == sid:
                    raise PackError(f"{sop.path}: related names an unknown or the same SOP: {r!r}")
            out.append(Unit(sid, self.name, "procedure", [sop, *[by_id[r] for r in rel]]))
        return out

    def deterministic_fields(self, unit: Unit) -> dict[str, Any]:
        sop = unit.primary
        first = next((ln for ln in sop.lines if ln.strip()), sop.doc_id)
        title = first.lstrip("# ").strip()
        if title.lower().startswith("sop:"):
            title = title[4:].strip()
        return {
            "card_id": unit.unit_id,
            "pack": self.name,
            "kind": unit.kind,
            "title": title or sop.doc_id,
            "playbook_link": unit.docs[1].doc_id if len(unit.docs) > 1 else None,
            "source_shas": [{"doc_id": d.doc_id, "sha256": d.sha256} for d in unit.docs],
        }

    def tool_schema(self) -> dict[str, Any]:
        return prose_schema(self.string_fields, self.list_fields)
