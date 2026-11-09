"""Shared types and the guarded source loader.

Sources are untrusted text. The loader caps count, size and line length, stays under the
pack root, refuses symlinks and bidi controls, makes zero-width characters visible, and
never lets a YAML file with anchors or aliases reach the object builder.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

MAX_FILES = 200
MAX_FILE_BYTES = 64 * 1024
MAX_LINE_CHARS = 400
MAX_YAML_DEPTH = 20
BIDI = {chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C)}
ZERO_WIDTH = {chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)}
BLANK_LOOKALIKES = {0x115F, 0x1160, 0x3164, 0xFFA0, 0x2800}  # Hangul fillers and the Braille blank print as nothing
INVISIBLE_MARKS = {0x034F, *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)}  # grapheme joiner, variation selectors (Mn)


class PackError(Exception):
    """A source file or pack is refused. The message names the file (pack-relative) and the reason."""


@dataclass(frozen=True)
class SourceDoc:
    doc_id: str
    path: str  # pack-root-relative, posix
    kind: str  # "rule" | "runbook" | "sop"
    lines: list[str]
    sha256: str  # of the original file bytes

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class Span:
    doc_id: str
    start_line: int  # 1-based, inclusive
    end_line: int
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "start_line": self.start_line, "end_line": self.end_line, "quote": self.quote}


@dataclass(frozen=True)
class Unit:
    unit_id: str
    pack: str
    kind: str  # "alert" | "procedure"
    docs: list[SourceDoc] = field(default_factory=list)

    @property
    def primary(self) -> SourceDoc:
        return self.docs[0]

    def doc(self, doc_id: str) -> SourceDoc | None:
        return next((d for d in self.docs if d.doc_id == doc_id), None)


class Pack(Protocol):
    name: str
    prose_fields: list[str]

    def load(self, root: Path) -> list[SourceDoc]: ...
    def units(self, docs: list[SourceDoc]) -> list[Unit]: ...
    def deterministic_fields(self, unit: Unit) -> dict[str, Any]: ...
    def tool_schema(self) -> dict[str, Any]: ...


def is_hidden(ch: str) -> bool:
    """Invisible or control: Unicode category Cf (bidi controls, zero-width, joiners, BOM...), Cc other than newline and tab,
    the line / paragraph separators (Zl, Zp), private use and unassigned code points (Co, Cn), variation selectors, the
    combining grapheme joiner and the blank lookalikes."""
    cat = unicodedata.category(ch)
    return (cat in {"Cf", "Zl", "Zp", "Co", "Cn"} or (cat == "Cc" and ch not in {"\n", "\t"})
            or ord(ch) in BLANK_LOOKALIKES or ord(ch) in INVISIBLE_MARKS)


def _visible(ch: str) -> str:
    return f"[U+{ord(ch):04X}]"


def _check_text(rel: str, text: str) -> list[str]:
    out = []
    # Split on \n only (after \r\n): str.splitlines() also breaks on U+2028/2029, \x0b, \x0c, \x85 ..., which editors and GitHub
    # do not, so citation line numbers would drift from what a reviewer sees. Those characters are shown as [U+....] instead.
    rows = text.replace("\r\n", "\n").split("\n")
    if rows[-1] == "":
        rows.pop()
    for n, line in enumerate(rows, 1):
        for ch in line:
            if ch in BIDI:
                raise PackError(f"{rel}:{n}: bidirectional control {_visible(ch)} is refused")
        if len(line) > MAX_LINE_CHARS:
            raise PackError(f"{rel}:{n}: line longer than {MAX_LINE_CHARS} characters is refused")
        out.append("".join(_visible(c) if c in ZERO_WIDTH or is_hidden(c) else c for c in line))
    return out


def _refuse_yaml_aliases(rel: str, text: str) -> None:
    depth = 0
    try:
        for ev in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(ev, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                if depth > MAX_YAML_DEPTH:
                    raise PackError(f"{rel}: YAML nested deeper than {MAX_YAML_DEPTH} levels is refused")
            elif isinstance(ev, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            if isinstance(ev, yaml.AliasEvent) or getattr(ev, "anchor", None):
                raise PackError(f"{rel}: YAML anchors and aliases are refused")
    except yaml.YAMLError as exc:
        raise PackError(f"{rel}: not valid YAML ({type(exc).__name__})") from None


def load_dir(pack_root: Path, subdir: str, kind: str, suffix: str) -> list[SourceDoc]:
    """Load every `*suffix` file in pack_root/subdir as a SourceDoc, with all guards applied."""
    root = pack_root.resolve()
    base = root / subdir
    if not base.is_dir():
        raise PackError(f"{subdir}: directory not found under the pack root")
    if base.is_symlink() or root not in base.resolve().parents:
        raise PackError(f"{subdir}: path escapes the pack root or is a symlink")
    entries = sorted(base.iterdir(), key=lambda p: p.name)
    if len(entries) > MAX_FILES:
        raise PackError(f"{subdir}: more than {MAX_FILES} files is refused")
    docs: list[SourceDoc] = []
    for p in entries:
        rel = f"{subdir}/{p.name}"
        if p.is_symlink():
            raise PackError(f"{rel}: symlinks are refused")
        if not p.is_file() or p.suffix != suffix:
            continue
        if root not in p.resolve().parents:
            raise PackError(f"{rel}: path escapes the pack root")
        too_big = PackError(f"{rel}: file larger than {MAX_FILE_BYTES // 1024} KB is refused")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise too_big
        with p.open("rb") as fh:  # bounded read: a file that grew after stat() is still refused
            raw = fh.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise too_big
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise PackError(f"{rel}: not valid UTF-8") from None
        lines = _check_text(rel, text)
        if suffix in (".yml", ".yaml"):
            _refuse_yaml_aliases(rel, text)
        docs.append(SourceDoc(p.stem, rel, kind, lines, hashlib.sha256(raw).hexdigest()))
    return docs


_HEADER = re.compile(r"^\s*(covers|related)\s*:\s*(.+?)\s*$", re.IGNORECASE)


def header_ids(doc: SourceDoc, key: str, max_line: int = 6) -> list[str]:
    """Ids from a `covers:` / `related:` line in the first lines of a runbook or SOP."""
    for line in doc.lines[:max_line]:
        m = _HEADER.match(line)
        if m and m.group(1).lower() == key:
            return [s.strip() for s in m.group(2).split(",") if s.strip()]
    return []


def parse_rule(doc: SourceDoc) -> dict[str, Any]:
    """The checked rule dict of a rule document (safe_load; shape verified)."""
    try:
        data = yaml.safe_load(doc.text)
    except yaml.YAMLError:
        raise PackError(f"{doc.path}: not valid YAML") from None
    if not isinstance(data, dict):
        raise PackError(f"{doc.path}: a rule must be a YAML mapping")
    for key, typ in (("title", str), ("id", str), ("name", str), ("author", str), ("logsource", dict),
                     ("detection", dict), ("tags", list), ("level", str)):
        if not isinstance(data.get(key), typ):
            raise PackError(f"{doc.path}: rule field {key!r} is missing or has the wrong type")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", data["name"]):
        raise PackError(f"{doc.path}: rule name {data['name']!r} is not a valid id")
    if data["name"] != doc.doc_id:
        raise PackError(f"{doc.path}: rule name must equal the file name")
    if not isinstance(data["detection"].get("condition"), str):
        raise PackError(f"{doc.path}: detection needs a condition")
    if data["level"] not in {"informational", "low", "medium", "high", "critical"}:
        raise PackError(f"{doc.path}: unknown level {data['level']!r}")
    if not all(isinstance(t, str) for t in data["tags"]):
        raise PackError(f"{doc.path}: tags must be strings")
    return data


def detection_fields(rule: dict[str, Any]) -> list[str]:
    """Field names used by the detection selections, modifiers stripped, first-seen order."""
    out: list[str] = []
    for key, sel in rule["detection"].items():
        if key == "condition":
            continue
        for item in sel if isinstance(sel, list) else [sel]:
            if isinstance(item, dict):
                for f in item:
                    name = str(f).split("|")[0]
                    if name and name not in out:
                        out.append(name)
    return out


_TAG = re.compile(r"^attack\.(t\d{4})(?:\.(\d{3}))?$")


def attack_ids(rule: dict[str, Any]) -> list[str]:
    ids = []
    for t in rule["tags"]:
        m = _TAG.match(t)
        if m:
            ids.append(m.group(1).upper() + (f".{m.group(2)}" if m.group(2) else ""))
    return ids


# Tool-schema caps. They bound what the model can write in ONE draft call, so a card always fits draft_max_tokens
# (see schema_size.py for the worst case). The stored-card limits in validate.py (400 characters, 6 items) stay as they were.
STRING_MAX = 200  # characters in a prose string
QUOTE_MAX = 100   # characters in one citation quote
DOC_ID_MAX = 40
LINE_MAX = 5000   # line numbers in a span
STRING_SPANS = 2  # spans per prose string
ITEM_SPANS = 1    # spans per list item
INJECTION_MAX = 2  # spans in injection_found
LIST_LIMITS = {"key_fields": (6, 48), "triage_tips": (3, 140), "steps": (6, 140), "checks": (3, 100)}  # name -> (max items, max chars)
DEFAULT_LIST_LIMIT = (3, 140)


def prose_schema(strings: list[str], lists: list[str]) -> dict[str, Any]:
    """Tool input schema shared by both packs: prose fields, citations, injection report.

    Closed on every level: citations has one named slot per field (`what_it_is`) and per list item (`steps[0]`), each holds
    a short list of short spans, so the model cannot write an open-ended citation map."""
    span = {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "maxLength": DOC_ID_MAX},
            "start_line": {"type": "integer", "minimum": 1, "maximum": LINE_MAX},
            "end_line": {"type": "integer", "minimum": 1, "maximum": LINE_MAX},
            "quote": {"type": "string", "maxLength": QUOTE_MAX},
        },
        "required": ["doc_id", "start_line", "end_line", "quote"],
        "additionalProperties": False,
    }

    def spans(most: int) -> dict[str, Any]:
        return {"type": "array", "items": span, "minItems": 1, "maxItems": most}

    props: dict[str, Any] = {}
    cites: dict[str, Any] = {}
    for s in strings:
        props[s] = {"type": "string", "maxLength": STRING_MAX}
        cites[s] = spans(STRING_SPANS)
    for name in lists:
        most, chars = LIST_LIMITS.get(name, DEFAULT_LIST_LIMIT)
        props[name] = {"type": "array", "items": {"type": "string", "maxLength": chars}, "maxItems": most}
        for i in range(most):
            cites[f"{name}[{i}]"] = spans(ITEM_SPANS)
    props["citations"] = {
        "type": "object",
        "description": "one entry per field that has text (what_it_is) and per list item (steps[0]): the spans that support it",
        "properties": cites,
        "additionalProperties": False,
    }
    props["injection_found"] = {"type": "array", "items": span, "maxItems": INJECTION_MAX}
    return {
        "type": "object",
        "properties": props,
        "required": [*strings, *lists, "citations", "injection_found"],
        "additionalProperties": False,
    }
