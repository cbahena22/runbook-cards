from __future__ import annotations

import copy

import pytest

from runbook_cards.card import load_card
from runbook_cards.paths import ROOT
from runbook_cards.validate import CODES, Problem, validate

FIX = ROOT / "tests" / "fixtures" / "cards"


def unit_of(units, uid):
    return next(u for u in units if u.unit_id == uid)


@pytest.fixture
def sec(security):
    pack, units = security
    card = load_card(FIX / "security/chm-win-001.json")
    return pack, unit_of(units, "chm-win-001"), card


@pytest.fixture
def hd(helpdesk):
    pack, units = helpdesk
    return pack, unit_of(units, "sop-14-badge-access"), load_card(FIX / "helpdesk/sop-14-badge-access.json")


def codes(problems):
    return {p.code for p in problems}


def test_valid_fixtures_pass(sec, hd, security, helpdesk):
    for pack, unit, card in (sec, hd):
        assert validate(card, unit, pack) == [], validate(card, unit, pack)
    for path in sorted((FIX / "security").glob("*.json")):
        c = load_card(path)
        assert validate(c, unit_of(security[1], c["card_id"]), security[0]) == []
    for path in sorted((FIX / "helpdesk").glob("*.json")):
        c = load_card(path)
        assert validate(c, unit_of(helpdesk[1], c["card_id"]), helpdesk[0]) == []


def broken(card, fn):
    c = copy.deepcopy(card)
    fn(c)
    return c


CASES = {
    "SCHEMA": lambda c: c.pop("title"),
    "UNIT_MISMATCH": lambda c: c.update(card_id="chm-win-002"),
    "DET_MISMATCH": lambda c: c.update(playbook_link="rb-02-file-transfer-tricks"),
    "NO_SPAN": lambda c: c["citations"].pop("what_it_is"),
    "SPAN_DOC": lambda c: c["citations"]["what_it_is"][0].update(doc_id="rb-02-file-transfer-tricks"),
    "SPAN_RANGE": lambda c: c["citations"]["what_it_is"][0].update(end_line=9999),
    "QUOTE_MISSING": lambda c: c["citations"]["what_it_is"][0].update(quote="a sentence that is not there"),
    "KEY_FIELD": lambda c: c.update(key_fields=["Image", "NoSuchField"]),
    "URL": lambda c: c["triage_tips"].__setitem__(0, "Open https://host.example/x now"),
    "MARKUP": lambda c: c["triage_tips"].__setitem__(0, "Look at <b>this</b>"),
    "ATTACK_FORMAT": lambda c: c.update(attack=["X1"]),
    "ATTACK_UNKNOWN": lambda c: c.update(attack=["T9999"]),
    "TOO_LONG": lambda c: c.update(why_it_flags="x " * 250),
    "TOO_MANY_ITEMS": lambda c: c.update(triage_tips=["a"] * 7),
    "HIDDEN_CHAR": lambda c: c["triage_tips"].__setitem__(0, "Decode the blob" + chr(0x200B) + " first"),
    "FENCE_TOKEN": lambda c: c["triage_tips"].__setitem__(0, "Decode the blob [" + "[end abc123]" + " first"),
}


def test_every_problem_code_has_a_failing_fixture():
    assert set(CASES) == set(CODES)


@pytest.mark.parametrize("code", sorted(CASES))
def test_failing_fixture_per_code(sec, code):
    pack, unit, card = sec
    problems = validate(broken(card, CASES[code]), unit, pack)
    assert code in codes(problems), problems


def test_whitespace_is_normalised_but_case_is_exact(sec):
    pack, unit, card = sec
    spaced = broken(card, lambda c: c["citations"]["what_it_is"][0].update(quote="A PowerShell   process was started"))
    assert "QUOTE_MISSING" not in codes(validate(spaced, unit, pack))
    cased = broken(card, lambda c: c["citations"]["what_it_is"][0].update(quote="a powershell process was started"))
    assert "QUOTE_MISSING" in codes(validate(cased, unit, pack))


