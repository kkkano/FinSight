from __future__ import annotations

from backend.dashboard.data_service import fetch_news


def test_fetch_news_returns_ranking_meta_v2(monkeypatch):
    def _fake_company_news(symbol: str, limit: int = 20):
        return [
            {
                "title": f"{symbol} raises guidance after earnings beat",
                "summary": "Earnings and guidance update",
                "source": "Reuters",
                "ts": "2026-02-08T10:00:00+00:00",
                "url": "https://example.com/impact-1",
            },
            {
                "title": f"{symbol} supply chain outlook stable",
                "summary": "Operational note",
                "source": "Yahoo Finance",
                "ts": "2026-02-08T09:00:00+00:00",
                "url": "https://example.com/impact-2",
            },
        ]

    def _fake_market_news(limit: int = 20):
        return [
            {
                "title": "US market opens mixed ahead of CPI",
                "summary": "Macro focus on inflation",
                "source": "Bloomberg",
                "ts": "2026-02-08T08:00:00+00:00",
                "url": "https://example.com/market-1",
            },
            {
                "title": "Rates outlook remains uncertain",
                "summary": "Fed watchers split",
                "source": "MarketWatch",
                "ts": "2026-02-08T07:00:00+00:00",
                "url": "https://example.com/market-2",
            },
        ]

    monkeypatch.setattr("backend.tools.news.get_company_news", _fake_company_news)
    monkeypatch.setattr("backend.tools.news.get_market_news_headlines", _fake_market_news)

    payload = fetch_news("AAPL", limit=20)

    ranking_meta = payload.get("ranking_meta") or {}
    assert ranking_meta.get("version") == "v2"
    assert "weights" in ranking_meta
    assert "half_life_hours" in ranking_meta

    impact = payload.get("impact") or []
    market = payload.get("market") or []
    assert impact and market

    first_item = impact[0]
    assert "asset_relevance" in first_item
    assert "source_penalty" in first_item
    assert "ranking_reason" in first_item
    assert isinstance(first_item.get("ranking_factors"), dict)


def test_ranked_news_has_stable_descending_order(monkeypatch):
    def _fake_company_news(symbol: str, limit: int = 20):
        return [
            {
                "title": "Update A",
                "summary": "guidance and earnings",
                "source": "Reuters",
                "ts": "2026-02-08T10:00:00+00:00",
                "url": "https://example.com/a",
            },
            {
                "title": "Update B",
                "summary": "guidance and earnings",
                "source": "Reuters",
                "ts": "2026-02-08T10:00:00+00:00",
                "url": "https://example.com/b",
            },
        ]

    def _fake_market_news(limit: int = 20):
        return []

    monkeypatch.setattr("backend.tools.news.get_company_news", _fake_company_news)
    monkeypatch.setattr("backend.tools.news.get_market_news_headlines", _fake_market_news)

    payload = fetch_news("AAPL", limit=20)
    ranked = payload.get("impact") or []

    assert len(ranked) == 2
    assert float(ranked[0].get("ranking_score") or 0.0) >= float(ranked[1].get("ranking_score") or 0.0)
    # score ties should have deterministic order by title
    assert [item.get("title") for item in ranked] == sorted([item.get("title") for item in ranked])

