"""新闻首源故障后的真实链接、查询窗口和失败语义回归。"""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests

from backend.tools import news
from backend.services.market_data_gateway import MarketDataGateway, _fetch_finnhub_news


def gateway(**kwargs):
    return MarketDataGateway(providers={}, primary_provider="", news_cache_ttl_seconds=0,
                             news_primary_provider="finnhub", news_secondary_provider="", **kwargs)


@pytest.mark.parametrize("target", ["http://127.0.0.1/private", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd"])
def test_finnhub_redirect_rejects_private_or_non_http_target(monkeypatch, target):
    calls = []
    monkeypatch.setattr(news, "is_safe_url", lambda url: url.startswith("https://finnhub.io/"))
    monkeypatch.setattr(news, "_http_get_no_retry", lambda url, **kwargs: calls.append((url, kwargs)) or
                        SimpleNamespace(status_code=302, headers={"Location": target}, close=lambda: None))
    assert news._resolve_finnhub_news_url("https://finnhub.io/api/news?id=1") == ""
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False


def test_finnhub_redirect_retains_publisher_without_fetching_it(monkeypatch):
    calls = []
    target = "https://www.reuters.com/technology/intel-results"
    monkeypatch.setattr(news, "is_safe_url", lambda _url: True)
    monkeypatch.setattr(news, "_http_get_no_retry", lambda url, **kwargs: calls.append(url) or
                        SimpleNamespace(status_code=302, headers={"Location": target}, close=lambda: None))
    assert news._resolve_finnhub_news_url("https://finnhub.io/api/news?id=1") == target
    assert calls == ["https://finnhub.io/api/news?id=1"]


def test_finnhub_requested_window_reaches_provider_and_original_url_survives(monkeypatch):
    calls = []
    def fetch(ticker, _from, to):
        calls.append((ticker, _from, to))
        return [{"headline": "Intel reports its quarterly earnings", "summary": "Intel earnings and revenue update",
                 "url": "https://finnhub.io/api/news?id=1", "source": "Reuters",
                 "datetime": datetime.now(UTC).timestamp()}]
    monkeypatch.setattr(news, "finnhub_client", SimpleNamespace(company_news=fetch))
    monkeypatch.setattr(news, "_resolve_finnhub_news_url", lambda url: "https://www.reuters.com/intel-earnings")
    instance = gateway(news_providers={"finnhub": _fetch_finnhub_news})
    result = instance.get_news("INTC", days=14)
    assert calls == [("INTC", str(date.today() - timedelta(days=14)), str(date.today()))]
    assert result["data"][0]["url"] == "https://www.reuters.com/intel-earnings"


def failed_gateway(monkeypatch, failures):
    monkeypatch.setattr("backend.services.market_data_gateway.get_market_data_gateway", lambda: SimpleNamespace(
        get_news=lambda *args, **kwargs: {"data": [], "error_code": "market_data_unavailable",
            "attempted_providers": ["finnhub", "yfinance"], "provider_failures": failures}))


def test_news_recovers_linked_search_discovery_without_inventing_publication(monkeypatch):
    failed_gateway(monkeypatch, ["provider_request_failed", "provider_no_results"])
    calls = []
    monkeypatch.setattr(news, "search", lambda query: calls.append(query) or
                        "1. Intel announces quarterly financial results\n2026-11-07 Intel financial results.\nhttps://www.intel.com/news/earnings\n"
                        "2. Nvidia announces new chips\nNVIDIA GPUs ship soon.\nhttps://www.nvidia.com/news/chips")
    result = news.get_company_news("INTC", max_age_hours=336)
    assert len(calls) == 1 and "14 days" in calls[0]
    assert len(result) == 1
    assert result[0]["url"] == "https://www.intel.com/news/earnings"
    assert result[0]["ticker"] == "INTC"
    assert result[0]["published_at"] is None
    assert result[0]["date_hint"] == "2026-11-07"
    assert result[0]["event_quality"]["verification"] == "discovery_only"
    assert result[0]["provider_failures"] == ["provider_request_failed", "provider_no_results"]
    assert result[0]["attempted_providers"] == ["finnhub", "yfinance", "web_search"]


@pytest.mark.parametrize("failures,text,status,code", [
    (["provider_request_failed", "provider_no_results"], "Search error: 全部失败", "unavailable", "market_data_unavailable"),
    (["provider_no_results", "provider_no_results"], "未找到相关搜索结果。", "empty", "news_no_matching_results"),
])
def test_news_distinguishes_provider_failure_from_empty_matches(monkeypatch, failures, text, status, code):
    failed_gateway(monkeypatch, failures)
    monkeypatch.setattr(news, "search", lambda query: text)
    result = news.get_company_news("INTC")
    assert result["status"] == status
    assert result["error"] == code
    assert result["data"] == []
    assert result["attempted_providers"][-1] == "web_search"


def test_provider_exception_preserves_request_failure_not_empty_list(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.Timeout("private provider URL must not escape")
    monkeypatch.setattr(news, "finnhub_client", SimpleNamespace(company_news=fail))
    result = gateway(news_providers={"finnhub": _fetch_finnhub_news}).get_news("INTC")
    assert result["provider_failures"] == ["provider_request_failed"]
    assert "private provider" not in str(result)
