"""A regular (non-editable) install must find config.toml and the data from the working folder, not from site-packages."""
from __future__ import annotations

import shutil
import subprocess
import sys
import venv

import pytest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd, cwd, timeout=900):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def test_non_editable_install_replays_from_the_working_folder(tmp_path):
    env = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env)
    py = str(env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"))
    inst = _run([py, "-m", "pip", "install", "--quiet", "--require-hashes", "-r", "requirements.lock"], ROOT)
    if inst.returncode != 0:
        pytest.skip("cannot install the locked dependencies here (offline?): " + inst.stderr[-200:])
    # build from a copy in tmp_path: pip writes build/ and *.egg-info next to the sources, never into the checkout
    src = tmp_path / "src_copy"
    src.mkdir()
    shutil.copytree(ROOT / "src", src / "src", ignore=shutil.ignore_patterns("*.egg-info", "__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", src / "pyproject.toml")
    inst = _run([py, "-m", "pip", "install", "--quiet", "--no-deps", str(src)], tmp_path)
    assert inst.returncode == 0, inst.stderr[-500:]
    where = _run([py, "-c", "import runbook_cards.paths as p; print(p.__file__)"], tmp_path)
    assert "site-packages" in where.stdout, where.stdout
    out = tmp_path / "out"
    r = _run([py, "-m", "runbook_cards.cli", "eval", "--replay", "evals/recorded/live-1"], ROOT)
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    assert "FileNotFoundError" not in r.stderr
    out.mkdir()  # an empty folder has no data: the run fails, it does not silently use site-packages
    bad = _run([py, "-m", "runbook_cards.cli", "eval", "--replay", "evals/recorded/live-1"], out)
    assert bad.returncode != 0
    assert not (ROOT / "build").exists()
