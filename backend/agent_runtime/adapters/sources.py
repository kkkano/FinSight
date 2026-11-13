"""现有供应商的结构化入口，避免先格式化成正文再反向拆字段。"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from urllib.parse import quote


def company_profile(arguments):
    from backend.tools import financial

    ticker = arguments["ticker"]
    failures = []
    try:
        info = financial.create_ticker(ticker).info
        if isinstance(info, dict) and info.get("longName"):
            return {**info, "ticker": ticker, "source": "yfinance", "status": "ok",
                    "source_url": f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}/profile/",
                    "retrieved_at": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        failures.append({"provider": "yfinance", "exception_type": type(exc).__name__})
    if financial.finnhub_client is not None:
        try:
            profile = financial.finnhub_client.company_profile2(symbol=ticker)
            if isinstance(profile, dict) and profile.get("name"):
                return {**profile, "ticker": ticker, "source": "finnhub", "status": "ok",
                        "column_units": {"marketCapitalization": "million " + str(profile.get("currency") or "unknown")},
                        "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider_failures": failures}
        except Exception as exc:
            failures.append({"provider": "finnhub", "exception_type": type(exc).__name__})
    if financial.ALPHA_VANTAGE_API_KEY:
        try:
            response = financial._http_get("https://www.alphavantage.co/query", params={
                "function": "OVERVIEW", "symbol": ticker, "apikey": financial.ALPHA_VANTAGE_API_KEY}, timeout=10)
            response.raise_for_status()
            profile = response.json()
            if isinstance(profile, dict) and profile.get("Symbol"):
                return {**profile, "ticker": ticker, "source": "alpha_vantage", "status": "ok",
                        "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider_failures": failures}
        except Exception as exc:
            failures.append({"provider": "alpha_vantage", "exception_type": type(exc).__name__})
    return {"status": "unavailable", "error_code": "market_data_unavailable", "ticker": ticker,
            "provider_failures": failures}


def web_search(arguments):
    # 只复用现有安装与安全配置；不增加 SDK、密钥或按查询文字决定供应商。
    import importlib
    provider = importlib.import_module("backend.tools.search")
    query = arguments["query"]
    failures = []
    if provider.EXA_API_KEY and provider.EXA_AVAILABLE and provider.Exa is not None:
        try:
            response = provider.Exa(api_key=provider.EXA_API_KEY).search_and_contents(
                query=query, type="neural", num_results=10, text=True, highlights=True)
            rows = [{"title": row.title, "url": row.url, "content": getattr(row, "text", None),
                     "highlights": getattr(row, "highlights", None),
                     "published_at": getattr(row, "published_date", None)} for row in response.results]
            if rows:
                return {"status": "ok", "source": "exa", "results": rows, "provider_failures": failures}
        except Exception as exc:
            failures.append({"provider": "exa", "exception_type": type(exc).__name__})
    if provider.TAVILY_API_KEY and provider.TAVILY_AVAILABLE and provider.TavilyClient is not None:
        try:
            response = provider.TavilyClient(api_key=provider.TAVILY_API_KEY).search(
                query=query, search_depth="advanced", max_results=10, include_answer=True, include_raw_content=False)
            if isinstance(response, dict) and response.get("results"):
                return {**response, "status": "ok", "source": "tavily", "provider_failures": failures}
        except Exception as exc:
            failures.append({"provider": "tavily", "exception_type": type(exc).__name__})
    if provider.WIKIPEDIA_AVAILABLE and provider.wikipedia is not None:
        try:
            rows = []
            for title in provider.wikipedia.search(query, results=3):
                page = provider.wikipedia.page(title, auto_suggest=False)
                rows.append({"title": page.title, "url": page.url, "content": page.summary})
            if rows:
                return {"status": "ok", "source": "wikipedia", "results": rows, "provider_failures": failures}
        except Exception as exc:
            failures.append({"provider": "wikipedia", "exception_type": type(exc).__name__})
    if provider.DDGS_AVAILABLE and provider.DDGS is not None:
        try:
            proxy = os.getenv("SEARCH_PROXY")
            client = provider.DDGS(proxy=proxy) if proxy else provider.DDGS()
            rows = [{**row, "url": row.get("href"), "content": row.get("body")} for row in
                    client.text(query, max_results=10, safesearch="moderate")]
            if rows:
                return {"status": "ok", "source": "duckduckgo", "results": rows, "provider_failures": failures}
        except Exception as exc:
            failures.append({"provider": "duckduckgo", "exception_type": type(exc).__name__})
    return {"status": "error" if failures else "empty", "results": [],
            "error_code": "tool_provider_error" if failures else None, "provider_failures": failures}
