from __future__ import annotations

import pytest
import yaml

from runbook_cards.convert import ConvResult, convert
from runbook_cards.packs.base import detection_fields
from runbook_cards.paths import PACKS_DIR, ROOT

GOLD = ROOT / "tests" / "fixtures" / "golden"


def rule(name):
    return yaml.safe_load((PACKS_DIR / f"security/sources/rules/{name}.yml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["chm-win-001", "chm-win-006", "chm-win-013"])
@pytest.mark.parametrize("backend", ["esql", "kql"])
def test_golden_queries(name, backend):
    r = rule(name)
    res = convert(r, backend, detection_fields(r))
    assert res.error is None
    assert res.query + "\n" == (GOLD / f"{name}.{backend}.txt").read_text(encoding="utf-8")


def test_field_map_comes_from_the_pipeline():
    r = rule("chm-win-001")
    assert convert(r, "esql", ["Image", "CommandLine"]).field_map == {
        "Image": "process.executable.caseless", "CommandLine": "process.command_line"}
    assert convert(r, "kql", ["Image", "CommandLine"]).field_map == {
        "Image": "FolderPath", "CommandLine": "ProcessCommandLine"}


def test_unsupported_modifier_is_a_recorded_failure_not_an_exception():
    r = {"title": "t", "logsource": {"category": "process_creation", "product": "windows"},
         "detection": {"sel": {"Image|fieldref": "CommandLine"}, "condition": "sel"}}
    res = convert(r, "kql", ["Image"])
    assert isinstance(res, ConvResult) and res.query is None
    assert "not supported" in res.error


def test_linux_rule_is_a_recorded_failure_for_both_backends():
    r = rule("chm-lin-027")
    e = convert(r, "esql", ["program"])
    assert e.query is None and "no ECS pipeline" in e.error
    k = convert(r, "kql", ["program"])
    assert k.query is None and "table name" in k.error and "\n" not in k.error


def test_every_rule_returns_a_result_and_counts_are_pinned(security):
    ok = {"esql": 0, "kql": 0}
    for u in security[1]:
        r = rule(u.unit_id)
        for b in ok:
            res = convert(r, b, detection_fields(r))
            assert (res.query is None) != (res.error is None)
            ok[b] += res.query is not None
    assert ok == {"esql": 27, "kql": 22}


def test_unknown_backend_rejected():
    with pytest.raises(ValueError):
        convert(rule("chm-win-001"), "spl")