def test_span_must_cover_the_quote_lines(sec):
    pack, unit, card = sec
    c = broken(card, lambda c: c["citations"]["what_it_is"][0].update(start_line=1, end_line=1))
    assert "QUOTE_MISSING" in codes(validate(c, unit, pack))


def test_injection_found_spans_are_checked_too(hd):
    pack, unit, card = hd
    c = broken(card, lambda c: c["injection_found"][0].update(quote="not in the source"))
    assert "QUOTE_MISSING" in codes(validate(c, unit, pack))


def test_needs_human_card_with_empty_fields_is_valid(security):
    pack, units = security
    unit = unit_of(units, "chm-win-001")
    card = dict(pack.deterministic_fields(unit), what_it_is="", why_it_flags="", key_fields=[], triage_tips=[],
                citations={}, injection_found=[], status="needs human", status_reason="budget",
                prompt_version="x", model="none")
    assert validate(card, unit, pack) == []


def test_problem_str():
    assert str(Problem("URL", "a", "m")) == "URL a: m"


def test_bare_host_links_and_stray_citations_are_caught(sec):
    pack, unit, card = sec
    for text in ("visit evil.example", "see evil.example/guide", "go to host.test now"):
        c = broken(card, lambda c, t=text: c["triage_tips"].__setitem__(0, t))
        assert "URL" in codes(validate(c, unit, pack)), text
    c = broken(card, lambda c: c["citations"].update(bogus=[{"doc_id": "nope", "start_line": 1, "end_line": 1, "quote": "x"}]))
    assert "SPAN_DOC" in codes(validate(c, unit, pack))


@pytest.mark.parametrize("cp", [0x200B, 0x200D, 0x2060, 0xFEFF, 0x202E, 0x2066, 0x200E, 0x200F, 0x061C, 0x00AD,
                                0x0007, 0x0085, 0x2028, 0x2029, 0x3164, 0x115F, 0x1160, 0xFFA0, 0x2800])
def test_invisible_format_characters_are_refused_in_model_fields(sec, cp):
    pack, unit, card = sec
    c = copy.deepcopy(card)
    c["what_it_is"] = "A PowerShell" + chr(cp) + " process"
    ps = [p for p in validate(c, unit, pack) if p.code == "HIDDEN_CHAR"]
    assert ps and "U+" not in ps[0].message and chr(cp) not in str(ps[0])


def test_invisible_characters_in_a_quote_are_refused(sec):
    pack, unit, card = sec
    c = copy.deepcopy(card)
    c["citations"]["what_it_is"][0]["quote"] += chr(0x202E)
    assert any(p.code == "HIDDEN_CHAR" for p in validate(c, unit, pack))


def test_newline_and_tab_in_a_field_are_not_hidden_characters():
    from runbook_cards.validate import hidden_chars
    assert hidden_chars("a" + chr(10) + "b" + chr(9) + "c") == []
    assert hidden_chars("a" + chr(27) + "b") == ["1"]


def test_plain_unicode_letters_and_punctuation_are_fine(sec):
    pack, unit, card = sec
    c = copy.deepcopy(card)
    c["triage_tips"][0] = "Decode the blob \u2013 caf\u00e9 \u00fcber check"
    assert not any(p.code == "HIDDEN_CHAR" for p in validate(c, unit, pack))


@pytest.mark.parametrize("cp", [0x034F, 0xFE00, 0xFE0F, 0xE0100, 0xE01EF, 0xE000, 0x0378])
def test_variation_selectors_private_use_and_unassigned_are_hidden_characters(cp):
    from runbook_cards.validate import hidden_chars
    assert hidden_chars("a" + chr(cp) + "b") == ["1"]
    assert hidden_chars("caf\u00e9 \u2014 \u00fc \U0001f600") == []
