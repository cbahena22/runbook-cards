from __future__ import annotations

import re
from pathlib import Path

import pytest

from runbook_cards.packs import get_pack
from runbook_cards.packs.base import MAX_FILE_BYTES, MAX_FILES, MAX_LINE_CHARS, PackError, load_dir
from runbook_cards.paths import PACKS_DIR

RULE = (PACKS_DIR / "security/sources/rules/chm-win-001.yml").read_text(encoding="utf-8")


def mkpack(tmp_path: Path, rules: dict[str, str] | None = None, runbooks: dict[str, str] | None = None) -> Path:
    root = tmp_path / "pack"
    (root / "sources/rules").mkdir(parents=True)
    (root / "sources/runbooks").mkdir(parents=True)
    for name, text in (rules if rules is not None else {"chm-win-001": RULE}).items():
        (root / "sources/rules" / f"{name}.yml").write_text(text, encoding="utf-8", newline="\n")
    for name, text in (runbooks or {}).items():
        (root / "sources/runbooks" / f"{name}.md").write_text(text, encoding="utf-8", newline="\n")
    return root


def test_both_packs_load(security, helpdesk):
    assert len(security[1]) == 30 and len(helpdesk[1]) == 15
    docs = get_pack("security").load()
    assert sum(d.kind == "runbook" for d in docs) == 16 and sum(d.kind == "rule" for d in docs) == 30
    assert all(len(d.sha256) == 64 for d in docs)


def test_covers_mapping_is_deterministic_and_some_rules_have_no_runbook(security):
    units = security[1]
    first = [(u.unit_id, [d.doc_id for d in u.docs]) for u in units]
    again = get_pack("security")
    second = [(u.unit_id, [d.doc_id for d in u.docs]) for u in again.units(again.load())]
    assert first == second
    assert [u.unit_id for u in units] == sorted(u.unit_id for u in units)
    assert sorted(u.unit_id for u in units if len(u.docs) == 1) == ["chm-lin-029", "chm-win-025", "chm-win-030"]
    by = {u.unit_id: [d.doc_id for d in u.docs] for u in units}
    assert by["chm-win-001"] == ["chm-win-001", "rb-01-powershell-alerts", "rb-15-encoded-commands"]


def test_playbook_link_is_code_built(security):
    pack, units = security
    by = {u.unit_id: pack.deterministic_fields(u)["playbook_link"] for u in units}
    assert by["chm-win-001"] == "rb-01-powershell-alerts" and by["chm-win-025"] is None


def test_covers_unknown_rule_is_an_error(tmp_path):
    root = mkpack(tmp_path, runbooks={"rb-x": "# x\ncovers: no-such-rule\n"})
    pack = get_pack("security")
    with pytest.raises(PackError, match="unknown rule"):
        pack.units(pack.load(root))


def test_runbook_without_covers_is_an_error(tmp_path):
    root = mkpack(tmp_path, runbooks={"rb-x": "# x\nnothing here\n"})
    pack = get_pack("security")
    with pytest.raises(PackError, match="covers"):
        pack.units(pack.load(root))


def test_related_unknown_sop_is_an_error(tmp_path):
    d = tmp_path / "hd/sources/sops"
    d.mkdir(parents=True)
    (d / "sop-a.md").write_text("# SOP: a\nrelated: sop-zzz\n", encoding="utf-8")
    pack = get_pack("helpdesk")
    with pytest.raises(PackError, match="related"):
        pack.units(pack.load(tmp_path / "hd"))


def test_oversize_file_refused_by_size_before_parse(tmp_path):
    big = "a: " + "x" * (MAX_FILE_BYTES + 10) + "\n"
    root = mkpack(tmp_path, rules={"chm-win-001": big})
    with pytest.raises(PackError, match="larger than 64 KB"):
        load_dir(root, "sources/rules", "rule", ".yml")


def test_read_is_bounded_even_if_stat_lies(tmp_path, monkeypatch):
    """stat() says small but the file grew: the read is capped at MAX_FILE_BYTES + 1 and refused."""
    big = "title: a\n# " + "x" * (MAX_FILE_BYTES + 10) + "\n"
    root = mkpack(tmp_path, rules={"chm-win-001": big})
    real_stat = Path.stat

    class Small:
        st_size = 10
        st_mode = 0o100644

    def fake_stat(self, *a, **k):
        return Small() if self.name == "chm-win-001.yml" else real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(PackError, match="larger than 64 KB"):
        load_dir(root, "sources/rules", "rule", ".yml")


def test_yaml_anchor_bomb_refused(tmp_path):
    lines = ["a: &a [x, x, x, x, x, x, x, x, x]"]
    for i in range(1, 9):
        prev = chr(ord("a") + i - 1)
        lines.append(f"{chr(ord('a') + i)}: &{chr(ord('a') + i)} [" + ", ".join([f"*{prev}"] * 9) + "]")
    text = "\n".join(lines) + "\n"
    assert len(text) < MAX_FILE_BYTES
    root = mkpack(tmp_path, rules={"chm-win-001": text})
    with pytest.raises(PackError, match="anchors and aliases"):
        load_dir(root, "sources/rules", "rule", ".yml")


def test_long_line_refused_and_named(tmp_path):
    root = mkpack(tmp_path, runbooks={"rb-x": "ok\n" + "y" * (MAX_LINE_CHARS + 1) + "\n"})
    with pytest.raises(PackError, match=r"rb-x\.md:2: line longer"):
        load_dir(root, "sources/runbooks", "runbook", ".md")
    ok = mkpack(tmp_path / "b", runbooks={"rb-x": "y" * MAX_LINE_CHARS})
    assert load_dir(ok, "sources/runbooks", "runbook", ".md")


