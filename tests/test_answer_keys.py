from __future__ import annotations

import json
import re

from runbook_cards.packs.base import attack_ids, detection_fields, parse_rule
from runbook_cards.paths import ROOT

KEYS = ROOT / "evals" / "answer_key"


def load(name):
    return json.loads((KEYS / name).read_text(encoding="utf-8"))


def test_security_key_fields_exist_in_their_rules(security):
    key = load("security.json")["units"]
    units = {u.unit_id: u for u in security[1]}
    assert set(key) == set(units)
    for uid, exp in key.items():
        rule = parse_rule(units[uid].primary)
        assert exp["key_fields"], uid
        assert set(exp["key_fields"]) <= set(detection_fields(rule)), uid
        assert exp["attack"] == attack_ids(rule), uid
        assert exp["must_not_contain"], uid


def test_helpdesk_key_matches_each_sop(helpdesk):
    key = load("helpdesk.json")["units"]
    units = {u.unit_id: u for u in helpdesk[1]}
    assert set(key) == set(units)
    step = re.compile(r"^(?:\d+[.)]|Step \d+:)\s")
    for uid, exp in key.items():
        text = units[uid].primary
        n = sum(bool(step.match(ln)) for ln in text.lines)
        assert exp["steps_max"] <= 6 and exp["steps_min"] <= min(n, 6) <= exp["steps_max"], uid
        assert f"Escalate to: {exp['escalate_to']}" in text.lines, uid


def test_red_team_set_has_six_items_and_spans_are_real(security, helpdesk):
    items = load("redteam.json")["items"]
    assert len(items) == 6
    docs = {}
    for _, units in (security, helpdesk):
        for u in units:
            for d in u.docs:
                docs[d.doc_id] = d
    for it in items:
        sp = it["injected_span"]
        doc = docs[it["doc_id"]]
        assert " ".join(sp["quote"].split()) in " ".join(" ".join(doc.lines[sp["start_line"] - 1:sp["end_line"]]).split()), it["id"]
        assert it["must_not_appear_outside_injection_found"]
    kinds = {it["id"] for it in items}
    assert kinds == {"rt-ignore", "rt-comment", "rt-system", "rt-script", "rt-env", "rt-zwj"}
    assert sum(it["pack"] == "security" for it in items) == 4


def test_no_other_doc_carries_instructions(security, helpdesk):
    """Only the six red-team docs hold instruction-like text; the normal sources are clean."""
    red = {it["doc_id"] for it in load("redteam.json")["items"]}
    pat = re.compile(r"ignore (?:the|all)|SYSTEM:|Assistant:|evil\.example", re.IGNORECASE)
    for _, units in (security, helpdesk):
        for u in units:
            for d in u.docs:
                if d.doc_id not in red:
                    assert not any(pat.search(ln) for ln in d.lines), d.doc_id
