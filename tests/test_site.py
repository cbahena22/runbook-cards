from __future__ import annotations

import base64
import copy
import hashlib
import re
from html.parser import HTMLParser

from runbook_cards import site
from runbook_cards.card import load_cards
from runbook_cards.paths import ROOT, TEMPLATES
from runbook_cards.site import render_pack

FIX = ROOT / "tests" / "fixtures" / "cards"
EVIL_TITLE = "</script><img src=x onerror=alert(1)>"
EVIL_LINE = '"><svg onload=alert(1)>'


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs, self.scripts, self.styles, self.meta, self.text = [], [], [], [], [], []
        self._in = None

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend((tag, k, v) for k, v in attrs)
        if tag == "meta":
            self.meta.append(dict(attrs))
        self._in = tag if tag in ("script", "style") else None

    def handle_endtag(self, tag):
        self._in = None

    def handle_data(self, data):
        if self._in == "script":
            self.scripts.append(data)
        elif self._in == "style":
            self.styles.append(data)
        else:
            self.text.append(data)


def parse(html):
    p = Page()
    p.feed(html)
    p.close()
    return p


def hostile_cards():
    card = copy.deepcopy(load_cards(FIX / "security")[0])
    card["title"] = EVIL_TITLE
    card["triage_tips"] = [EVIL_LINE]
    card["what_it_is"] = EVIL_LINE
    card["attack"] = ["T1059.001", "javascript:alert(1)"]
    card["injection_found"] = [{"doc_id": "rb-15", "start_line": 3, "end_line": 3, "quote": EVIL_TITLE}]
    card["queries"]["esql"]["query"] = EVIL_TITLE
    return [card]


def token(body):
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"


def test_hostile_text_renders_only_as_escaped_text():
    html = render_pack("security", hostile_cards())
    p = parse(html)
    assert p.tags.count("script") == 1
    assert "img" not in p.tags and "svg" not in p.tags
    assert EVIL_TITLE in "".join(p.text) and EVIL_LINE in "".join(p.text)
    assert "&lt;/script&gt;&lt;img" in html


def test_page_has_no_resources_handlers_or_style_attributes():
    for name in ("security", "helpdesk"):
        p = parse(render_pack(name, load_cards(FIX / name)))
        assert p.tags.count("script") == 1 and p.tags.count("style") == 1
        assert not [a for a in p.attrs if a[1] == "src"]
        assert not [a for a in p.attrs if a[1].startswith("on")]
        assert not [a for a in p.attrs if a[1] == "style"]
        assert "link" not in p.tags and "iframe" not in p.tags and "img" not in p.tags and "form" not in p.tags
        for tag, k, v in p.attrs:
            if k == "href":
                assert v.startswith("#card-") or v.startswith("https://attack.mitre.org/"), v
            if k in ("src", "action", "data"):
                assert not (v or "").startswith("http")


def test_csp_hashes_equal_script_and_style_bodies():
    p = parse(render_pack("security", load_cards(FIX / "security")))
    csp = next(m["content"] for m in p.meta if m.get("http-equiv") == "Content-Security-Policy")
    assert f"script-src {token(''.join(p.scripts))};" in csp
    assert f"style-src {token(''.join(p.styles))};" in csp
    for need in ("default-src 'none'", "img-src 'none'", "object-src 'none'", "base-uri 'none'", "form-action 'none'"):
        assert need in csp
    assert "unsafe-inline" not in csp and "http" not in csp


def test_script_uses_only_the_allowed_apis():
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "Function(", "fetch(", "XMLHttpRequest"):
        assert bad not in site.SCRIPT
    for need in ("textContent", "dataset", "hidden"):
        assert need in site.SCRIPT


def test_no_inline_json_and_no_safe_filter_in_templates():
    html = render_pack("helpdesk", load_cards(FIX / "helpdesk"))
    assert "application/json" not in html and "ld+json" not in html
    for t in TEMPLATES.glob("*"):
        text = t.read_text(encoding="utf-8")
        assert "|safe" not in text.replace(" ", "") and "autoescape false" not in text and "| safe" not in text


def test_jinja_environment_settings():
    src = (ROOT / "src/runbook_cards/site.py").read_text(encoding="utf-8")
    assert "autoescape=True" in src and "StrictUndefined" in src


def test_bad_attack_id_is_not_linked_and_good_one_is():
    html = render_pack("security", hostile_cards())
    assert "https://attack.mitre.org/techniques/T1059/001/" in html
    hrefs = [v for _, k, v in parse(html).attrs if k == "href"]
    assert hrefs and all(h.startswith("https://attack.mitre.org/") for h in hrefs)


def test_subtechnique_url_form():
    from runbook_cards.techniques import attack_url
    assert attack_url("T1059") == "https://attack.mitre.org/techniques/T1059/"
    assert attack_url("T1059.001") == "https://attack.mitre.org/techniques/T1059/001/"
    assert attack_url("T1059/../x") is None


def test_links_carry_rel_and_footer_notice():
    html = render_pack("security", load_cards(FIX / "security"))
    for m in re.finditer(r"<a [^>]*href=\"https://[^>]*>", html):
        assert 'rel="noopener noreferrer"' in m.group(0)
    assert "registered trademark of The MITRE Corporation" in html


def test_needs_human_banner_injection_box_and_sources():
    cards = load_cards(FIX / "helpdesk")
    bad = copy.deepcopy(cards[0])
    bad["status"], bad["status_reason"] = "needs human", "budget"
    html = render_pack("helpdesk", [bad, cards[1]])
    assert "Needs a human" in html and "(budget)" in html
    assert "Instruction-like text found in the source (not followed)" in html
    assert "sop-14-badge-access:" in html and "-" in html
    p = parse(html)
    assert sum(1 for t, k, v in p.attrs if k == "data-q") == 2


def test_playbook_anchor_links_only_to_cards_on_the_page():
    cards = load_cards(FIX / "helpdesk")
    html = render_pack("helpdesk", cards)  # sop-01 -> related sop-04 (not on page), sop-14 -> sop-02 (not on page)
    assert 'href="#card-sop-04' not in html
    cards[1]["playbook_link"] = cards[0]["card_id"]
    assert f'href="#card-{cards[0]["card_id"]}"' in render_pack("helpdesk", cards)


def test_build_is_deterministic():
    cards = load_cards(FIX / "security")
    assert render_pack("security", cards) == render_pack("security", list(reversed(cards)))


def test_page_has_no_absolute_paths_or_external_hosts():
    html = render_pack("security", load_cards(FIX / "security"))
    hosts = set(re.findall(r"https?://([^/\"' ]+)", html))
    assert hosts <= {"attack.mitre.org"}
    assert not re.search(r"file://|[A-Za-z]:\\\\", html)
