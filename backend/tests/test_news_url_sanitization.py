from backend.tools.news import _build_news_item


def test_build_news_item_strips_finnhub_api_redirect_url():
    item = _build_news_item(
        title="Sample headline",
        source="Yahoo",
        url="https://finnhub.io/api/news?id=abc123",
        published_at="2026-02-13",
        snippet="sample",
        ticker="AAPL",
        confidence=0.8,
    )
    assert item.get("url") == ""


def test_build_news_item_keeps_normal_article_url():
    article_url = "https://www.reuters.com/world/us/apple-announces-new-product-2026-02-13/"
    item = _build_news_item(
        title="Reuters sample",
        source="Reuters",
        url=article_url,
        published_at="2026-02-13",
        snippet="sample",
        ticker="AAPL",
        confidence=0.8,
    )
    assert item.get("url") == article_url
