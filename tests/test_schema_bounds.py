"""The draft tool schema bounds one model reply: every field, list, citation and quote has a cap, so a card fits max_tokens."""
from __future__ import annotations

import copy
import json

import jsonschema
import pytest

from runbook_cards.config import load_config
from runbook_cards.draft import SYSTEM
from runbook_cards.packs import get_pack
from runbook_cards.packs.base import DOC_ID_MAX, INJECTION_MAX, ITEM_SPANS, LINE_MAX, LIST_LIMITS, QUOTE_MAX, STRING_MAX, STRING_SPANS
from runbook_cards.schema_size import max_chars, max_tokens_estimate

CFG = load_config()
PACKS = ("security", "helpdesk")


def full_instance(schema):
    """The largest tool input the schema allows: every field at its cap, every citation slot filled to its cap."""
    def build(s):
        t = s["type"]
        if t == "string":
            return "x" * s["maxLength"]
        if t == "integer":
            return s["maximum"]
        if t == "array":
            return [build(s["items"]) for _ in range(s["maxItems"])]
        return {k: build(v) for k, v in s["properties"].items()}
    return build(schema)


@pytest.mark.parametrize("name", PACKS)
def test_worst_case_reply_fits_well_under_the_draft_limit(name):
    schema = get_pack(name).tool_schema()
    est = max_tokens_estimate(schema)
    assert est <= 0.65 * CFG.draft_max_tokens, f"{name}: worst case ~{est} tokens vs draft_max_tokens {CFG.draft_max_tokens}"


@pytest.mark.parametrize("name", PACKS)
def test_the_computed_worst_case_is_the_real_largest_reply(name):
    schema = get_pack(name).tool_schema()
    inst = full_instance(schema)
    jsonschema.Draft202012Validator(schema).validate(inst)
    assert len(json.dumps(inst, separators=(",", ":"))) == max_chars(schema)


@pytest.mark.parametrize("name", PACKS)
def test_every_string_array_and_integer_in_the_schema_is_capped(name):
    def walk(s):
        if s["type"] == "string":
            assert "maxLength" in s
        elif s["type"] == "integer":
            assert "maximum" in s
        elif s["type"] == "array":
            assert "maxItems" in s
            walk(s["items"])
        else:
            assert s["additionalProperties"] is False and s["properties"]
            for v in s["properties"].values():
                walk(v)
    walk(get_pack(name).tool_schema())


def test_max_chars_refuses_an_uncapped_schema():
    for bad in ({"type": "string"}, {"type": "integer"}, {"type": "array", "items": {"type": "string", "maxLength": 1}},
                {"type": "object", "properties": {"a": {"type": "string", "maxLength": 1}}}):
        with pytest.raises(ValueError):
            max_chars(bad)


@pytest.fixture(params=PACKS)
def pack_schema(request):
    pack = get_pack(request.param)
    return pack, jsonschema.Draft202012Validator(pack.tool_schema())


def small(pack):
    """A valid minimal reply for the pack."""
    sp = {"doc_id": "d", "start_line": 1, "end_line": 1, "quote": "q"}
    out = {f: "t" for f in pack.string_fields}
    out.update({f: ["t"] for f in pack.list_fields})
    out["citations"] = {f: [sp] for f in pack.string_fields}
    out["citations"].update({f"{f}[0]": [sp] for f in pack.list_fields})
    out["injection_found"] = []
    return out


def fails(v, inst):
    return bool(list(v.iter_errors(inst)))


def test_a_small_honest_reply_is_valid(pack_schema):
    pack, v = pack_schema
    assert not fails(v, small(pack))


def test_citations_are_a_closed_set_of_slots(pack_schema):
    pack, v = pack_schema
    inst = small(pack)
    inst["citations"]["not_a_field"] = inst["citations"][pack.string_fields[0]]
    assert fails(v, inst)
    inst = small(pack)
    last = pack.list_fields[0]
    most = LIST_LIMITS[last][0]
    inst["citations"][f"{last}[{most}]"] = inst["citations"][f"{last}[0]"]  # one slot past the list cap
    assert fails(v, inst)


def test_span_counts_and_sizes_are_capped(pack_schema):
    pack, v = pack_schema
    base = small(pack)
    s0 = pack.string_fields[0]
    sp = base["citations"][s0][0]

    def mutated(fn):
        inst = copy.deepcopy(base)
        fn(inst)
        return inst
    assert not fails(v, mutated(lambda i: i["citations"].__setitem__(s0, [sp] * STRING_SPANS)))
    assert fails(v, mutated(lambda i: i["citations"].__setitem__(s0, [sp] * (STRING_SPANS + 1))))
    item = f"{pack.list_fields[0]}[0]"
    assert fails(v, mutated(lambda i: i["citations"].__setitem__(item, [sp] * (ITEM_SPANS + 1))))
    assert fails(v, mutated(lambda i: i["citations"].__setitem__(item, [])))
    assert not fails(v, mutated(lambda i: i.__setitem__("injection_found", [sp] * INJECTION_MAX)))
    assert fails(v, mutated(lambda i: i.__setitem__("injection_found", [sp] * (INJECTION_MAX + 1))))
    for key, ok, bad in (("quote", "q" * QUOTE_MAX, "q" * (QUOTE_MAX + 1)), ("doc_id", "d" * DOC_ID_MAX, "d" * (DOC_ID_MAX + 1)),
                         ("end_line", LINE_MAX, LINE_MAX + 1)):
        assert not fails(v, mutated(lambda i: i["citations"][s0][0].__setitem__(key, ok)))
        assert fails(v, mutated(lambda i: i["citations"][s0][0].__setitem__(key, bad)))


def test_prose_lengths_and_list_sizes_are_capped(pack_schema):
    pack, v = pack_schema
    base = small(pack)
    s0 = pack.string_fields[0]
    assert not fails(v, {**base, s0: "t" * STRING_MAX}) and fails(v, {**base, s0: "t" * (STRING_MAX + 1)})
    for name in pack.list_fields:
        most, chars = LIST_LIMITS[name]
        assert not fails(v, {**base, name: ["t" * chars] * most})
        assert fails(v, {**base, name: ["t" * (chars + 1)]})
        assert fails(v, {**base, name: ["t"] * (most + 1)})


def test_the_prompt_states_the_same_limits_as_the_schema():
    for n in (STRING_MAX, QUOTE_MAX, INJECTION_MAX, LIST_LIMITS["key_fields"][0], LIST_LIMITS["triage_tips"][0],
              LIST_LIMITS["triage_tips"][1], LIST_LIMITS["key_fields"][1], LIST_LIMITS["checks"][1]):
        assert str(n) in SYSTEM, n
