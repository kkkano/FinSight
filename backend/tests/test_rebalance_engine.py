import pytest

from backend.api.rebalance_schemas import RebalanceConstraints, RiskTier
from backend.services.rebalance_engine import RebalanceContext, RebalanceEngine


def _base_context(**overrides) -> RebalanceContext:
    params = {
        "session_id": "public:test_user:thread-1",
        "portfolio": [
            {"ticker": "AAPL", "shares": 10},
            {"ticker": "MSFT", "shares": 5},
        ],
        "risk_tier": RiskTier.MODERATE,
        "constraints": RebalanceConstraints(
            max_single_position_pct=55,
            max_turnover_pct=30,
            sector_concentration_limit=100,
            min_action_delta_pct=1,
        ),
        "live_prices": {"AAPL": 200.0, "MSFT": 100.0},
        "sector_map": {"AAPL": "Technology", "MSFT": "Technology"},
    }
    params.update(overrides)
    return RebalanceContext(**params)


@pytest.mark.asyncio
async def test_rebalance_actions_include_evidence_snapshots():
    engine = RebalanceEngine()
    suggestion = await engine.generate(_base_context())

    assert suggestion.degraded_mode is False
    assert len(suggestion.actions) >= 1
    first_action = suggestion.actions[0]
    assert len(first_action.evidence_ids) >= 1
    assert len(first_action.evidence_snapshots) >= 1
    assert all(item.evidence_id for item in first_action.evidence_snapshots)


@pytest.mark.asyncio
async def test_llm_enhancer_failure_falls_back_to_deterministic(caplog):
    async def failing_enhancer(*_args, **_kwargs):
        raise RuntimeError("llm offline")

    engine = RebalanceEngine(llm_enhancer=failing_enhancer)
    caplog.set_level("WARNING")
    suggestion = await engine.generate(_base_context(use_llm_enhancement=True))

    assert len(suggestion.actions) >= 1
    assert any("fallback to deterministic" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_llm_enhancer_switch_is_respected():
    calls = {"count": 0}

    async def enhancer(_candidates, _diag, _ctx):
        calls["count"] += 1
        return []

    engine = RebalanceEngine(llm_enhancer=enhancer)
    suggestion = await engine.generate(_base_context(use_llm_enhancement=True))

    assert calls["count"] == 1
    assert suggestion.actions == []
