"""Budget, request-hash store, gateway, live clients (with a fake SDK), replay."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from runbook_cards.budget import Budget, BudgetError, estimate_tokens
from runbook_cards.cli import main
from runbook_cards.config import load_config
from runbook_cards.draft import draft_request
from runbook_cards.llm import (SDK_MAX_RETRIES, Gateway, LiveBatch, LiveSync, LlmError, NotRecorded, Replay, Reply, Request, Store,
                               request_hash)
from runbook_cards.paths import ROOT
from tests.fakes import FakeModel

CFG = load_config()
STORE_FX = ROOT / "tests" / "fixtures" / "store" / "fx-1"


def requests_for(security, n):
    pack, units = security
    return [draft_request(pack, u, CFG) for u in units[:n]], {u.unit_id: u for u in units}


def budget(limit):
    return Budget(limit, CFG.price_in, CFG.price_out)


def test_live_run_needs_a_budget(security, tmp_path):
    _, units = security
    with pytest.raises(LlmError):
        Gateway(FakeModel({}), Store(tmp_path / "s"), CFG, None)
    assert main(["eval", "--live", "--record", str(tmp_path / "r")]) == 2  # no --budget
    assert main(["eval", "--live", "--budget", "1"]) == 2  # no --record
    with pytest.raises(BudgetError):
        budget(0)
    with pytest.raises(BudgetError):
        budget(float("nan"))


def test_bound_over_budget_sends_nothing(security, tmp_path):
    reqs, units = requests_for(security, 5)
    fake = FakeModel(units)
    gw = Gateway(fake, Store(tmp_path / "s"), CFG, budget(0.01))
    res = gw.run(reqs)
    assert fake.calls == []
    assert [r.reply.error for r in res] == ["budget"] * 5


def test_mid_run_stop_marks_the_rest(security, tmp_path):
    reqs, units = requests_for(security, 12)
    fake = FakeModel(units)
    # one draft request: single-attempt bound 3000 in + max_tokens out, x3 with SDK retries; real cost $0.010; groups of 4,
    # so a limit of one group bound + $0.06 lets exactly two groups through (spent $0.04 + bound fits, $0.08 + bound does not)
    limit = 4 * (1 + SDK_MAX_RETRIES) * (3000 * 2 + CFG.draft_max_tokens * 10) / 1e6 + 0.06
    gw = Gateway(fake, Store(tmp_path / "s"), CFG, budget(limit))
    res = gw.run(reqs)
    assert len(fake.calls) == 8
    assert [r.reply.error for r in res] == [None] * 8 + ["budget"] * 4
    assert gw.budget.spent <= limit


def test_budget_bound_covers_sdk_retries(security, tmp_path):
    reqs, units = requests_for(security, 1)
    single = budget(5).bound(reqs[0].body, 3000)  # one attempt: 3000 in + max_tokens out
    assert single == pytest.approx((3000 * 2 + CFG.draft_max_tokens * 10) / 1e6)
    limit = single * 1.5  # one attempt fits, 1 + SDK_MAX_RETRIES attempts do not
    assert budget(limit).allows(single) and not budget(limit).allows(single * (1 + SDK_MAX_RETRIES))
    fake = FakeModel(units)
    res = Gateway(fake, Store(tmp_path / "s"), CFG, budget(limit)).run(reqs)
    assert fake.calls == [] and [r.reply.error for r in res] == ["budget"]
    fake2 = FakeModel(units)  # the same call is sent once the budget covers every attempt
    res2 = Gateway(fake2, Store(tmp_path / "t"), CFG, budget(single * (1 + SDK_MAX_RETRIES) + 0.001)).run(reqs)
    assert len(fake2.calls) == 1 and res2[0].reply.error is None


def test_spend_is_summed_from_returned_usage(security, tmp_path):
    reqs, units = requests_for(security, 4)
    gw = Gateway(FakeModel(units), Store(tmp_path / "s"), CFG, budget(5))
    gw.run(reqs)
    assert gw.budget.spent == pytest.approx(4 * (3000 * 2 + 400 * 10) / 1e6)
    usage = json.loads((tmp_path / "s" / "usage.json").read_text(encoding="utf-8"))
    assert usage["input_tokens"] == 12000 and usage["requests"] == 4


def test_estimate_is_used_when_the_provider_cannot_count(security):
    reqs, _ = requests_for(security, 1)
    b = budget(5)
    assert b.bound(reqs[0].body, None) > b.bound(reqs[0].body, 1000)
    assert estimate_tokens(reqs[0].body) > len(json.dumps(reqs[0].body)) / 3


def test_cache_hit_sends_nothing_and_resumes_spend(security, tmp_path):
    reqs, units = requests_for(security, 4)
    fake = FakeModel(units)
    Gateway(fake, Store(tmp_path / "s"), CFG, budget(5)).run(reqs)
    assert len(fake.calls) == 4
    store = Store(tmp_path / "s")
    gw = Gateway(fake, store, CFG, Budget(5, CFG.price_in, CFG.price_out, spent=store.total_cost(CFG)))
    res = gw.run(reqs)
    assert len(fake.calls) == 4 and all(r.cached for r in res)
    assert gw.budget.spent == pytest.approx(0.04)


def test_replay_hit_and_miss(security, tmp_path):
    reqs, units = requests_for(security, 3)
    Gateway(FakeModel(units), Store(tmp_path / "s"), CFG, budget(5)).run(reqs)
    gw = Gateway(Replay(), Store(tmp_path / "s", readonly=True), CFG)
    assert [r.reply.tool_input is not None for r in gw.run(reqs)] == [True] * 3
    other = Request(reqs[0].unit_id, "draft", {**reqs[0].body, "max_tokens": 7})
    with pytest.raises(NotRecorded, match="not recorded"):
        gw.run([other])
    with pytest.raises(LlmError):
        Store(tmp_path / "nope", readonly=True)


def test_replay_store_is_never_written(security, tmp_path):
    reqs, units = requests_for(security, 2)
    Gateway(FakeModel(units), Store(tmp_path / "s"), CFG, budget(5)).run(reqs)
    before = {p.name: p.read_bytes() for p in (tmp_path / "s").iterdir()}
    Gateway(Replay(), Store(tmp_path / "s", readonly=True), CFG).run(reqs)
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "s").iterdir()}


def test_failures_are_retried_live_and_replayed_as_recorded(security, tmp_path):
    reqs, units = requests_for(security, 1)
    Gateway(FakeModel(units), Store(tmp_path / "s"), CFG, budget(0.0001)).run(reqs)  # budget stop is recorded
    assert Gateway(Replay(), Store(tmp_path / "s", readonly=True), CFG).run(reqs)[0].reply.error == "budget"
    fake = FakeModel(units)
    res = Gateway(fake, Store(tmp_path / "s"), CFG, budget(5)).run(reqs)  # a bigger budget retries it
    assert len(fake.calls) == 1 and res[0].reply.error is None


def test_hash_covers_model_prompt_schema_and_body():
    b = {"model": "m", "max_tokens": 5}
    h = request_hash(b, "p1", "1")
    assert h == request_hash(dict(reversed(list(b.items()))), "p1", "1")
    assert len({h, request_hash(b, "p2", "1"), request_hash(b, "p1", "2"), request_hash({**b, "model": "n"}, "p1", "1")}) == 4


def test_store_keeps_no_headers_or_keys(security, tmp_path, monkeypatch):
    secret = "sk-" + "ant-" + "x" * 30
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    reqs, units = requests_for(security, 2)
    Gateway(FakeModel(units), Store(tmp_path / "s"), CFG, budget(5)).run(reqs)
    for f in (tmp_path / "s").iterdir():
        assert secret not in f.read_text(encoding="utf-8")
    keys = set()
    for line in (tmp_path / "s" / "requests.jsonl").read_text(encoding="utf-8").splitlines():
        keys |= set(json.loads(line))
    assert keys == {"hash", "unit_id", "phase", "model", "max_tokens"}


def test_torn_store_line_is_refused(tmp_path):
    (tmp_path / "responses.jsonl").write_text('{"hash": "a"}\n{"hash": \n', encoding="utf-8")
    with pytest.raises(LlmError, match="responses.jsonl:2"):
        Store(tmp_path)


KEY_SHAPES = re.compile("|".join(["sk-" + "ant-", "AK" + "IA[0-9A-Z]{8}", "-----BEGIN " + "[A-Z ]*PRIVATE"]))


def test_no_key_shapes_in_recorded_stores():
    for base in (ROOT / "evals" / "recorded", ROOT / "tests" / "fixtures" / "store"):
        if base.is_dir():
            for f in base.rglob("*"):
                if f.is_file():
                    assert not KEY_SHAPES.search(f.read_text(encoding="utf-8")), f.name


# ---- live clients with a fake SDK ----

def msg(tool_input=None, stop="tool_use", tokens=(10, 5)):
    block = NS(type="tool_use", input=tool_input) if tool_input is not None else NS(type="text", text="no")
    return NS(content=[block], stop_reason=stop, usage=NS(input_tokens=tokens[0], output_tokens=tokens[1]))


class FakeSdk:
    def __init__(self, create=None):
        self.create_fn = create or (lambda **kw: msg({"ok": True}))
        self.messages = NS(create=lambda **kw: self.create_fn(**kw), count_tokens=self.count, batches=NS())
        self.seen = []

    def count(self, **kw):
        return NS(input_tokens=1234)


def req(i="u1"):
    return Request(i, "draft", {"model": "m", "max_tokens": 10, "system": "s", "messages": [], "tools": [], "tool_choice": {}})


def test_live_sync_extracts_the_tool_input_and_usage():
    c = LiveSync(CFG, sdk=FakeSdk())
    r = c.submit([req("a"), req("b")])
    assert [x.tool_input for x in r] == [{"ok": True}] * 2 and r[0].usage == {"input_tokens": 10, "output_tokens": 5}
    assert c.count_tokens(req().body) == 1234 and c.group_size == CFG.concurrency


def test_live_sync_truncated_or_missing_tool_is_an_error_not_a_card():
    assert LiveSync(CFG, sdk=FakeSdk(lambda **kw: msg({"x": 1}, stop="max_tokens"))).submit([req()])[0].error == "error"
    assert LiveSync(CFG, sdk=FakeSdk(lambda **kw: msg(None))).submit([req()])[0].error == "error"


def test_max_tokens_keeps_the_stop_reason_and_a_bounded_snippet_in_the_store(tmp_path):
    big = {"what_it_is": "A" * 900, "citations": {"what_it_is": [{"quote": "z" * 900}]}}
    r = LiveSync(CFG, sdk=FakeSdk(lambda **kw: msg(big, stop="max_tokens", tokens=(10, 10)))).submit([req()])[0]
    assert (r.error, r.tool_input, r.stop_reason) == ("error", None, "max_tokens")
    assert r.partial.startswith('{"what_it_is":"AAA') and r.partial.endswith('zzz"}]}}')  # first + last 400 chars
    assert "chars omitted" in r.partial and len(r.partial) < 900
    st = Store(tmp_path / "s")
    st.put(req(), "h1", r)
    rec = json.loads((tmp_path / "s" / "responses.jsonl").read_text(encoding="utf-8"))
    assert rec["stop_reason"] == "max_tokens" and rec["partial"] == r.partial and rec["tool_input"] is None
    back = Gateway(Replay(), Store(tmp_path / "s", readonly=True), CFG)  # the snippet survives a reload
    assert Store(tmp_path / "s", readonly=True).get("h1")["partial"] == r.partial
    assert back.client.live is False


def test_a_short_partial_is_kept_whole_and_a_good_reply_carries_no_extra_keys(tmp_path):
    r = LiveSync(CFG, sdk=FakeSdk(lambda **kw: msg({"a": 1}, stop="max_tokens"))).submit([req()])[0]
    assert r.partial == '{"a":1}'
    ok = LiveSync(CFG, sdk=FakeSdk()).submit([req()])[0]
    assert ok.stop_reason is None and ok.partial is None
    st = Store(tmp_path / "s")
    st.put(req(), "h2", ok)
    assert set(json.loads((tmp_path / "s" / "responses.jsonl").read_text(encoding="utf-8"))) == {
        "hash", "unit_id", "phase", "tool_input", "usage", "error"}


def test_a_hidden_character_in_a_partial_is_written_as_a_visible_escape(tmp_path):
    zwj, rlo = chr(0x200D), chr(0x202E)
    r = LiveSync(CFG, sdk=FakeSdk(lambda **kw: msg({"a": f"x{zwj}y{rlo}z"}, stop="max_tokens"))).submit([req()])[0]
    Store(tmp_path / "s").put(req(), "h3", r)
    raw = (tmp_path / "s" / "responses.jsonl").read_text(encoding="utf-8")
    assert r"\\u200d" in raw and r"\\u202e" in raw and all(ord(c) < 128 for c in raw)  # visible escapes, no raw control


def test_spend_keeps_every_record_of_a_retried_hash(tmp_path):
    st = Store(tmp_path / "s")
    r = req()
    st.put(r, "h", Reply(None, {"input_tokens": 100, "output_tokens": 50}, "error"))
    st.put(r, "h", Reply({"ok": 1}, {"input_tokens": 100, "output_tokens": 60}, None))  # the live retry of a recorded failure
    assert st.get("h")["tool_input"] == {"ok": 1}  # lookups see the last record
    assert st.total_usage() == {"input_tokens": 200, "output_tokens": 110}  # the spend counts both
    st.save_usage(CFG)
    again = Store(tmp_path / "s")
    assert again.total_usage() == {"input_tokens": 200, "output_tokens": 110}  # and so does a reloaded store
    assert json.loads((tmp_path / "s" / "usage.json").read_text(encoding="utf-8"))["requests"] == 2


def test_live_sync_maps_exceptions():
    class APITimeoutError(Exception): ...
    class AuthenticationError(Exception): ...
    class Boom(Exception): ...

    def make(exc):
        def f(**kw):
            raise exc("secret-looking detail must not travel")
        return f
    assert LiveSync(CFG, sdk=FakeSdk(make(APITimeoutError))).submit([req()])[0].error == "timeout"
    assert LiveSync(CFG, sdk=FakeSdk(make(Boom))).submit([req()])[0].error == "error"
    with pytest.raises(LlmError) as ei:
        LiveSync(CFG, sdk=FakeSdk(make(AuthenticationError))).submit([req()])
    assert "secret-looking" not in str(ei.value)


def test_count_tokens_failure_falls_back_to_none():
    sdk = FakeSdk()
    sdk.messages.count_tokens = lambda **kw: (_ for _ in ()).throw(RuntimeError("x"))
    assert LiveSync(CFG, sdk=sdk).count_tokens(req().body) is None


def test_live_client_needs_the_key_in_the_environment(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LlmError, match="ANTHROPIC_API_KEY"):
        LiveSync(CFG)
    with pytest.raises(LlmError, match="ANTHROPIC_API_KEY"):
        LiveBatch(CFG)


class Batches:
    def __init__(self, statuses, results=()):
        self.statuses, self.results_list, self.cancelled, self.created = list(statuses), list(results), [], []

    def create(self, requests):
        self.created.append(requests)
        return NS(id="b1", processing_status="in_progress")

    def retrieve(self, bid):
        return NS(id=bid, processing_status=self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])

    def cancel(self, bid):
        self.cancelled.append(bid)

    def results(self, bid):
        return iter(self.results_list)


def batch_client(batches):
    sdk = FakeSdk()
    sdk.messages.batches = batches
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += 3600  # one poll = one hour

    return LiveBatch(CFG, sdk=sdk, sleep=sleep, clock=lambda: now[0]), slept


def test_batch_times_out_cancels_and_marks_timeout():
    b = Batches(["in_progress"])
    client, _ = batch_client(b)
    replies = client.submit([req("a"), req("b")])
    assert b.cancelled == ["b1"] and [r.error for r in replies] == ["timeout", "timeout"]


def test_batch_collects_results_by_custom_id():
    entries = [NS(custom_id="r1", result=NS(type="errored")), NS(custom_id="r0", result=NS(type="succeeded", message=msg({"v": 1}))),
               ]
    client, slept = batch_client(Batches(["ended"], entries))
    out = client.submit([req("a"), req("b"), req("c")])
    assert out[0].tool_input == {"v": 1} and out[1].error == "error" and out[2].error == "error"  # r2 never came back
    assert slept  # it polled with the injected sleep, not the real one


def test_batch_through_the_gateway_marks_units_timeout(security, tmp_path):
    reqs, _ = requests_for(security, 3)
    client, _ = batch_client(Batches(["in_progress"]))
    res = Gateway(client, Store(tmp_path / "s"), CFG, budget(5)).run(reqs)
    assert [r.reply.error for r in res] == ["timeout"] * 3


def test_batch_is_one_submit_with_the_budget_checked_for_all(security, tmp_path):
    reqs, _ = requests_for(security, 6)
    b = Batches(["ended"], [])
    client, _ = batch_client(b)
    Gateway(client, Store(tmp_path / "s"), CFG, budget(5)).run(reqs)
    assert len(b.created) == 1 and len(b.created[0]) == 6
    b2 = Batches(["ended"], [])
    client2, _ = batch_client(b2)
    res = Gateway(client2, Store(tmp_path / "t"), CFG, budget(0.1)).run(reqs)  # 6 x $0.054 > $0.1
    assert b2.created == [] and {r.reply.error for r in res} == {"budget"}


def test_replay_eval_never_imports_the_sdk(tmp_path):
    code = ("import sys\nfrom runbook_cards.cli import main\n"
            "rc = main(['eval','--replay',sys.argv[1],'--cards',sys.argv[2],'--results',sys.argv[3]])\n"
            "print('rc', rc, 'anthropic' in sys.modules)\n")
    env = {**os.environ}
    env.pop("ANTHROPIC_API_KEY", None)
    out = subprocess.run([sys.executable, "-c", code, str(STORE_FX), str(tmp_path / "c"), str(tmp_path / "r")],
                         capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert out.stdout.strip().endswith("rc 0 False"), out.stdout[-300:] + out.stderr[-300:]


def test_errors_without_usage_are_charged_at_the_bound(security, tmp_path):
    reqs, units = requests_for(security, 2)

    class Timeouts(FakeModel):
        def submit(self, requests):
            return [Reply(None, error="timeout") for _ in requests]
    gw = Gateway(Timeouts(units), Store(tmp_path / "s"), CFG, budget(5))
    gw.run(reqs)
    assert gw.budget.spent == pytest.approx(2 * 3 * (3000 * 2 + CFG.draft_max_tokens * 10) / 1e6)  # count 3000 + max_tokens, never $0; x3 = 1 + SDK_MAX_RETRIES


def test_batch_sdk_errors_do_not_echo_provider_text():
    class Boom(Exception): ...
    b = Batches(["ended"])
    b.create = lambda requests: (_ for _ in ()).throw(Boom("response body with details"))
    client, _ = batch_client(b)
    with pytest.raises(LlmError) as ei:
        client.submit([req()])
    assert "details" not in str(ei.value) and "Boom" in str(ei.value)
