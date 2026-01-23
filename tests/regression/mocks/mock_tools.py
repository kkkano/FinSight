# -*- coding: utf-8 -*-
"""
Mock Tools Module for Regression Testing
固定数据源，不依赖外网，可复现
"""
import json
import os
from typing import Any, Dict, List, Optional

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> Dict:
    path = os.path.join(FIXTURES_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


class MockToolsModule:
    """Mock 工具模块 - 返回固定数据"""

    def __init__(self):
        self._price_data = _load_fixture("price_data")
        self._news_data = _load_fixture("news_data")
        self._sentiment_data = _load_fixture("sentiment_data")

    def get_stock_price(self, ticker: str) -> Dict[str, Any]:
        if ticker.startswith("INVALID") or ticker.startswith("UNKNOWN"):
            return {"error": f"No data found for {ticker}"}
        if ticker.startswith("FAIL_"):
            return {"error": "Simulated failure", "ticker": ticker}
        data = self._price_data.get(ticker)
        if data:
            return data
        # Default mock data
        return {
            "price": 100.00,
            "change_percent": 0.5,
            "volume": 1000000,
            "ticker": ticker
        }

    def get_company_news(self, ticker: str) -> List[Dict[str, Any]]:
        if ticker.startswith("UNKNOWN"):
            return []
        news = self._news_data.get(ticker, [])
        if not news:
            return [{"headline": f"Mock news for {ticker}", "source": "Mock", "url": "#", "datetime": "2026-01-22"}]
        return news

    def get_market_sentiment(self) -> Dict[str, Any]:
        return self._sentiment_data or {"fear_greed_index": 50, "fear_greed_label": "Neutral"}

    def search(self, query: str) -> str:
        return f"[Mock Search Result] Query: {query}. Found relevant financial information."

    def get_performance_comparison(self, tickers: List[str]) -> Dict[str, Any]:
        result = {}
        for ticker in tickers:
            price_data = self.get_stock_price(ticker)
            result[ticker] = {
                "price": price_data.get("price", 100),
                "change_percent": price_data.get("change_percent", 0),
                "ytd_return": 5.0
            }
        return result

    def get_financial_statements(self, ticker: str) -> Dict[str, Any]:
        return {
            "ticker": ticker,
            "revenue": 100000000000,
            "net_income": 20000000000,
            "eps": 5.50,
            "pe_ratio": 28.5
        }

    def get_economic_events(self) -> List[Dict[str, Any]]:
        return [
            {"event": "Fed Meeting", "date": "2026-01-28", "impact": "high"},
            {"event": "GDP Report", "date": "2026-01-30", "impact": "medium"}
        ]

    def format_news_items(self, news_items: List[Dict], title: str = "News") -> str:
        lines = [f"**{title}**"]
        for item in news_items[:5]:
            headline = item.get("headline", item.get("title", "No title"))
            source = item.get("source", "Unknown")
            lines.append(f"- {headline} ({source})")
        return "\n".join(lines)
