"""Repo-relative paths. Nothing printed by this package is ever absolute."""
from __future__ import annotations

from pathlib import Path

def _find_root() -> Path:
    """The folder that holds config.toml, packs/, cards/ and evals/.

    In a checkout (plain or `pip install -e`) that is two levels above this file. In a regular install the package sits in
    site-packages, which has none of that data, so the working folder is used (run the tool from a checkout)."""
    here = Path(__file__).resolve().parents[2]
    return here if (here / "config.toml").is_file() else Path.cwd().resolve()


ROOT = _find_root()
PACKS_DIR = ROOT / "packs"
CARDS_DIR = ROOT / "cards"
SITE_DIR = ROOT / "site"
CONFIG = ROOT / "config.toml"
EVALS_DIR = ROOT / "evals"
TECHNIQUES = ROOT / "attack" / "techniques.json"
SCHEMA = Path(__file__).resolve().parent / "schema" / "card.schema.json"
TEMPLATES = Path(__file__).resolve().parent / "templates"


def rel(path: Path | str) -> str:
    """Repo-relative form of a path; a path outside the repo shows only its last part."""
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return "<outside>/" + p.name
