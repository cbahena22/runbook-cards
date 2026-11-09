"""Drafting, redraft, grounding check - with the scripted stand-in for the model."""
from __future__ import annotations

import copy

import pytest

from runbook_cards.budget import Budget
from runbook_cards.config import load_config, strict_variant
from runbook_cards.draft import SYSTEM, draft_pack, draft_request, evaluate, fence_for, needs_human
from runbook_cards.grounding import Unsupported, grounding_request, parse_unsupported, redraft_note
from runbook_cards.llm import Gateway, Reply, Request, Result, Store
from runbook_cards.validate import validate
from tests.fakes import USAGE, FakeModel, honest

CFG = load_config()
BAD = [{"field": "what_it_is", "claim": "It also detects things the lines never say."}]


def gw(tmp_path, units, script=None, limit=50):
    fake = FakeModel({u.unit_id: u for u in units}, script)
    return Gateway(fake, Store(tmp_path / "s"), CFG, Budget(limit, CFG.price_in, CFG.price_out)), fake


def pick(security, *ids):
    pack, units = security
    return pack, [u for u in units if u.unit_id in ids]


def test_request_shape_one_tool_call_sources_as_data(security):
    pack, units = security
    r = draft_request(pack, units[0], CFG)
    b = r.body
    assert b["max_tokens"] == CFG.draft_max_tokens and b["model"] == CFG.model
    assert b["tool_choice"] == {"type": "auto"} and b["thinking"] == {"type": "between_tools"}  # config.toml [request]
    assert "write_card tool exactly once" in b["system"]
    assert "strict" not in b["tools"][0] and b["tools"][0]["input_schema"] == pack.tool_schema()  # config.toml [request] strict = false
    assert "write_card tool now" in b["messages"][0]["content"]
    assert "DATA" in b["system"] and "never add URLs" in b["system"].replace("Never add", "never add")
    text = b["messages"][0]["content"]
    fence = fence_for(units[0])
    assert f"[[source {units[0].primary.doc_id} {fence}]]" in text and "\n1: " in text and f"[[end {fence}]]" in text


def test_fence_depends_on_the_content(security):
    _, units = security
    assert fence_for(units[0]) != fence_for(units[1])


def test_valid_draft_is_grounded_and_code_fields_win(security, tmp_path):
    pack, units = pick(security, "chm-win-001")
    g, fake = gw(tmp_path, units)
    card = draft_pack(pack, units, g, CFG)["chm-win-001"]
    assert card["status"] == "grounded" and card["status_reason"] is None
    assert validate(card, units[0], pack) == []
    det = pack.deterministic_fields(units[0])
    assert all(card[k] == v for k, v in det.items())
    assert [r.phase for r in fake.calls] == ["draft", "ground"]


def test_invalid_then_fixed_by_one_redraft(security, tmp_path):
    pack, units = pick(security, "chm-win-003")
    g, fake = gw(tmp_path, units, {"chm-win-003": {"draft": "bad"}})
    card = draft_pack(pack, units, g, CFG)["chm-win-003"]
    assert card["status"] == "grounded"
    assert [r.phase for r in fake.calls] == ["draft", "redraft", "ground"]
    note = fake.calls[1].body["messages"][0]["content"]
    assert "KEY_FIELD" in note and "NoSuchField" not in note.split("rejected")[1]


def test_invalid_twice_is_needs_human_validator(security, tmp_path):
    pack, units = pick(security, "chm-win-005")
    g, fake = gw(tmp_path, units, {"chm-win-005": {"draft": "bad", "redraft": "bad"}})
    card = draft_pack(pack, units, g, CFG)["chm-win-005"]
    assert (card["status"], card["status_reason"]) == ("needs human", "validator")
    assert card["what_it_is"] == "" and card["key_fields"] == [] and card["citations"] == {}  # no unchecked model text
    assert validate(card, units[0], pack) == []
    assert [r.phase for r in fake.calls] == ["draft", "redraft"]  # exactly one redraft, no grounding


def test_unsupported_claim_redrafted_once_then_clean(security, tmp_path):
    pack, units = pick(security, "chm-win-007")
    g, fake = gw(tmp_path, units, {"chm-win-007": {"ground": [BAD]}})
    card = draft_pack(pack, units, g, CFG)["chm-win-007"]
    assert card["status"] == "grounded" and (card["unsupported_before"], card["unsupported_after"]) == (1, 0)
    assert [r.phase for r in fake.calls] == ["draft", "ground", "redraft-unsupported", "ground"]
    assert "never say" in fake.calls[2].body["messages"][0]["content"]


