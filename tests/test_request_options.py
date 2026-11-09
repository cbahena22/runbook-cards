"""config.toml [request]: how a request asks for its one tool call, and what a failed call leaves in the store."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from runbook_cards.config import load_config, request_extras, strict_variant, tool_definition
from runbook_cards.draft import draft_request
from runbook_cards.grounding import grounding_request
from runbook_cards.llm import DETAIL_MAX, LiveSync, Request, Store, exc_detail
from runbook_cards.paths import CONFIG

CFG = load_config()


def with_request(tmp_path, body: str):
    text = CONFIG.read_text(encoding="utf-8")
    head = text.split("[request]")[0]
    tail = "[price_per_mtok]" + text.split("[price_per_mtok]")[1]
    p = tmp_path / "c.toml"
    p.write_text(head + body + tail, encoding="utf-8")
    return load_config(p)


def test_the_committed_config_asks_for_the_tool_with_auto_and_no_thinking():
    assert (CFG.tool_choice, CFG.thinking) == ("auto", "between_tools")
    assert request_extras(CFG, "t") == {"tool_choice": {"type": "auto"}, "thinking": {"type": "between_tools"}}


def test_forced_and_default_thinking_are_still_available(tmp_path):
    cfg = with_request(tmp_path, '[request]\ntool_choice = "forced"\nthinking = "omit"\n\n')
    assert request_extras(cfg, "write_card") == {"tool_choice": {"type": "tool", "name": "write_card"}}


def test_a_config_without_a_request_section_uses_the_defaults(tmp_path):
    cfg = with_request(tmp_path, "")
    assert (cfg.tool_choice, cfg.thinking) == ("auto", "between_tools")


def test_an_unknown_request_option_is_refused(tmp_path):
    with pytest.raises(ValueError):
        with_request(tmp_path, '[request]\ntool_choice = "any"\n\n')


def test_every_request_carries_the_options(security):
    pack, units = security
    d = draft_request(pack, units[0], CFG).body
    g = grounding_request(pack, {"card_id": "x", "source_shas": [{"doc_id": "a", "sha256": "b"}], "citations": {}}, units[0], CFG).body
    for body in (d, g):
        assert body["tool_choice"] == {"type": "auto"} and body["thinking"] == {"type": "between_tools"}


class BadRequestError(Exception):
    status_code = 400

    def __init__(self, message):
        super().__init__("never used")
        self.body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}


def test_a_rejected_call_keeps_the_exception_class_status_and_a_bounded_message(tmp_path):
    def boom(**kw):
        raise BadRequestError("tool_choice: type tool is not supported for this model. " + "x" * 1000)
    sdk = NS(messages=NS(create=boom, count_tokens=lambda **kw: NS(input_tokens=5)))
    req = Request("u1", "draft", {"model": "m", "max_tokens": 10, "system": "s", "messages": [], "tools": [], "tool_choice": {}})
    r = LiveSync(CFG, sdk=sdk).submit([req])[0]
    assert r.error == "error" and r.detail.startswith("BadRequestError 400: tool_choice: type tool is not supported")
    assert len(r.detail) <= len("BadRequestError 400: ") + DETAIL_MAX
    Store(tmp_path / "s").put(req, "h", r)
    rec = json.loads((tmp_path / "s" / "responses.jsonl").read_text(encoding="utf-8"))
    assert rec["detail"] == r.detail and "stop_reason" not in rec


def test_exc_detail_without_status_or_body_is_just_the_class():
    assert exc_detail(ValueError("secret")) == "ValueError"
    assert exc_detail(NS(status_code=None, body=None)) == "SimpleNamespace"


# ---- strict tools ----

UNSUPPORTED = {"maxLength", "minLength", "maximum", "minimum", "maxItems"}


def keys_anywhere(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from keys_anywhere(v)
    elif isinstance(node, list):
        for v in node:
            yield from keys_anywhere(v)


@pytest.mark.parametrize("name", ["security", "helpdesk"])
def test_strict_tools_carry_no_keyword_the_strict_decoder_refuses(name):
    from runbook_cards.packs import get_pack
    full = get_pack(name).tool_schema()
    strict = strict_variant(full)
    assert not UNSUPPORTED & set(keys_anywhere(strict))
    assert UNSUPPORTED & set(keys_anywhere(full))  # the full schema (our own check) still has the caps
    assert strict["additionalProperties"] is False and strict["required"] == full["required"]
    assert strict["properties"]["what_it_is"]["description"] == "at most 200 characters"
    assert "at most 2 spans" not in json.dumps(strict) and strict["properties"]["injection_found"]["description"] == "at most 2 items"
    assert strict_variant(strict) == strict  # idempotent
    assert full["properties"]["what_it_is"] == {"type": "string", "maxLength": 200}  # the input is not modified


def test_strict_tool_definition_and_the_off_switch(tmp_path):
    schema = {"type": "object", "properties": {"a": {"type": "string", "maxLength": 5}}, "required": ["a"], "additionalProperties": False}
    on = tool_definition(with_request(tmp_path, "[request]\nstrict = true\n\n"), "t", "d", schema)
    assert on["strict"] is True and on["input_schema"]["properties"]["a"] == {"type": "string", "description": "at most 5 characters"}
    off = tool_definition(with_request(tmp_path, "[request]\nstrict = false\n\n"), "t", "d", schema)
    assert off == {"name": "t", "description": "d", "input_schema": schema}
    with pytest.raises(ValueError):
        with_request(tmp_path, '[request]\nstrict = "yes"\n\n')


def test_the_committed_config_is_not_strict_and_the_requests_say_so(security):
    # strict: true failed with HTTP 400 "compiled grammar is too large" on the card schema (probe 2026-10-29), so the
    # committed config turns it off and our own validator checks every card.
    pack, units = security
    assert CFG.strict is False
    tool = draft_request(pack, units[0], CFG).body["tools"][0]
    assert "strict" not in tool and tool["input_schema"] == pack.tool_schema()


def test_the_strict_switch_still_puts_strict_true_on_the_drafting_request(security, tmp_path):
    pack, units = security
    cfg = with_request(tmp_path, "[request]\nstrict = true\n\n")
    tool = draft_request(pack, units[0], cfg).body["tools"][0]
    assert tool["strict"] is True and tool["input_schema"] == strict_variant(pack.tool_schema())


# ---- auto tool choice: a reply without the tool call is a recorded failure, never a card ----

def text_only(text="Here is your card: it detects things."):
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=NS(input_tokens=900, output_tokens=40))


def test_a_reply_with_no_tool_call_is_recorded_and_the_unit_is_needs_human(security, tmp_path):
    from runbook_cards.budget import Budget
    from runbook_cards.draft import draft_pack
    from runbook_cards.llm import Gateway
    pack, units = security
    unit = units[0]
    sdk = NS(messages=NS(create=lambda **kw: text_only(), count_tokens=lambda **kw: NS(input_tokens=900)))
    store = Store(tmp_path / "s")
    gw = Gateway(LiveSync(CFG, sdk=sdk), store, CFG, Budget(5, CFG.price_in, CFG.price_out))
    cards = draft_pack(pack, [unit], gw, CFG)
    card = cards[unit.unit_id]
    assert card["status"] == "needs human" and card["status_reason"] == "error"
    assert card["what_it_is"] == "" and card["citations"] == {} and "detects things" not in json.dumps(card)  # no model text kept
    rec = next(r for r in map(json.loads, (tmp_path / "s" / "responses.jsonl").read_text(encoding="utf-8").splitlines())
               if r["phase"] == "draft")
    assert rec["error"] == "error" and rec["tool_input"] is None and rec["stop_reason"] == "end_turn"
    assert rec["partial"].startswith("Here is your card")  # what the model wrote instead, bounded, for the diagnosis


def test_a_tool_call_with_an_unusable_input_is_also_needs_human(security, tmp_path):
    from runbook_cards.budget import Budget
    from runbook_cards.draft import draft_pack
    from runbook_cards.llm import Gateway
    pack, units = security
    unit = units[0]
    bad = NS(content=[NS(type="tool_use", input={"what_it_is": "x"})], stop_reason="tool_use",
             usage=NS(input_tokens=900, output_tokens=40))  # missing required fields
    sdk = NS(messages=NS(create=lambda **kw: bad, count_tokens=lambda **kw: NS(input_tokens=900)))
    gw = Gateway(LiveSync(CFG, sdk=sdk), Store(tmp_path / "s"), CFG, Budget(5, CFG.price_in, CFG.price_out))
    card = draft_pack(pack, [unit], gw, CFG)[unit.unit_id]
    assert card["status"] == "needs human" and card["status_reason"] == "validator" and card["what_it_is"] == ""
