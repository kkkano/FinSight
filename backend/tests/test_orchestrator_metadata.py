"""
Additional metadata/observability tests for ToolOrchestrator.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.orchestration import ToolOrchestrator, DataSource


def _mock_success(ticker: str) -> str:
    return {"price": 100.0, "change_percent": 1.2}


def _mock_fail(ticker: str) -> str:
    raise Exception("fail")


def test_fallback_sets_metadata_and_trace():
    orchestrator = ToolOrchestrator()
    orchestrator.sources["price"] = [
        DataSource("fail_source", _mock_fail, 1, 60),
        DataSource("ok_source", _mock_success, 2, 60),
    ]

    result = orchestrator.fetch("price", "AAPL")

    assert result.success is True
    assert result.fallback_used is True
    assert result.tried_sources == ["fail_source", "ok_source"]
    assert isinstance(result.trace, dict)
    assert "tried_sources" in result.trace

    result_dict = result.to_dict()
    assert result_dict["fallback_used"] is True
    assert result_dict["tried_sources"] == ["fail_source", "ok_source"]
    assert result_dict["trace"]["tried_sources"] == ["fail_source", "ok_source"]
