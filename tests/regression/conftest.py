# -*- coding: utf-8 -*-
"""
Pytest fixtures for regression testing
Mock 环境配置，不依赖外网
"""
import json
import os
import sys
import pytest

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.regression.mocks.mock_tools import MockToolsModule
from tests.regression.mocks.mock_llm import MockLLM

BASELINES_DIR = os.path.join(os.path.dirname(__file__), "baselines")


@pytest.fixture(scope="session")
def mock_tools():
    """Return MockToolsModule instance"""
    return MockToolsModule()


@pytest.fixture(scope="session")
def mock_llm():
    """Return MockLLM instance"""
    return MockLLM()


@pytest.fixture(scope="session")
def baseline_cases():
    """Load baseline test cases from JSON"""
    path = os.path.join(BASELINES_DIR, "baseline_cases.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


@pytest.fixture(scope="session")
def supervisor(mock_llm, mock_tools):
    """Build SupervisorAgent with mock dependencies"""
    from backend.orchestration.cache import DataCache
    from backend.services.circuit_breaker import CircuitBreaker
    from backend.orchestration.supervisor_agent import SupervisorAgent

    cache = DataCache()
    circuit_breaker = CircuitBreaker()

    return SupervisorAgent(
        llm=mock_llm,
        tools_module=mock_tools,
        cache=cache,
        circuit_breaker=circuit_breaker
    )


@pytest.fixture
def evaluators():
    """Return all evaluators"""
    from tests.regression.evaluators import IntentEvaluator, StructureEvaluator, CitationEvaluator
    return {
        "intent": IntentEvaluator(),
        "structure": StructureEvaluator(),
        "citation": CitationEvaluator()
    }
