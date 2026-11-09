"""Test helpers: build a valid card for a unit from quotes that exist in its sources."""
from __future__ import annotations

from typing import Any

from runbook_cards.packs.base import Unit


def locate(unit: Unit, quote: str) -> dict[str, Any]:
    """A span for the first line of any unit doc that contains the quote."""
    for doc in unit.docs:
        for n, line in enumerate(doc.lines, 1):
            if quote in line:
                return {"doc_id": doc.doc_id, "start_line": n, "end_line": n, "quote": quote}
    raise AssertionError(f"quote not found in {unit.unit_id}: {quote!r}")


def build_card(pack: Any, unit: Unit, prose: dict[str, Any], quotes: dict[str, str],
               injection: list[str] | None = None, status: str = "grounded") -> dict[str, Any]:
    card = dict(pack.deterministic_fields(unit))
    card.update(prose)
    card["citations"] = {path: [locate(unit, q)] for path, q in quotes.items()}
    card["injection_found"] = [locate(unit, q) for q in (injection or [])]
    card.update(status=status, status_reason=None if status == "grounded" else "validator",
                prompt_version="fixture", model="fixture")
    return card
