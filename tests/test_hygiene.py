"""Publish hygiene: secrets, paths, e-mails, URLs, imports. Scans the files git knows about in this folder (never .venv)."""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LOCAL_PATHS = re.compile("|".join([r"/home/\w", r"/Users/\w", r"/root/", r"[A-Za-z]:\\Users\\", r"/tmp/claude"]))
SECRET_SHAPES = re.compile("|".join([
    "sk-" + "ant-", "AK" + "IA[0-9A-Z]{8}", "-----BEGIN " + r"[A-Z ]*PRIVATE", r"\b(?:api[_-]?key|password|secret|token)\s*[=:]\s*[\"']?[A-Za-z0-9/+_-]{12,}",
    "gh" + r"p_[A-Za-z0-9]{20}", "xox" + r"[bp]-",
]), re.IGNORECASE)
URL = re.compile(r"https?://([A-Za-z0-9.-]+)", re.IGNORECASE)
ALLOWED_HOST = re.compile(r"^(?:attack\.mitre\.org|(?:[a-z0-9-]+\.)*example(?:\.(?:com|org|net))?|[a-z0-9.-]+\.(?:test|invalid))$")
URL_FREE_DIRS = ("src/", "packs/", "cards/", "site/", "evals/")
ALLOWED_IMPORTS = {"runbook_cards", "tests", "make_techniques", "yaml", "jinja2", "jsonschema", "markupsafe", "sigma",
                   "pytest", "setuptools", "anthropic"}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "."],
                             cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    return [ROOT / n for n in out.decode("utf-8").split("\0") if n and (ROOT / n).is_file()]


def read_text(p: Path) -> str | None:
    try:
        return p.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return None


def bad_imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for n in names:
            top = n.split(".")[0]
            if top not in sys.stdlib_module_names and top not in ALLOWED_IMPORTS:
                found.add(top)
            if top in {"agent", "tools"}:
                found.add(top)
    return found


def bad_urls(text: str) -> list[str]:
    return [m.group(1) for m in URL.finditer(text) if not ALLOWED_HOST.match(m.group(1).lower())]


def test_scanners_work():
    assert bad_imports("import agent.x\nimport os\nfrom tools import y") == {"agent", "tools"}
    assert bad_imports("import requests") == {"requests"}
    assert bad_urls("see http://evil.example/x and https://attack.mitre.org/t/ and https://other.org/") == ["other.org"]
    assert SECRET_SHAPES.search("api_key = " + "abcdefghijklmnop")


def test_only_stdlib_and_locked_imports():
    bad = {}
    for p in tracked_files():
        if p.suffix == ".py":
            found = bad_imports(p.read_text(encoding="utf-8"))
            if found:
                bad[p.name] = sorted(found)
    assert not bad, bad


def test_urls_only_reserved_or_attack_in_data_dirs():
    bad = {}
    for p in tracked_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(URL_FREE_DIRS):
            text = read_text(p)
            hosts = bad_urls(text) if text else []
            if hosts:
                bad[rel] = hosts
    assert not bad, bad


def test_no_local_paths_or_secret_shapes():
    bad = {}
    for p in tracked_files():
        text = read_text(p)
        if text is None:
            continue
        if p.name == "test_hygiene.py":
            continue
        if LOCAL_PATHS.search(text) or SECRET_SHAPES.search(text):
            bad[p.name] = "local path or secret shape"
    assert not bad, bad


def test_gitignore_and_stubs():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert {".env", ".venv/", "out/"} <= set(ignore)
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert (ROOT / "SECURITY.md").is_file() and (ROOT / "THIRD_PARTY.md").is_file()


def test_locks_are_universal_and_hashed():
    for name in ("requirements.lock", "requirements-dev.lock"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "--universal" in text and "--generate-hashes" in text
        assert "--hash=sha256:" in text
    dev = (ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
    assert "colorama==" in dev and "sys_platform == 'win32'" in dev
    assert "setuptools==" in dev
