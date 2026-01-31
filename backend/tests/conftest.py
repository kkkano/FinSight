# -*- coding: utf-8 -*-
"""
Test fixtures for backend tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import os


@pytest.fixture(scope="session", autouse=True)
def disable_llm_rate_limit() -> None:
    """Disable global LLM rate limiter for deterministic tests."""
    os.environ["LLM_RATE_LIMIT_ENABLED"] = "false"
    try:
        from backend.services.rate_limiter import LLMRateLimiter
        LLMRateLimiter.reset_instance()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def reset_test_api_user_profile() -> None:
    """Keep test_api_user deterministic across test order."""
    path = Path("data/memory/test_api_user.json")
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    data["risk_tolerance"] = "medium"
    if "investment_style" not in data:
        data["investment_style"] = "balanced"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def ticker() -> str:
    """Default ticker for integration tests."""
    return "AAPL"
