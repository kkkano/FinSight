# -*- coding: utf-8 -*-
import json
import os
from pathlib import Path

import pytest

# Keep test runtime deterministic and avoid async sqlite destructor noise in
# short-lived TestClient lifecycles unless a test explicitly overrides backend.
os.environ.setdefault("LANGGRAPH_CHECKPOINTER_BACKEND", "memory")
os.environ.setdefault("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", "true")


@pytest.fixture(autouse=True)
def _force_langgraph_deterministic_defaults(monkeypatch):
    """
    Tests must be deterministic and must NOT call external LLMs/tools by default.

    Individual tests can override these env vars when explicitly testing LLM/tool modes.
    """

    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "stub")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setenv("ENABLE_LANGSMITH", "false")


@pytest.fixture(autouse=True)
def _reset_api_memory_test_fixtures():
    """
    Some API tests persist user profiles/watchlists to `data/memory/*.json`.
    Reset them before each test to avoid order-dependence and dirty working trees.
    """

    repo_root = Path(__file__).resolve().parents[2]
    memory_dir = repo_root / "data" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    (memory_dir / "test_api_user.json").write_text(
        json.dumps(
            {
                "user_id": "test_api_user",
                "risk_tolerance": "medium",
                "investment_style": "balanced",
                "watchlist": [],
                "preferences": {},
                "last_active": "2026-02-03T00:00:00Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (memory_dir / "test_api_user_wl.json").write_text(
        json.dumps(
            {
                "user_id": "test_api_user_wl",
                "risk_tolerance": "medium",
                "investment_style": "balanced",
                "watchlist": [],
                "preferences": {},
                "last_active": "2026-02-03T00:00:00Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
