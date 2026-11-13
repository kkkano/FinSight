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

def test_price_collector_has_no_dynamic_tool_registry_or_llm():
    collector = PriceAgent(None, _Cache(), _Tools())

    assert not hasattr(collector, "_get_tool_registry")
    assert not hasattr(collector, "llm")


def test_risk_collector_has_no_dynamic_tool_registry_or_llm():
    collector = RiskAgent(None, _Cache(), _Tools())

    assert not hasattr(collector, "_get_tool_registry")
    assert not hasattr(collector, "llm")
