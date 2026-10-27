from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"


@pytest.fixture
def cases() -> Path:
    return CASES


@pytest.fixture
def core() -> Path:
    return CASES / "core"
