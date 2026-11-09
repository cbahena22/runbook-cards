import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def security():
    from runbook_cards.packs import get_pack
    p = get_pack("security")
    return p, p.units(p.load())


@pytest.fixture(scope="session")
def helpdesk():
    from runbook_cards.packs import get_pack
    p = get_pack("helpdesk")
    return p, p.units(p.load())
