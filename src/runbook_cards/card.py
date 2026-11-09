"""Card files: JSON on disk, validated against schema/card.schema.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROSE_STRINGS = {"what_it_is", "why_it_flags", "when_to_use", "escalate_to"}
PROSE_LISTS = {"key_fields", "triage_tips", "steps", "checks"}


class CardError(Exception):
    pass


def load_card(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CardError(f"{Path(path).name}: not readable JSON") from None
    if not isinstance(data, dict):
        raise CardError(f"{Path(path).name}: a card must be a JSON object")
    return data


def dump_card(card: dict[str, Any], path: Path) -> None:
    """Write a card with a stable layout (sorted keys, 2-space indent, trailing newline)."""
    Path(path).write_text(json.dumps(card, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def load_cards(directory: Path) -> list[dict[str, Any]]:
    """All `*.json` cards of a directory, sorted by file name."""
    return [load_card(p) for p in sorted(Path(directory).glob("*.json"))]


def field_paths(card: dict[str, Any], prose_fields: list[str]) -> list[tuple[str, str]]:
    """(citation path, text) for every non-empty prose string and list item in a card."""
    out: list[tuple[str, str]] = []
    for f in prose_fields:
        v = card.get(f)
        if isinstance(v, str) and v:
            out.append((f, v))
        elif isinstance(v, list):
            out.extend((f"{f}[{i}]", x) for i, x in enumerate(v) if isinstance(x, str))
    return out
