"""ATT&CK id -> name table (attack/techniques.json, made by tools/make_techniques.py)."""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .paths import TECHNIQUES

ID_RE = re.compile(r"^T\d{4}(\.\d{3})?$")


@lru_cache(maxsize=1)
def load_techniques() -> dict[str, str]:
    data = json.loads(TECHNIQUES.read_text(encoding="utf-8"))
    return dict(data["techniques"])


def attack_url(tid: str) -> str | None:
    """Code-built ATT&CK URL for a well-formed id; None otherwise."""
    if not ID_RE.fullmatch(tid):
        return None
    return "https://attack.mitre.org/techniques/" + tid.replace(".", "/") + "/"
