"""Hardening: schema echo, per-prompt fences, fence brackets, retry spend, ASCII store, usage checks."""
from __future__ import annotations

import copy
import json
import re
import sys
from types import SimpleNamespace as NS

import pytest

from runbook_cards.budget import Budget
from runbook_cards.card import load_card
from runbook_cards.cli import main
from runbook_cards.config import load_config
from runbook_cards.draft import draft_request, evaluate, fence_for, needs_human
from runbook_cards.grounding import grounding_request
from runbook_cards.llm import SDK_MAX_RETRIES, Gateway, LiveSync, Reply, Result, Store, StoreError
from runbook_cards.paths import ROOT
from runbook_cards.validate import validate
from tests.fakes import USAGE, FakeModel, honest

CFG = load_config()


def reply(tool_input):
    return Result("x", "draft", "h", Reply(tool_input, dict(USAGE)))


def test_schema_problems_never_echo_model_text(security):
    pack, units = security
    marker = "ZQ" + "MARKER" + "9" * 6
    data = honest(units[0])
    data["triage_tips"] = marker * 30  # wrong type (string, not list) and long
    data["what_it_is"] = marker * 40  # long
    data["injection_found"] = [{"quote": marker}]  # wrong shape
    card, problems, hard = evaluate(pack, units[0], reply(data), CFG)
    assert card is None and hard is None and problems
    assert all(p.startswith("SCHEMA ") and "fails '" in p for p in problems), problems
    assert marker not in " ".join(problems)
    notes = "\n".join(f"- {p}" for p in problems)
    assert marker not in draft_request(pack, units[0], CFG, "redraft", notes).body["messages"][0]["content"]


def test_each_prompt_type_has_its_own_fence(security, helpdesk):
    seen = 0
    for pack, units in (security, helpdesk):
        for u in units:
            if len(u.docs) != 1:
                continue
            seen += 1
            card = copy.deepcopy(needs_human(pack, u, CFG, "validator"))
            card.update(what_it_is="x", citations={"what_it_is": []})
            text = grounding_request(pack, card, u, CFG).body["messages"][0]["content"]
            ground = re.search(r"\[\[text (\w+)\]\]", text).group(1)
            assert ground != fence_for(u) and ground != fence_for(u, "notes")
            assert fence_for(u) != fence_for(u, "notes")
    assert seen, "need at least one single-source unit"


FIX = ROOT / "tests" / "fixtures" / "cards"


def test_fence_brackets_in_a_model_field_are_refused_with_offsets_only(security):
    pack, units = security
    unit = next(u for u in units if u.unit_id == "chm-win-001")
    card = load_card(FIX / "security/chm-win-001.json")
    assert validate(card, unit, pack) == []
    for bad in ("Read [" + "[end abc123]" + " first", "Read " + "]" + "] first"):
        c = copy.deepcopy(card)
        c["triage_tips"][0] = bad
        got = [p for p in validate(c, unit, pack) if p.code == "FENCE_TOKEN"]
        assert got and "offsets" in str(got[0]) and "abc123" not in str(got[0])


def reqs_for(security, n):
    pack, units = security
    return [draft_request(pack, u, CFG) for u in units[:n]], {u.unit_id: u for u in units}


def test_timeout_is_charged_for_every_attempt(security, tmp_path):
    reqs, units = reqs_for(security, 2)

    class Slow(FakeModel):
        def submit(self, requests):
            return [Reply(None, error="timeout") for _ in requests]
    gw = Gateway(Slow(units), Store(tmp_path / "s"), CFG, Budget(5, CFG.price_in, CFG.price_out))
    gw.run(reqs)
    one = (3000 * CFG.price_in + CFG.draft_max_tokens * CFG.price_out) / 1e6  # count 3000 + max_tokens
    assert SDK_MAX_RETRIES == 2
    assert gw.budget.spent == pytest.approx(2 * (1 + SDK_MAX_RETRIES) * one)


def test_other_errors_are_charged_once(security, tmp_path):
    reqs, units = reqs_for(security, 2)

    class Errors(FakeModel):
        def submit(self, requests):
            return [Reply(None, error="error") for _ in requests]
    gw = Gateway(Errors(units), Store(tmp_path / "s"), CFG, Budget(5, CFG.price_in, CFG.price_out))
    gw.run(reqs)
    assert gw.budget.spent == pytest.approx(2 * (3000 * CFG.price_in + CFG.draft_max_tokens * CFG.price_out) / 1e6)


def test_sdk_is_built_with_the_retry_count_the_charge_assumes(monkeypatch):
    seen = {}
    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=lambda **kw: seen.update(kw) or NS()))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k" * 12)
    LiveSync(CFG)
    assert seen["max_retries"] == SDK_MAX_RETRIES


def test_store_is_written_as_ascii_escapes(security, tmp_path):
    reqs, _ = reqs_for(security, 1)
    hidden = chr(0x202E) + chr(0x200B)  # Cf: bidi override, zero-width space
    store = Store(tmp_path / "s")
    store.put(reqs[0], "h1", Reply({"what_it_is": "a" + hidden + "b"}, {"input_tokens": 1, "output_tokens": 1}))
    for name in ("requests.jsonl", "responses.jsonl"):
        assert (tmp_path / "s" / name).read_text(encoding="utf-8").isascii()
    raw = (tmp_path / "s" / "responses.jsonl").read_text(encoding="utf-8")
    assert "\\u202e" in raw and "\\u200b" in raw
    assert Store(tmp_path / "s", readonly=True).get("h1")["tool_input"]["what_it_is"] == "a" + hidden + "b"


BAD_USAGE = [{"input_tokens": -5, "output_tokens": 1}, {"input_tokens": 1, "output_tokens": "9"},
             {"input_tokens": 1.5, "output_tokens": 1}, {"input_tokens": True, "output_tokens": 1},
             {"input_tokens": 1, "output_tokens": None}, "lots", [1, 2]]


@pytest.mark.parametrize("usage", BAD_USAGE)
def test_store_with_bad_usage_is_refused(tmp_path, usage):
    rec = json.dumps({"hash": "a", "usage": usage, "error": None})
    (tmp_path / "responses.jsonl").write_text(rec + "\n", encoding="utf-8")
    with pytest.raises(StoreError, match=r"responses.jsonl:1: usage must hold non-negative integers"):
        Store(tmp_path)


def test_cli_refuses_a_reused_store_with_bad_usage(tmp_path):
    rec = json.dumps({"hash": "a", "usage": {"input_tokens": -1, "output_tokens": 1}, "error": None})
    (tmp_path / "responses.jsonl").write_text(rec + "\n", encoding="utf-8")
    assert main(["eval", "--live", "--budget", "1", "--record", str(tmp_path)]) == 2


def test_store_with_good_or_missing_usage_loads(tmp_path):
    lines = [{"hash": "a", "usage": {"input_tokens": 0, "output_tokens": 7}}, {"hash": "b"}, {"hash": "c", "usage": None}]
    (tmp_path / "responses.jsonl").write_text("\n".join(map(json.dumps, lines)) + "\n", encoding="utf-8")
    assert Store(tmp_path).total_usage() == {"input_tokens": 0, "output_tokens": 7}