@pytest.mark.parametrize("cp", [0x202A, 0x202E, 0x2066, 0x2069])
def test_bidi_controls_refused_and_named(tmp_path, cp):
    root = mkpack(tmp_path, runbooks={"rb-x": "fine\nabc" + chr(cp) + "def\n"})
    with pytest.raises(PackError, match=rf"rb-x\.md:2: bidirectional control \[U\+{cp:04X}\]"):
        load_dir(root, "sources/runbooks", "runbook", ".md")


def test_zero_width_characters_become_visible(tmp_path):
    zw = chr(0x200D)
    root = mkpack(tmp_path, runbooks={"rb-x": f"i{zw}g\n"})
    doc = load_dir(root, "sources/runbooks", "runbook", ".md")[0]
    assert doc.lines == ["i[U+200D]g"]


def test_too_many_files_refused(tmp_path):
    root = mkpack(tmp_path)
    for i in range(MAX_FILES + 1):
        (root / "sources/runbooks" / f"r{i}.md").write_text("x", encoding="utf-8")
    with pytest.raises(PackError, match="more than 200 files"):
        load_dir(root, "sources/runbooks", "runbook", ".md")


def test_symlinked_file_refused(tmp_path):
    root = mkpack(tmp_path, runbooks={"rb-x": "x"})
    target = tmp_path / "outside.md"
    target.write_text("secret", encoding="utf-8")
    try:
        (root / "sources/runbooks/rb-link.md").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(PackError, match="symlinks are refused"):
        load_dir(root, "sources/runbooks", "runbook", ".md")


def test_symlinked_directory_and_dotdot_refused(tmp_path):
    root = mkpack(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "a.md").write_text("x", encoding="utf-8")
    with pytest.raises(PackError, match="escapes"):
        load_dir(root, "../elsewhere", "runbook", ".md")
    try:
        (root / "sources/linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    with pytest.raises(PackError, match="escapes the pack root or is a symlink"):
        load_dir(root, "sources/linked", "runbook", ".md")


def test_non_utf8_refused(tmp_path):
    root = mkpack(tmp_path)
    (root / "sources/runbooks/bad.md").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(PackError, match="UTF-8"):
        load_dir(root, "sources/runbooks", "runbook", ".md")


@pytest.mark.parametrize("edit", [
    lambda t: t.replace("title:", "ttl:", 1),
    lambda t: t.replace("level: medium", "level: spicy"),
    lambda t: t.replace("name: chm-win-001", "name: Not A Valid Name"),
    lambda t: t.replace("name: chm-win-001", "name: chm-win-999"),
    lambda t: "- just\n- a list\n",
])
def test_rule_shape_checked(tmp_path, edit):
    root = mkpack(tmp_path, rules={"chm-win-001": edit(RULE)})
    with pytest.raises(PackError):
        get_pack("security").load(root)


def test_committed_sources_have_no_real_urls():
    host = re.compile(r"https?://([A-Za-z0-9.-]+)")
    for name in ("security", "helpdesk"):
        for d in get_pack(name).load():
            for ln in d.lines:
                for h in host.findall(ln):
                    assert h == "evil.example" and d.kind != "sop", (d.doc_id, h)
            if d.kind == "sop":
                assert not any("://" in ln for ln in d.lines), d.doc_id


def test_deeply_nested_yaml_refused(tmp_path):
    text = "a: " + "[" * 30 + "]" * 30 + "\n"
    root = mkpack(tmp_path, rules={"chm-win-001": text})
    with pytest.raises(PackError, match="nested deeper"):
        load_dir(root, "sources/rules", "rule", ".yml")


def test_every_format_character_is_refused_or_made_visible():
    from runbook_cards.packs.base import PackError, _check_text
    for cp in (0x200E, 0x200F, 0x061C):
        with pytest.raises(PackError):
            _check_text("x", "a" + chr(cp) + "b")
    out = _check_text("x", "a" + chr(0x00AD) + chr(0xE0041) + "b")[0]
    assert out == "a[U+00AD][U+E0041]b"


def test_only_newline_splits_lines_so_citation_numbers_match_the_raw_file():
    from runbook_cards.packs.base import _check_text
    seps = (0x2028, 0x2029, 0x0B, 0x0C, 0x85, 0x1C, 0x0D)
    text = "first\r\nsecond" + "".join(chr(c) for c in seps) + "tail\nthird\n"
    out = _check_text("x", text)
    assert len(out) == 3 and out[0] == "first" and out[2] == "third"
    assert out[1] == "second" + "".join(f"[U+{c:04X}]" for c in seps) + "tail"
    assert _check_text("x", "") == [] and _check_text("x", "a\n\nb") == ["a", "", "b"]


def test_variation_selectors_private_use_and_unassigned_are_made_visible():
    from runbook_cards.packs.base import _check_text
    cps = (0x034F, 0xFE00, 0xFE0F, 0xE0100, 0xE01EF, 0xE000, 0xF0000, 0x0378)  # CGJ, VS1/16, VS17/256, Co, Co (plane 15), Cn
    for cp in cps:
        assert _check_text("x", "a" + chr(cp) + "b") == [f"a[U+{cp:04X}]b"], hex(cp)
    assert _check_text("x", "caf\u00e9 \u2014 \u00fc \U0001f600") == ["caf\u00e9 \u2014 \u00fc \U0001f600"]
