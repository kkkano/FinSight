"""公开行情与 Dashboard 不能绕过新闻质量合同。"""
from datetime import datetime, timezone

from backend.dashboard.data_service import _to_news_item
from backend.dashboard.schemas import NewsItem
from backend.services.market_data_gateway import MarketDataGateway


def test_public_news_gateway_and_dashboard_keep_quality_on_cache_hit():
    calls = []
    def news(symbol, limit):
        calls.append(symbol)
        return [{"title": "Apple introduces a new product", "source": "Reuters",
                 "url": "https://www.reuters.com/technology/apple-product",
                 "published_at": datetime.now(timezone.utc).isoformat(), "ticker": symbol}]
    gateway = MarketDataGateway(providers={}, primary_provider="none",
        news_providers={"fixture": news}, news_primary_provider="fixture",
        news_secondary_provider="", news_trusted_providers={"fixture"}, news_cache_ttl_seconds=300)
    first = gateway.get_news("AAPL")["data"][0]
    second = gateway.get_news("AAPL")["data"][0]
    public = NewsItem.model_validate(_to_news_item(second)).model_dump()
    assert calls == ["AAPL"]
    assert public["event_quality"]["observed_at"] == first["event_quality"]["observed_at"]
    assert public["event_quality"]["evidence_role"] == "reported_news"
    assert public["event_quality"]["verification"] == "headline_only"
    assert public["supporting_reports"][0]["url"] == first["url"]
