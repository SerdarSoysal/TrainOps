from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = REPO_ROOT / "samples"


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES
