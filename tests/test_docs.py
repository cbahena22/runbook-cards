"""The write-ups: every relative link resolves, the AI-use line is in the README, no slot is left in a page that claims a result."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from runbook_cards.paths import ROOT

DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)")
AI_LINE = "Designed, specified and reviewed by me; most code written by Claude Code agents I directed."


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_relative_link_resolves(doc):
    for target in LINK.findall(doc.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = (doc.parent / target.split("#")[0]).resolve()
        assert path.exists(), f"{doc.name}: {target}"


def test_the_readme_carries_the_ai_use_line():
    assert AI_LINE in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_docs_use_the_fictional_client():
    text = "\n".join(p.read_text(encoding="utf-8") for p in DOCS)
    assert "Calder Health MSSP" in text


def test_the_readme_result_numbers_equal_the_recorded_run():
    import json
    res = json.loads((ROOT / "evals" / "results" / "live-1.json").read_text(encoding="utf-8"))
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    s, h = res["security"], res["helpdesk"]
    nh = s["needs_human"]
    assert f"${res['cost']['total_usd']:.2f}" in text and "45 units" in text and s["n"] + h["n"] == 45
    assert s["grounded_fields"][0] == s["grounded_fields"][1] and h["grounded_fields"][0] == h["grounded_fields"][1]
    total = s["grounded_fields"][1] + h["grounded_fields"][1]
    assert f"the {total} fields that reached a card" in text
    assert f"{sum(nh.values())} of {s['n']} security rules refused" in text
    assert f"error {nh['error']}, unsupported {nh['unsupported']}, validator {nh['validator']}" in text
    assert f"{h['escalate_match']} / {h['n']}" in text and f"{h['steps_in_range']} / {h['n']}" in text
    assert "Human spot check" not in text and res["spot_check"] is None  # no row for a check that has not happened
    assert "No human spot check yet; planned: 20 cards read by the author." in text
    assert f"{res['redteam']['reported']} / {res['redteam']['n']}, {res['redteam']['followed']} / {res['redteam']['n']}" in text
    assert "SLOT" not in text and "SLOT" not in (ROOT / "docs" / "pilot-readout.md").read_text(encoding="utf-8")


def test_the_reworded_recording_is_disclosed_in_the_readout_only():
    readout = (ROOT / "docs" / "pilot-readout.md").read_text(encoding="utf-8")
    assert "8 single words in 6 recorded replies were reworded" in readout and "every score and cost is unchanged" in readout
