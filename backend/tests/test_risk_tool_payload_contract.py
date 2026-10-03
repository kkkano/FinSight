import json

import pytest

from backend.agents.risk_agent import RiskAgent


class Tools:
    def get_stock_price(self, ticker):
        return {"ticker": ticker, "price": 55.97, "change_percent": -0.37, "source": "fixture_quote"}

    def get_factor_exposure(self, _positions, **_kwargs):
        return json.dumps({"source": "fixture_factor", "factor_beta": {"market": 2.9451, "growth": 2.4804}, "annualized_volatility": 0.7699, "max_drawdown": -0.419, "error": None})

    def analyze_historical_drawdowns(self, ticker):
        return f"Top 3 Historical Drawdowns for {ticker} (coverage 1980-03-17 to 2026-10-02 (~46.5y)):\n- Drawdown: -82.25% (from 2000-08-31 to 2002-10-08)\n Duration to trough: 768 days. Recovery time: 5628 days."


@pytest.mark.asyncio
async def test_json_factor_tool_is_consumed_and_changes_risk_assessment():
    output = await RiskAgent(None, None, Tools()).research("INTC主要风险", "INTC")
    assert any("2.95" in risk for risk in output.risks)
    assert any("76.99%" in risk or "77.0%" in risk for risk in output.risks)
    factor = next(item for item in output.evidence if item.source == "fixture_factor")
    assert factor.meta["factor_beta"]["market"] == 2.9451
    assert "0.0/100" not in output.summary
    history = next(item for item in output.evidence if item.source == "historical_price_analysis")
    assert history.meta["max_drawdown"] == pytest.approx(-0.8225)
    assert history.meta["period_end"] == "2026-10-02"
    assert "历史事实" in history.text


@pytest.mark.asyncio
@pytest.mark.parametrize("factor", ["broken JSON", "[]", "null", '{"error":"provider_failed"}', '{"factor_beta":{}}'])
async def test_missing_factor_with_stable_quote_cannot_mean_zero_low_risk(factor):
    class MissingTools(Tools):
        def get_factor_exposure(self, *_args, **_kwargs):
            return factor

        def analyze_historical_drawdowns(self, _ticker):
            return "No historical data available for INTC."

    output = await RiskAgent(None, None, MissingTools()).research("INTC主要风险", "INTC")
    assert "评分未知" in output.summary
    assert "0.0/100" not in output.summary
    assert not output.chart_specs
    assert not any(claim.get("metadata", {}).get("claim_type") == "risk_score" for claim in output.claims)
    assert all(item.meta.get("risk_score") is None for item in output.evidence)
    assert output.fallback_reason == "risk_inputs_unavailable"


def test_historical_text_rejects_different_subject_and_unstructured_numbers():
    assert RiskAgent._historical_drawdown_payload(Tools().analyze_historical_drawdowns("AAPL"), "INTC").get("error")
    assert RiskAgent._historical_drawdown_payload("INTC maybe drawdown 99%", "INTC").get("error")


@pytest.mark.asyncio
async def test_provider_exception_becomes_missing_input_not_low_risk():
    class FailedTools(Tools):
        def get_factor_exposure(self, *_args, **_kwargs):
            raise ConnectionError("fixture failed")

        def analyze_historical_drawdowns(self, _ticker):
            raise TimeoutError("fixture failed")

    output = await RiskAgent(None, None, FailedTools()).research("INTC主要风险", "INTC")
    assert "评分未知" in output.summary
    assert output.fallback_used


@pytest.mark.asyncio
async def test_zero_triggered_rules_does_not_claim_overall_investment_risk_is_low():
    class QuietTools(Tools):
        def get_factor_exposure(self, *_args, **_kwargs):
            return {"factor_beta": {"market": 0.0145, "growth": -0.026},
                    "annualized_volatility": 0.2139, "max_drawdown": -0.2307}
    output = await RiskAgent(None, None, QuietTools()).research("主要风险", "INTC")
    claim = next(item for item in output.claims if item.get("metadata", {}).get("claim_type") == "risk_score")
    assert "未触发预设风险阈值" in claim["claim"]
    assert "不代表整体投资风险低" in claim["claim"]
    assert "0.0/100（低风险）" not in claim["claim"]
    assert claim["metadata"]["assessment_scope"] == "observed_rule_signals"
