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
                if sector_lower and key.lower() in sector_lower or sector_lower in key.lower():
                    candidates = syms
                    break
        peers = [s for s in candidates if s.upper() != symbol.upper()][:limit]

    return peers[:limit]


def _fetch_single_peer_metrics(sym: str) -> dict[str, Any]:
    """Fetch valuation metrics for a single symbol via yfinance."""
    try:
        import yfinance as yf

        info = yf.Ticker(sym).info or {}
        return {
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
    except Exception as exc:
        logger.info("[PeerService] metrics fetch failed for %s: %s", sym, exc)
        return {"symbol": sym, "name": sym}


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
                for future in as_completed(futures, timeout=12):
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

        return {
            "subject_symbol": symbol,
            "peers": results,
        }
    except Exception as exc:
        logger.info("[PeerService] fetch_peer_comparison failed for %s: %s", symbol, exc)
        return None
