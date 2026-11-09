"""Card validator: schema, span check, key-field subset, no links or markup, banned words, ATT&CK ids, caps."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jsonschema

from .card import field_paths
from .packs.base import Unit, detection_fields, is_hidden, parse_rule
from .paths import SCHEMA
from .techniques import ID_RE, load_techniques

MAX_FIELD_CHARS = 400
MAX_LIST_ITEMS = 6

URL_RE = re.compile(r"(?i)(?:\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:example|test|invalid)\b|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+/|\b[a-z][a-z0-9+.-]{1,20}://|\bwww\.|\bjavascript:|\bdata:|\bmailto:)")
FENCE_RE = re.compile(r"\[\[|\]\]")  # prompt fences are [[...]]; model-written fields may not hold them
MARKUP_RE = re.compile(r"<[A-Za-z/!?]|&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);|\]\(|<!--")


def hidden_chars(text: str) -> list[str]:
    """Offsets of invisible characters (see is_hidden)."""
    return [f"{i}" for i, ch in enumerate(text) if is_hidden(ch)]


@dataclass(frozen=True)
class Problem:
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.path}: {self.message}"


CODES = ["SCHEMA", "UNIT_MISMATCH", "DET_MISMATCH", "NO_SPAN", "SPAN_DOC", "SPAN_RANGE", "QUOTE_MISSING", "KEY_FIELD",
         "URL", "MARKUP", "ATTACK_FORMAT", "ATTACK_UNKNOWN", "TOO_LONG", "TOO_MANY_ITEMS", "HIDDEN_CHAR", "FENCE_TOKEN"]


@lru_cache(maxsize=1)
def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def norm(s: str) -> str:
    return " ".join(s.split())


def _spans(card: dict[str, Any], path: str) -> list[dict[str, Any]]:
    v = card.get("citations", {}).get(path, [])
    return [s for s in v if isinstance(s, dict)] if isinstance(v, list) else []


def check_span(span: dict[str, Any], unit: Unit) -> Problem | None:
    """None if the span's quote appears in lines[start-1:end] of one of the unit's docs."""
    doc = unit.doc(str(span.get("doc_id")))
    where = f"{span.get('doc_id')}:{span.get('start_line')}-{span.get('end_line')}"
    if doc is None:
        return Problem("SPAN_DOC", where, "the span names a document that is not part of this unit")
    s, e = span.get("start_line"), span.get("end_line")
    if not (isinstance(s, int) and isinstance(e, int) and 1 <= s <= e <= len(doc.lines)):
        return Problem("SPAN_RANGE", where, "the line range is outside the document")
    quote = str(span.get("quote", ""))
    if hidden_chars(quote):
        return Problem("HIDDEN_CHAR", where, "the quote holds invisible format characters")
    if not quote.strip() or norm(quote) not in norm("\n".join(doc.lines[s - 1:e])):
        return Problem("QUOTE_MISSING", where, "the quoted text does not appear in those lines")
    return None


def validate(card: dict[str, Any], unit: Unit, pack: Any | None = None) -> list[Problem]:
    """All problems found in a card. `pack` (optional) also checks the code-built fields."""
    problems: list[Problem] = []
    for err in sorted(_validator().iter_errors(card), key=lambda e: list(map(str, e.absolute_path))):
        loc = ".".join(str(p) for p in err.absolute_path) or "(card)"
        problems.append(Problem("SCHEMA", loc, err.message[:160]))
    if problems:
        return problems  # later checks assume the shape
    if card["card_id"] != unit.unit_id or card["pack"] != unit.pack or card["kind"] != unit.kind:
        problems.append(Problem("UNIT_MISMATCH", "card_id", "card does not belong to this unit"))
    if pack is not None:
        det = pack.deterministic_fields(unit)
        for k, want in det.items():
            if card.get(k) != want:
                problems.append(Problem("DET_MISMATCH", k, "differs from the value built by code"))
    prose_fields = pack.prose_fields if pack is not None else sorted(
        {"what_it_is", "why_it_flags", "key_fields", "triage_tips", "when_to_use", "steps", "checks", "escalate_to"})
    for f in prose_fields:
        v = card.get(f)
        if isinstance(v, list) and len(v) > MAX_LIST_ITEMS:
            problems.append(Problem("TOO_MANY_ITEMS", f, f"more than {MAX_LIST_ITEMS} items"))
    for path, text in field_paths(card, prose_fields):
        if len(text) > MAX_FIELD_CHARS:
            problems.append(Problem("TOO_LONG", path, f"longer than {MAX_FIELD_CHARS} characters"))
        hidden = hidden_chars(text)
        if hidden:  # offsets only: the character itself is invisible and must not be echoed
            problems.append(Problem("HIDDEN_CHAR", path, "invisible format characters at character offsets " + ", ".join(hidden[:8])))
        brackets = [f"{m.start()}" for m in FENCE_RE.finditer(text)]
        if brackets:  # offsets only: the prompt fences are written as double brackets
            problems.append(Problem("FENCE_TOKEN", path, "fence brackets at character offsets " + ", ".join(brackets[:8])))
        if URL_RE.search(text):
            problems.append(Problem("URL", path, "links are not allowed in model-written fields"))
        if MARKUP_RE.search(text):
            problems.append(Problem("MARKUP", path, "markup-looking text is not allowed in model-written fields"))
        spans = _spans(card, path)
        if not spans:
            problems.append(Problem("NO_SPAN", path, "no supporting span"))
        for sp in spans:
            p = check_span(sp, unit)
            if p:
                problems.append(Problem(p.code, f"{path} -> {p.path}", p.message))
    valid_paths = {p for p, _ in field_paths(card, prose_fields)}
    for key in card["citations"]:
        if key not in valid_paths:
            problems.append(Problem("SPAN_DOC", key, "citation for a field that has no text"))
    for sp in card["injection_found"]:
        p = check_span(sp, unit)
        if p:
            problems.append(Problem(p.code, f"injection_found -> {p.path}", p.message))
    if unit.pack == "security":
        allowed = set(detection_fields(parse_rule(unit.primary)))
        for i, name in enumerate(card.get("key_fields", [])):
            if name not in allowed:
                problems.append(Problem("KEY_FIELD", f"key_fields[{i}]", "not a field used by the rule's detection"))
    known = load_techniques()
    for i, tid in enumerate(card.get("attack", [])):
        if not ID_RE.fullmatch(tid):
            problems.append(Problem("ATTACK_FORMAT", f"attack[{i}]", "not an ATT&CK technique id"))
        elif tid not in known:
            problems.append(Problem("ATTACK_UNKNOWN", f"attack[{i}]", "id not in attack/techniques.json"))
    return problems
