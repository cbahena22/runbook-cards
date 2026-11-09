"""Packs: a source loader plus the rules for turning sources into units and cards."""
from __future__ import annotations

from .base import Pack, PackError
from .helpdesk import HelpdeskPack
from .security import SecurityPack

PACKS: dict[str, type] = {"security": SecurityPack, "helpdesk": HelpdeskPack}


def get_pack(name: str) -> Pack:
    if name not in PACKS:
        raise PackError(f"unknown pack: {name!r} (choose from {', '.join(sorted(PACKS))})")
    return PACKS[name]()
