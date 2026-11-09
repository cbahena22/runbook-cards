"""`eval --only UNIT_ID` / `--limit N`: a small probe run that never touches the committed cards or the spot-check sheet."""
from __future__ import annotations

import json

import pytest

from runbook_cards.budget import Budget
from runbook_cards.cli import main
from runbook_cards.config import load_config
from runbook_cards.evals import EvalError, run_eval, select_units
from runbook_cards.llm import Gateway, Store
from runbook_cards.packs import get_pack
from runbook_cards.paths import ROOT
from tests.fakes import FakeModel
from tests.make_fixture_store import units_by_id

CFG = load_config()
FX = ROOT / "tests" / "fixtures" / "store" / "fx-1"
SEC, HELP = "chm-win-001", "sop-01-password-reset"


def replay(tmp_path, *extra):
    return main(["eval", "--replay", str(FX), "--cards", str(tmp_path / "c"), "--results", str(tmp_path / "r"), *extra])


def test_only_drafts_just_those_units_and_marks_the_results_as_a_probe(tmp_path, capsys):
    assert replay(tmp_path, "--only", SEC, "--only", HELP) == 0
    assert [p.stem for p in (tmp_path / "c" / "security").glob("*.json")] == [SEC]
    assert [p.stem for p in (tmp_path / "c" / "helpdesk").glob("*.json")] == [HELP]
    res = json.loads((tmp_path / "r" / "fx-1.json").read_text(encoding="utf-8"))
    assert res["probe"] == {"units": 2} and res["security"]["n"] == 1 and res["helpdesk"]["n"] == 1
    assert "PROBE: 2 unit(s) only" in (tmp_path / "r" / "fx-1.md").read_text(encoding="utf-8")
    assert not (tmp_path / "r" / "spot_check.csv").exists()  # a probe never writes the spot-check sheet
    assert "PROBE" in capsys.readouterr().out


def test_limit_takes_units_in_pack_order(tmp_path):
    assert replay(tmp_path, "--limit", "1") == 0
    assert len(list((tmp_path / "c" / "security").glob("*.json"))) == 1
    assert list((tmp_path / "c" / "helpdesk").glob("*.json")) == []


def test_a_probe_scores_only_the_redteam_items_it_drafted(tmp_path):
    assert replay(tmp_path, "--only", SEC) == 0
    res = json.loads((tmp_path / "r" / "fx-1.json").read_text(encoding="utf-8"))
    assert res["redteam"]["n"] == 6  # the key's item count stays; the detail lists only drafted units
    assert 0 < len(res["redteam"]["items"]) < 6


def test_a_probe_without_cards_dir_is_refused_so_committed_cards_are_safe(tmp_path, capsys):
    assert main(["eval", "--replay", str(FX), "--results", str(tmp_path / "r"), "--only", SEC]) == 2
    assert "--cards" in capsys.readouterr().err


def test_an_unknown_unit_or_a_zero_limit_is_refused(tmp_path, capsys):
    assert replay(tmp_path, "--only", "no-such-unit") == 2
    assert "no such unit" in capsys.readouterr().err
    assert replay(tmp_path, "--limit", "0") == 2


def test_select_units_filters_then_limits():
    per = {n: get_pack(n).units(get_pack(n).load()) for n in ("security", "helpdesk")}
    both = select_units(per, [SEC, HELP], None)
    assert [u.unit_id for u in both["security"]] == [SEC] and [u.unit_id for u in both["helpdesk"]] == [HELP]
    capped = select_units(per, None, 2)
    assert sum(len(v) for v in capped.values()) == 2 and capped["helpdesk"] == []
    assert sum(len(v) for v in select_units(per, None, None).values()) == sum(len(v) for v in per.values())
    with pytest.raises(EvalError):
        select_units(per, ["nope"], None)


def test_a_live_probe_sends_only_the_chosen_units_and_stays_under_a_small_budget(tmp_path):
    fake = FakeModel(units_by_id())
    budget = Budget(0.5, CFG.price_in, CFG.price_out)
    gw = Gateway(fake, Store(tmp_path / "probe-1"), CFG, budget)
    res = run_eval(gw, CFG, "probe-1", tmp_path / "c", tmp_path / "r", tmp_path / "r" / "spot.csv", only=[SEC, HELP])
    assert {r.unit_id for r in fake.calls} == {SEC, HELP}
    assert res["probe"] == {"units": 2} and budget.spent < 0.5
    assert not (tmp_path / "r" / "spot.csv").exists()


def test_the_probe_command_end_to_end_with_a_stub_sdk(tmp_path, monkeypatch, capsys):
    """The exact CLI path of a probe run (--live --budget --record --cards --only --only) with the SDK replaced by a stub."""
    import re
    from types import SimpleNamespace as NS

    from tests.fakes import honest

    units = units_by_id()
    seen = []

    def create(**body):
        seen.append(body["max_tokens"])
        if body["tools"][0]["name"] == "report_unsupported":
            data = {"unsupported": []}
        else:
            data = honest(units[re.match(r"Unit: (\S+) ", body["messages"][0]["content"]).group(1)])
        return NS(content=[NS(type="tool_use", input=data)], stop_reason="tool_use", usage=NS(input_tokens=1700, output_tokens=500))

    sdk = NS(messages=NS(create=create, count_tokens=lambda **kw: NS(input_tokens=1700)))
    monkeypatch.setattr("runbook_cards.llm._make_sdk", lambda: sdk)
    rec = tmp_path / "probe-1"
    rc = main(["eval", "--live", "--budget", "0.25", "--record", str(rec), "--cards", str(tmp_path / "c"),
               "--results", str(tmp_path / "r"), "--only", SEC, "--only", HELP])
    out = capsys.readouterr().out
    assert rc == 0 and "PROBE: 2 unit(s) only" in out
    assert sorted(seen) == [CFG.grounding_max_tokens] * 2 + [CFG.draft_max_tokens] * 2  # 2 drafts + 2 grounding checks, nothing else
    usage = json.loads((rec / "usage.json").read_text(encoding="utf-8"))
    assert usage["requests"] == 4 and usage["cost_usd"] < 0.25