def test_unsupported_twice_is_needs_human_unsupported(security, tmp_path):
    pack, units = pick(security, "chm-win-009")
    g, _ = gw(tmp_path, units, {"chm-win-009": {"ground": [BAD, BAD]}})
    card = draft_pack(pack, units, g, CFG)["chm-win-009"]
    assert (card["status"], card["status_reason"]) == ("needs human", "unsupported")
    assert (card["unsupported_before"], card["unsupported_after"]) == (1, 1)


def test_redraft_that_fails_validation_is_needs_human_validator(security, tmp_path):
    pack, units = pick(security, "chm-win-007")
    g, _ = gw(tmp_path, units, {"chm-win-007": {"ground": [BAD], "redraft-unsupported": "bad"}})
    card = draft_pack(pack, units, g, CFG)["chm-win-007"]
    assert (card["status"], card["status_reason"]) == ("needs human", "validator")


def test_budget_stop_marks_units_needs_human_budget(security, tmp_path):
    pack, units = pick(security, "chm-win-001", "chm-win-002")
    g, fake = gw(tmp_path, units, limit=0.001)
    cards = draft_pack(pack, units, g, CFG)
    assert {c["status_reason"] for c in cards.values()} == {"budget"} and fake.calls == []


def test_helpdesk_cards_are_drafted_too(helpdesk, tmp_path):
    pack, units = helpdesk
    g, _ = gw(tmp_path, units[:3])
    cards = draft_pack(pack, units[:3], g, CFG)
    assert all(c["status"] == "grounded" and c["steps"] for c in cards.values())


def reply(tool_input):
    return Result("x", "draft", "h", Reply(tool_input, dict(USAGE)))


def test_schema_invalid_tool_input_becomes_problems(security):
    pack, units = security
    data = honest(units[0])
    data.pop("what_it_is")
    card, problems, hard = evaluate(pack, units[0], reply(data), CFG)
    assert card is None and hard is None and problems and problems[0].startswith("SCHEMA")
    data2 = honest(units[0])
    data2["extra"] = 1
    assert evaluate(pack, units[0], reply(data2), CFG)[0] is None
    assert evaluate(pack, units[0], reply(None), CFG)[1]  # None input is a problem, not a crash


def test_call_errors_are_hard_reasons(security):
    pack, units = security
    for why in ("timeout", "budget", "error"):
        res = Result("x", "draft", "h", Reply(None, error=why))
        assert evaluate(pack, units[0], res, CFG) == (None, [], why)


def test_needs_human_card_validates_for_every_reason(security):
    pack, units = security
    for why in ("budget", "timeout", "validator", "unsupported", "error"):
        assert validate(needs_human(pack, units[0], CFG, why), units[0], pack) == []


def test_grounded_card_with_a_reason_is_a_schema_problem(security):
    pack, units = security
    c = needs_human(pack, units[0], CFG, "budget")
    c["status"] = "grounded"
    assert any(p.code == "SCHEMA" for p in validate(c, units[0], pack))
    d = needs_human(pack, units[0], CFG, "budget")
    d["status_reason"] = None
    assert any(p.code == "SCHEMA" for p in validate(d, units[0], pack))


def test_grounding_request_holds_only_the_cited_lines(security):
    pack, units = security
    u = units[0]
    card = copy.deepcopy(needs_human(pack, u, CFG, "validator"))
    data = honest(u)
    card.update(what_it_is=data["what_it_is"], citations={"what_it_is": data["citations"]["what_it_is"]})
    r = grounding_request(pack, card, u, CFG)
    text = r.body["messages"][0]["content"]
    assert r.body["max_tokens"] == 400 and r.body["tools"][0]["name"] == "report_unsupported" and r.body["tool_choice"] == {"type": "auto"}
    assert data["what_it_is"] in text and "falsepositives" not in text and "level:" not in text


def test_parse_unsupported(security):
    pack, units = security
    card = {"what_it_is": "x", "citations": {}}
    assert parse_unsupported({"unsupported": []}, card, pack) == []
    got = parse_unsupported({"unsupported": [{"field": "nope", "claim": "c"}, {"field": "what_it_is", "claim": "d"}]}, card, pack)
    assert [g.field for g in got] == ["(card)", "what_it_is"]
    assert parse_unsupported({"unsupported": "x"}, card, pack) is None
    assert parse_unsupported(None, card, pack) is None
    assert parse_unsupported({"unsupported": [], "x": 1}, card, pack) is None


def test_redraft_note_lists_field_and_claim():
    note = redraft_note([Unsupported("what_it_is", "first claim"), Unsupported("steps[0]", "plain claim")])
    assert note == "- what_it_is: first claim\n- steps[0]: plain claim"


def test_source_text_cannot_close_its_own_fence(security):
    pack, units = security
    u = units[0]
    text = draft_request(pack, u, CFG).body["messages"][0]["content"]
    fence = fence_for(u)
    # a source can only forge a fence it can compute from its own hash, which it cannot know
    assert text.count(f"[[end {fence}]]") == len(u.docs)
