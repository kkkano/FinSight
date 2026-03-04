"""Peer comparison data service.

Resolves peer symbols based on industry/sector and fetches comparative
valuation metrics for a target symbol and its peers.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from typing import Any, Optional

from backend.utils.quote import safe_float

logger = logging.getLogger(__name__)

# Hardcoded sector peer map used when dynamic resolution is unavailable.
_SECTOR_PEER_MAP: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN", "CRM", "ORCL"],
    "Consumer Electronics": ["AAPL", "SONY", "SSNLF", "HPQ", "DELL"],
    "Semiconductors": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM", "MU", "TXN"],
    "Internet Content & Information": ["GOOGL", "META", "SNAP", "PINS", "BIDU"],
    "Software - Infrastructure": ["MSFT", "ORCL", "CRM", "NOW", "ADBE", "INTU"],
    "Automotive": ["TSLA", "F", "GM", "TM", "HMC", "STLA", "RIVN"],
    "Financial Services": ["JPM", "BAC", "GS", "MS", "WFC", "C", "SCHW"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD", "SBUX", "TGT"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA", "T", "VZ"],
}

_DEFAULT_PEERS_BY_MARKET: dict[str, list[str]] = {
    "US": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "XOM", "UNH"],
    "CN": ["600519.SS", "000858.SZ", "601318.SS", "600036.SS", "600900.SS", "601899.SS"],
    "HK": ["0700.HK", "9988.HK", "1299.HK", "0005.HK", "0939.HK", "2318.HK"],
}
_DEFAULT_PEERS: list[str] = list(_DEFAULT_PEERS_BY_MARKET["US"])


_FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def _infer_market_from_symbol(symbol: str) -> str:
    ticker = str(symbol or "").strip().upper()
    if ticker.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if ticker.endswith(".HK"):
        return "HK"
    return "US"


def _finnhub_request(path: str, params: Optional[dict[str, Any]] = None) -> Any | None:
    try:
        from backend.tools.env import FINNHUB_API_KEY
        from backend.tools.http import _http_get

        token = str(FINNHUB_API_KEY or "").strip()
        if not token:
            return None
        query = dict(params or {})
        query["token"] = token
        url = f"{_FINNHUB_BASE_URL}/{path.lstrip('/')}"
        resp = _http_get(url, params=query, timeout=8)
        if getattr(resp, "status_code", 0) != 200:
            return None
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("error"):
            return None
        return payload
    except Exception as exc:
        logger.info("[PeerService] Finnhub request failed for %s: %s", path, exc)
        return None


def _pct_to_ratio(value: Any) -> Optional[float]:
    number = safe_float(value)
    if number is None:
        return None
    return number / 100.0


def _market_cap_to_usd(value: Any) -> Optional[float]:
    number = safe_float(value)
    if number is None:
        return None
    return number * 1_000_000.0


def _has_peer_metrics(row: dict[str, Any]) -> bool:
    return any(
        row.get(key) is not None
        for key in (
            "trailing_pe",
            "forward_pe",
            "price_to_book",
            "ev_to_ebitda",
            "net_margin",
            "roe",
            "revenue_growth",
            "dividend_yield",
            "market_cap",
        )
    )


def _fetch_single_peer_metrics_from_finnhub(sym: str) -> dict[str, Any] | None:
    profile = _finnhub_request("stock/profile2", {"symbol": sym})
    metric_payload = _finnhub_request("stock/metric", {"symbol": sym, "metric": "all"})
    metric = metric_payload.get("metric") if isinstance(metric_payload, dict) else {}
    if not isinstance(metric, dict):
        metric = {}

    result = {
        "symbol": sym,
        "name": (profile or {}).get("name") if isinstance(profile, dict) else sym,
        "trailing_pe": safe_float(metric.get("peTTM") or metric.get("peBasicExclExtraTTM")),
        "forward_pe": safe_float(metric.get("forwardPE") or metric.get("peExclExtraAnnual")),
        "price_to_book": safe_float(metric.get("pbQuarterly")),
        "ev_to_ebitda": safe_float(metric.get("evEbitdaTTM")),
        "net_margin": _pct_to_ratio(metric.get("netProfitMarginTTM")),
        "roe": _pct_to_ratio(metric.get("roeTTM")),
        "revenue_growth": _pct_to_ratio(metric.get("revenueGrowthTTMYoy")),
        "dividend_yield": _pct_to_ratio(metric.get("dividendYieldIndicatedAnnual")),
        "market_cap": _market_cap_to_usd(
            (profile or {}).get("marketCapitalization") if isinstance(profile, dict) else metric.get("marketCapitalization")
        ),
    }
    if not _has_peer_metrics(result):
        return None
    if not result.get("name"):
        result["name"] = sym
    return result


def _fetch_single_peer_metrics_from_cn_hk(sym: str) -> dict[str, Any] | None:
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_quote_metrics

        payload = fetch_cn_hk_quote_metrics(sym)
        if not isinstance(payload, dict):
            return None
        result = {
            "symbol": sym,
            "name": payload.get("name") or sym,
            "trailing_pe": safe_float(payload.get("trailing_pe")),
            "forward_pe": safe_float(payload.get("forward_pe")),
            "price_to_book": safe_float(payload.get("price_to_book")),
            "ev_to_ebitda": safe_float(payload.get("ev_to_ebitda")),
            "net_margin": None,
            "roe": None,
            "revenue_growth": None,
            "dividend_yield": safe_float(payload.get("dividend_yield")),
            "market_cap": safe_float(payload.get("market_cap")),
        }
        if not _has_peer_metrics(result):
            return None
        return result
    except Exception as exc:
        logger.info("[PeerService] CN/HK metrics fetch failed for %s: %s", sym, exc)
        return None


def resolve_peers(symbol: str, limit: int = 6) -> list[str]:
    """Find peer symbols based on industry/sector from yfinance.

    Falls back to a hardcoded sector map when dynamic lookup fails.
    The target *symbol* is excluded from the returned list.

    Args:
        symbol: The target ticker symbol.
        limit: Maximum number of peer symbols to return.

    Returns:
        A list of peer ticker strings (may be empty).
    """
    market = _infer_market_from_symbol(symbol)
    if market in {"CN", "HK"}:
        defaults = _DEFAULT_PEERS_BY_MARKET.get(market, _DEFAULT_PEERS_BY_MARKET["US"])
        return [s for s in defaults if s.upper() != symbol.upper()][:limit]

    industry = ""
    sector = ""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        industry = info.get("industry", "") or ""
        sector = info.get("sector", "") or ""
    except Exception as exc:
        logger.info("[PeerService] yfinance info failed for %s: %s", symbol, exc)

    # Try FMP stock screener with matching industry (best-effort)
    peers: list[str] = []
    if industry:
        try:
            from backend.tools.fmp import _fmp_request

            data = _fmp_request(
                "/v3/stock-screener",
                params={
                    "industry": industry,
                    "limit": str(limit + 5),
                    "exchange": "NYSE,NASDAQ",
                },
            )
            if isinstance(data, list):
                for item in data:
                    sym = item.get("symbol", "")
                    if sym and sym.upper() != symbol.upper():
                        peers.append(sym)
                    if len(peers) >= limit:
                        break
        except Exception as exc:
            logger.info("[PeerService] FMP screener failed: %s", exc)

    # Fallback to hardcoded sector map
    if not peers:
        candidates: list[str] = []
        # Try industry-level match first, then sector-level
        for key in (industry, sector):
            if key and key in _SECTOR_PEER_MAP:
                candidates = _SECTOR_PEER_MAP[key]
                break
        if not candidates:
            # Partial match on sector name
            sector_lower = sector.lower()
            for key, syms in _SECTOR_PEER_MAP.items():
                if sector_lower and (key.lower() in sector_lower or sector_lower in key.lower()):
                    candidates = syms
                    break
        peers = [s for s in candidates if s.upper() != symbol.upper()][:limit]

    if not peers:
        defaults = _DEFAULT_PEERS_BY_MARKET.get(market, _DEFAULT_PEERS_BY_MARKET["US"])
        peers = [s for s in defaults if s.upper() != symbol.upper()][:limit]

    return peers[:limit]


def _fetch_single_peer_metrics(sym: str) -> dict[str, Any]:
    """Fetch valuation metrics for a single symbol via yfinance."""
    market = _infer_market_from_symbol(sym)
    if market in {"CN", "HK"}:
        cn_hk_result = _fetch_single_peer_metrics_from_cn_hk(sym)
        if cn_hk_result:
            return cn_hk_result

    yfinance_result: dict[str, Any] = {"symbol": sym, "name": sym}
    try:
        import yfinance as yf

        info = yf.Ticker(sym).info or {}
        yfinance_result = {
            "symbol": sym,
            "name": info.get("shortName") or info.get("longName") or sym,
            "trailing_pe": safe_float(info.get("trailingPE")),
            "forward_pe": safe_float(info.get("forwardPE")),
            "price_to_book": safe_float(info.get("priceToBook")),
            "ev_to_ebitda": safe_float(info.get("enterpriseToEbitda")),
            "net_margin": safe_float(info.get("profitMargins")),
            "roe": safe_float(info.get("returnOnEquity")),
            "revenue_growth": safe_float(info.get("revenueGrowth")),
            "dividend_yield": safe_float(info.get("dividendYield")),
            "market_cap": safe_float(info.get("marketCap")),
        }
        if _has_peer_metrics(yfinance_result):
            return yfinance_result
    except Exception as exc:
        logger.info("[PeerService] metrics fetch failed for %s: %s", sym, exc)

    finnhub_result = _fetch_single_peer_metrics_from_finnhub(sym)
    if finnhub_result:
        return finnhub_result
    return yfinance_result


def fetch_peer_comparison(
    symbol: str,
    peers: list[str] | None = None,
) -> dict[str, Any] | None:
    """Fetch comparison metrics for *symbol* and its peers.

    Args:
        symbol: The target ticker.
        peers: Optional explicit peer list.  If *None*, peers are
            resolved automatically via :func:`resolve_peers`.

    Returns:
        A dict matching the ``PeerComparisonData`` schema, or *None*
        on total failure.
    """
    try:
        if peers is None:
            peers = resolve_peers(symbol, limit=6)

        all_symbols = [symbol] + [p for p in peers if p.upper() != symbol.upper()]

        # Fetch metrics in parallel (max 3 workers for budget constraint).
        # Use a global timeout to avoid cumulative per-future waits.
        results_by_symbol: dict[str, dict[str, Any]] = {
            s: {"symbol": s, "name": s} for s in all_symbols
        }
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_fetch_single_peer_metrics, s): s for s in all_symbols}
            try:
                for future in as_completed(futures, timeout=8):
                    sym = futures[future]
                    try:
                        result = future.result()
                        if isinstance(result, dict):
                            results_by_symbol[sym] = result
                    except Exception as exc:
                        logger.info("[PeerService] peer %s failed: %s", sym, exc)
            except FuturesTimeout:
                logger.info("[PeerService] global timeout while fetching peers for %s", symbol)

        results: list[dict[str, Any]] = [results_by_symbol[s] for s in all_symbols]

        payload = {
            "subject_symbol": symbol,
            "peers": results,
        }
        has_any_metric = any(_has_peer_metrics(row) for row in results if isinstance(row, dict))
        return payload if has_any_metric else None
    except Exception as exc:
        logger.info("[PeerService] fetch_peer_comparison failed for %s: %s", symbol, exc)
        return None
