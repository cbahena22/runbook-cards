from __future__ import annotations

import hashlib
import json
import shutil

import pytest

import make_techniques as mt

from runbook_cards import cli
from runbook_cards.paths import ROOT, rel
from runbook_cards.techniques import load_techniques

FIX = ROOT / "tests" / "fixtures"


def test_techniques_file_covers_every_tag_used_by_the_rules():
    used = mt.used_ids(ROOT)
    names = load_techniques()
    assert len(used) == 24 and set(used) == set(names)
    assert all(n.strip() for n in names.values())


def bundle(tmp_path):
    objs = [
        {"type": "attack-pattern", "name": "PowerShell", "external_references": [{"source_name": "mitre-attack", "external_id": "T1059.001"}]},
        {"type": "attack-pattern", "name": "Old", "x_mitre_deprecated": True, "external_references": [{"source_name": "mitre-attack", "external_id": "T1105"}]},
    ]
    p = tmp_path / "b.json"
    p.write_bytes(json.dumps({"type": "bundle", "objects": objs}).encode())
    return p, hashlib.sha256(p.read_bytes()).hexdigest()


def tiny_root(tmp_path, tags):
    r = tmp_path / "root/packs/p/sources/rules"
    r.mkdir(parents=True)
    (r / "a.yml").write_text("title: a\ntags: " + json.dumps(tags) + "\n", encoding="utf-8")
    return tmp_path / "root"


def test_make_techniques_with_fixture_bundle(tmp_path):
    b, sha = bundle(tmp_path)
    root = tiny_root(tmp_path, ["attack.t1059.001", "attack.execution"])
    out = tmp_path / "t.json"
    assert mt.main(["--bundle", str(b), "--root", str(root), "--out", str(out)], version="1.0", sha256=sha) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["techniques"] == {"T1059.001": "PowerShell"}
    assert doc["source"]["sha256"] == sha and doc["source"]["pinned"] is True


def test_make_techniques_refuses_sha_mismatch_and_missing_ids(tmp_path):
    b, sha = bundle(tmp_path)
    root = tiny_root(tmp_path, ["attack.t1059.001"])
    out = tmp_path / "t.json"
    assert mt.main(["--bundle", str(b), "--root", str(root), "--out", str(out)], version="1", sha256="0" * 64) == 2
    assert not out.exists()
    root2 = tiny_root(tmp_path / "x", ["attack.t1105"])  # deprecated in the bundle -> missing
    assert mt.main(["--bundle", str(b), "--root", str(root2), "--out", str(out)], version="1", sha256=sha) == 1


def test_make_techniques_defaults_to_the_pinned_constants(tmp_path):
    import re

    assert re.fullmatch(r"[0-9a-f]{64}", mt.ATTACK_SHA256)
    assert mt.ATTACK_URL.startswith("https://raw.githubusercontent.com/mitre-attack/attack-stix-data/")
    assert mt.ATTACK_VERSION in mt.ATTACK_URL
    b, _ = bundle(tmp_path)
    root = tiny_root(tmp_path, ["attack.t1059.001"])
    out = tmp_path / "t.json"
    # the fixture bundle is not the pinned file, so the pinned default refuses it; there is no --sha256 flag to override
    assert mt.main(["--bundle", str(b), "--root", str(root), "--out", str(out)]) == 2
    assert not out.exists()
    with pytest.raises(SystemExit):
        mt.main(["--bundle", str(b), "--sha256", "0" * 64, "--root", str(root)])


def test_committed_techniques_file_is_pinned_to_the_constants():
    doc = json.loads((ROOT / "attack" / "techniques.json").read_text(encoding="utf-8"))
    assert doc["source"]["pinned"] is True
    assert doc["source"]["version"] == mt.ATTACK_VERSION and doc["source"]["sha256"] == mt.ATTACK_SHA256


def test_build_makes_a_page_from_fixture_cards(tmp_path, capsys):
    out = tmp_path / "s.html"
    assert cli.main(["build", "--pack", "security", "--cards", "tests/fixtures/cards/security", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
    printed = capsys.readouterr().out
    assert "3 cards" in printed and str(tmp_path) not in printed and str(ROOT) not in printed


def test_check_exit_0_on_valid_and_1_on_broken(tmp_path, capsys):
    good = ROOT / "tests/fixtures/cards/security"
    assert cli.main(["check", "--pack", "security", "--cards", str(good)]) == 0
    d = tmp_path / "cards"
    shutil.copytree(good, d)
    card = json.loads((d / "chm-win-001.json").read_text(encoding="utf-8"))
    card["citations"]["what_it_is"][0]["quote"] = "invented text"
    (d / "chm-win-001.json").write_text(json.dumps(card), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["check", "--pack", "security", "--cards", str(d)]) == 1
    out = capsys.readouterr().out
    assert "QUOTE_MISSING" in out and str(tmp_path) not in out


def test_check_flags_unknown_unit_and_unreadable_card(tmp_path, capsys):
    d = tmp_path / "c"
    d.mkdir()
    (d / "x.json").write_text(json.dumps({"card_id": "nope"}), encoding="utf-8")
    assert cli.main(["check", "--pack", "security", "--cards", str(d)]) == 1
    (d / "y.json").write_text("{not json", encoding="utf-8")
    assert cli.main(["check", "--pack", "security", "--cards", str(d)]) == 2


def test_build_with_no_cards_and_demo_without_committed_cards(tmp_path, capsys):
    d = tmp_path / "empty"
    d.mkdir()
    assert cli.main(["build", "--pack", "helpdesk", "--cards", str(d)]) == 1
    if not any((ROOT / "cards" / p).glob("*.json") for p in ("security", "helpdesk")):
        assert cli.main(["demo"]) == 1


def test_rel_never_prints_absolute(tmp_path):
    assert rel(ROOT / "cards" / "a.json") == "cards/a.json"
    assert rel(tmp_path / "x.json") == "<outside>/x.json"
