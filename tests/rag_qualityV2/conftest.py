from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

EVAL_DIR = Path(__file__).parent
DATASET_PATH = PROJECT_ROOT / "tests" / "rag_quality" / "dataset.json"
THRESHOLDS_PATH = EVAL_DIR / "thresholds_v2.json"


@pytest.fixture(scope="session")
def dataset() -> dict[str, Any]:
    with DATASET_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def dataset_cases(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    return dataset["cases"]


@pytest.fixture(scope="session")
def thresholds() -> dict[str, Any]:
    with THRESHOLDS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_case(dataset_cases: list[dict[str, Any]]) -> dict[str, Any]:
    return dataset_cases[0]
