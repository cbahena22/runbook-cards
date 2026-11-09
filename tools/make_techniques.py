"""Build attack/techniques.json (id -> name) for the ATT&CK ids the rules use, from a pinned STIX bundle.

    python tools/make_techniques.py --bundle enterprise-attack-18.1.json

The pinned version, its official download URL and its sha256 are the constants below (not command-line
arguments). Download the file at ATTACK_URL yourself; this script makes no network call and refuses a file whose
sha256 differs from ATTACK_SHA256 (exit 2). The sha256 was computed on first download (trust on first use) and is
recorded here, in attack/techniques.json and in THIRD_PARTY.md. Only ids found in the rules' `tags` are kept.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ATTACK_VERSION = "18.1"
ATTACK_URL = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack-18.1.json"
ATTACK_SHA256 = "f857d8f78f2f0c0b7db321a711a39fba98546c1e3076a657684850c83d0962fb"
TAG = re.compile(r"^attack\.(t\d{4})(?:\.(\d{3}))?$")


def used_ids(rules_glob_root: Path) -> list[str]:
    ids: set[str] = set()
    for f in sorted(rules_glob_root.glob("packs/*/sources/rules/*.yml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        for t in data.get("tags", []):
            m = TAG.match(str(t))
            if m:
                ids.add(m.group(1).upper() + (f".{m.group(2)}" if m.group(2) else ""))
    return sorted(ids)


def names_from_bundle(bundle: dict, wanted: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for obj in bundle.get("objects", []):
        if obj.get("type") != "attack-pattern" or obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        for ref in obj.get("external_references", []):
            if ref.get("source_name") == "mitre-attack" and ref.get("external_id") in wanted:
                found[ref["external_id"]] = obj["name"]
    return found


def main(argv: list[str] | None = None, *, version: str = ATTACK_VERSION, sha256: str = ATTACK_SHA256) -> int:
    """`version` / `sha256` default to the pinned constants; only tests pass others (with a fixture bundle)."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bundle", required=True, type=Path)
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root holding packs/ (default: this repo)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    raw = a.bundle.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != sha256.lower():
        print(f"refused: bundle sha256 does not match the pinned ATT&CK {version} value", file=sys.stderr)
        return 2
    wanted = used_ids(a.root)
    names = names_from_bundle(json.loads(raw), wanted)
    missing = [i for i in wanted if i not in names]
    if missing:
        print("refused: ids missing from the bundle: " + ", ".join(missing), file=sys.stderr)
        return 1
    out = a.out or (a.root / "attack" / "techniques.json")
    doc = {
        "source": {"name": "MITRE ATT&CK enterprise STIX bundle", "version": version, "sha256": digest, "pinned": True},
        "techniques": {i: names[i] for i in wanted},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(wanted)} techniques")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
