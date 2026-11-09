"""Static site: one self-contained HTML file per pack, safe from file://.

Safety rules (tested): Jinja2 autoescape on, StrictUndefined, no `|safe`; the only Markup values are
constants built here (the CSP, the one script, the one style). No inline JSON, no external resource, no event
attributes, no style attributes. The script only toggles `hidden` using `textContent` and `dataset`.
"""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any

import jinja2
from markupsafe import Markup

from .paths import TEMPLATES
from .techniques import attack_url

LABELS = {
    "what_it_is": "What it is", "why_it_flags": "Why it flags", "key_fields": "Key fields",
    "triage_tips": "Triage tips", "when_to_use": "When to use", "steps": "Steps", "checks": "Checks",
    "escalate_to": "Escalate to",
}
HEADINGS = {"security": "Security alert cards", "helpdesk": "IT helpdesk cards"}
BACKEND_LABEL = {"esql": "ES|QL", "kql": "KQL"}

STYLE = (
    ":root{color-scheme:light dark;--bg:#fff;--fg:#1b1f24;--mut:#59636e;--line:#d0d7de;--card:#f6f8fa;--warn:#9a6700}"
    "@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#9198a1;--line:#30363d;--card:#161b22;--warn:#d29922}}"
    "body{margin:0 auto;max-width:56rem;padding:1rem;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}"
    "h1{font-size:1.5rem}h2{font-size:1.2rem;margin:.2rem 0}h3{font-size:.95rem;margin:.8rem 0 .2rem}h4{font-size:.85rem;margin:.5rem 0 .1rem}"
    ".card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:1rem 0}"
    ".card[hidden]{display:none}.meta,.muted,.sub,.refs{color:var(--mut);font-size:.85rem}"
    ".banner{border-left:4px solid var(--warn);padding:.4rem .6rem;color:var(--warn);font-weight:600}"
    ".inj{border:1px dashed var(--warn);border-radius:6px;padding:0 .8rem}"
    "pre{overflow-x:auto;background:var(--bg);border:1px solid var(--line);padding:.5rem;border-radius:6px}"
    "input{width:100%;box-sizing:border-box;padding:.5rem;font:inherit}a{color:inherit}footer{color:var(--mut);font-size:.8rem}"
)
SCRIPT = (
    "(function(){var f=document.getElementById(\"filter\");"
    "var cards=document.querySelectorAll(\"article.card\");"
    "f.addEventListener(\"input\",function(){var q=f.value.toLowerCase();var n=0;"
    "cards.forEach(function(c){var m=c.dataset.q.indexOf(q)!==-1;c.hidden=!m;if(m){n++;}});"
    "document.getElementById(\"count\").textContent=n+\" of \"+cards.length+\" cards\";});})();"
)


def sha_token(body: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode("ascii") + "'"


def csp() -> str:
    return ("default-src 'none'; script-src " + sha_token(SCRIPT) + "; style-src " + sha_token(STYLE)
            + "; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")


def _slug(card_id: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", card_id.lower())[:64]


def _refs(card: dict[str, Any], path: str) -> str:
    spans = card.get("citations", {}).get(path, [])
    seen: list[str] = []
    for s in spans if isinstance(spans, list) else []:
        if isinstance(s, dict):
            t = f"{s.get('doc_id')}:{s.get('start_line')}-{s.get('end_line')}"
            if t not in seen:
                seen.append(t)
    return ", ".join(seen)


def _view(card: dict[str, Any], ids: set[str]) -> dict[str, Any]:
    fields = []
    for f, label in LABELS.items():
        v = card.get(f)
        if isinstance(v, str) and v:
            fields.append({"label": label, "text": v, "refs": _refs(card, f), "rows": None})
        elif isinstance(v, list) and v:
            fields.append({"label": label, "text": "", "refs": "", "rows": [
                {"text": str(x), "refs": _refs(card, f"{f}[{i}]")} for i, x in enumerate(v)]})
    attack = [{"id": str(a), "url": attack_url(str(a))} for a in card.get("attack", [])]
    queries = []
    for b, label in BACKEND_LABEL.items():
        q = card.get("queries", {}).get(b)
        if isinstance(q, dict):
            fm = [(str(k), v) for k, v in q.get("field_map", {}).items()]
            queries.append({"label": label, "query": q.get("query"), "error": q.get("error") or "conversion failed",
                            "field_map": fm})
    sources: list[str] = []
    for spans in card.get("citations", {}).values():
        for s in spans if isinstance(spans, list) else []:
            t = f"{s.get('doc_id')}:{s.get('start_line')}-{s.get('end_line')}"
            if t not in sources:
                sources.append(t)
    inj = [{"where": f"{s.get('doc_id')}:{s.get('start_line')}-{s.get('end_line')}", "quote": str(s.get("quote", ""))}
           for s in card.get("injection_found", [])]
    playbook = card.get("playbook_link")
    title = str(card.get("title", ""))
    return {
        "card_id": str(card.get("card_id", "")), "slug": _slug(str(card.get("card_id", ""))), "title": title,
        "kind": str(card.get("kind", "")), "attack": attack, "fields": fields, "queries": queries,
        "injection_found": inj, "needs_human": card.get("status") != "grounded",
        "status_reason": card.get("status_reason") or "unknown",
        "sources": ", ".join(sources) if sources else "none",
        "playbook": playbook, "playbook_anchor": _slug(playbook) if playbook in ids else None,
        "q": " ".join([title, str(card.get("card_id", "")), *[a["id"] for a in attack]]).lower(),
    }


def render_pack(pack: str, cards: list[dict[str, Any]]) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True,
                             undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    ids = {str(c.get("card_id")) for c in cards}
    views = [_view(c, ids) for c in sorted(cards, key=lambda c: str(c.get("card_id")))]
    # Markup wraps only constants built in this module (CSP, style, script), never card or source text.
    csp_m, style_m, script_m = (Markup(csp()), Markup(STYLE), Markup(SCRIPT))  # nosec B704
    return env.get_template("pack.html.j2").render(
        heading=HEADINGS.get(pack, pack), cards=views, csp=csp_m, style=style_m, script=script_m)


def build_site(pack: str, cards: list[dict[str, Any]], out: Path) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_pack(pack, cards), encoding="utf-8", newline="\n")
