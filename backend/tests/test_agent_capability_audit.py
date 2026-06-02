# -*- coding: utf-8 -*-
from backend.agents.price_agent import PriceAgent
from backend.agents.risk_agent import RiskAgent


class _Cache:
    def get(self, _key):
        return None

    def set(self, _key, _value, _ttl=None):
        return None


class _Tools:
    def search(self, query):
        return f"search:{query}"

    def get_stock_price(self, ticker):
        return {"ticker": ticker, "price": 100}

    def get_option_chain_metrics(self, ticker):
        return {"ticker": ticker, "iv_atm": 0.4}

    def get_stock_historical_data(self, ticker, period="1y", interval="1d"):
        return {"ticker": ticker, "period": period, "interval": interval, "kline_data": []}

    def analyze_historical_drawdowns(self, ticker):
        return {"ticker": ticker, "max_drawdown": -0.25}

    def get_factor_exposure(self, positions, lookback_days=252):
        return {"positions": positions, "lookback_days": lookback_days}

    def run_portfolio_stress_test(self, positions, scenarios=None, lookback_days=252):
        return {"positions": positions, "scenarios": scenarios or []}


def test_price_agent_registry_exposes_quote_and_options_tools():
    registry = PriceAgent(None, _Cache(), _Tools())._get_tool_registry()

    assert {
        "search",
        "get_stock_price",
        "get_stock_historical_data",
        "get_market_benchmark_history",
        "get_relative_strength",
        "analyze_historical_drawdowns",
        "get_option_chain_metrics",
    }.issubset(registry)
    assert registry["get_stock_price"]["call_with"] == "ticker"
    assert registry["get_stock_historical_data"]["call_with"] == "ticker"
    assert registry["get_relative_strength"]["call_with"] == "ticker"
    assert registry["get_option_chain_metrics"]["call_with"] == "ticker"


def test_risk_agent_registry_exposes_risk_specific_tools():
    registry = RiskAgent(None, _Cache(), _Tools())._get_tool_registry()

    assert {
        "search",
        "get_stock_price",
        "analyze_historical_drawdowns",
        "get_factor_exposure",
        "run_portfolio_stress_test",
    }.issubset(registry)
    assert registry["analyze_historical_drawdowns"]["call_with"] == "ticker"
    assert registry["get_factor_exposure"]["call_with"] == "positions"
    assert registry["run_portfolio_stress_test"]["call_with"] == "positions"
