# -*- coding: utf-8 -*-
"""
Dashboard Insights Engine - Orchestration layer for dashboard scorers.

Responsibilities:
- Orchestrate parallel scorer execution with cache strategy.
- Keep external import compatibility (`insights_engine` as stable entrypoint).
- Re-export scorer symbols (new and legacy names) during migration window.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from backend.dashboard import scorers as scorer_runtime
from backend.dashboard.cache import DashboardCache, dashboard_cache
from backend.dashboard.scorers import (
    DashboardScorer,
    DigestAgent,
    FinancialDigest,
    FinancialScorer,
    NewsDigest,
    NewsScorer,
    OverviewDigest,
    OverviewScorer,
    PeersDigest,
    PeersScorer,
    TechnicalDigest,
    TechnicalScorer,
)
from backend.dashboard.schemas import DashboardInsightsResponse, InsightCard

logger = logging.getLogger(__name__)
_DASHBOARD_FAILURE_MARKER = "__dashboard_failure__"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_INSIGHTS_ENABLED = os.getenv("INSIGHTS_ENABLED", "true").lower() in ("true", "1", "yes")
_OVERALL_TIMEOUT_SECONDS = float(os.getenv("INSIGHTS_OVERALL_TIMEOUT", "8"))
_MAX_CONCURRENT_SYMBOLS = int(os.getenv("INSIGHTS_MAX_CONCURRENT_SYMBOLS", "3"))

# Backward-compatible aliases for tests/utilities that import from this module.
_DIGEST_TIMEOUT_SECONDS = scorer_runtime._DIGEST_TIMEOUT_SECONDS
_get_llm = scorer_runtime._get_llm
_label_from_score = scorer_runtime._label_from_score
_ensure_str_list = scorer_runtime._ensure_str_list

# Semaphore to limit concurrent symbol insight generation.
_generation_semaphore: asyncio.Semaphore | None = None
# Background refresh tasks by symbol (dedupe stale-triggered refreshes).
_refresh_tasks: dict[str, asyncio.Task[None]] = {}


def _get_semaphore() -> asyncio.Semaphore:
    global _generation_semaphore
    if _generation_semaphore is None:
        _generation_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SYMBOLS)
    return _generation_semaphore


# ---------------------------------------------------------------------------
# InsightsOrchestrator
# ---------------------------------------------------------------------------


class InsightsOrchestrator:
    """
    Orchestrate parallel dashboard scorer execution with caching.

    Usage::

        orchestrator = InsightsOrchestrator()
        response = await orchestrator.generate("AAPL")
    """

    def __init__(self, cache: DashboardCache | None = None) -> None:
        self._cache = cache or dashboard_cache
        self._technical = TechnicalScorer()
        self._financial = FinancialScorer()
        self._news = NewsScorer()
        self._peers = PeersScorer()
        self._overview = OverviewScorer()

    async def generate(
        self,
        symbol: str,
        *,
        force: bool = False,
    ) -> DashboardInsightsResponse:
        """
        Generate insights for a symbol.

        1. Check cache (stale-while-revalidate)
        2. If fresh -> return immediately
        3. If stale -> return stale, schedule background refresh
        4. If miss -> generate and return
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        sym_upper = symbol.upper()

        if not _INSIGHTS_ENABLED:
            return DashboardInsightsResponse(
                symbol=sym_upper,
                insights={},
                generated_at=now_iso,
                cached=False,
                cache_age_seconds=0,
            )

        if not force:
            cached_data, is_stale = self._cache.get_with_stale(
                sym_upper,
                "insights",
                stale_ttl=self._cache.TTL_INSIGHTS_STALE,
            )
            if cached_data is not None and isinstance(cached_data, dict):
                cache_generated_at = cached_data.get("generated_at", "")
                cache_age = _compute_cache_age(cache_generated_at)
                insights_dict = _deserialize_insights(cached_data.get("insights", {}))
                if self._cached_insights_need_refresh(sym_upper, insights_dict):
                    logger.info(
                        "[Insights] cached news fallback stale for %s; regenerate from refreshed dashboard data",
                        sym_upper,
                    )
                    return await self._generate_fresh(sym_upper)

                response = DashboardInsightsResponse(
                    symbol=sym_upper,
                    insights=insights_dict,
                    generated_at=cache_generated_at,
                    cached=True,
                    cache_age_seconds=cache_age,
                )

                if is_stale:
                    # Schedule deduplicated background refresh.
                    self._schedule_background_refresh(sym_upper)

                return response

        # Generate fresh insights.
        return await self._generate_fresh(sym_upper)

    async def _generate_fresh(self, symbol: str) -> DashboardInsightsResponse:
        """Run all dashboard scorers in parallel."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Acquire semaphore to limit concurrent generations.
        semaphore = _get_semaphore()
        async with semaphore:
            # Gather pre-fetched dashboard data from cache.
            data = self._collect_dashboard_data(symbol)
            data = await self._hydrate_missing_data(symbol, data)

            # Phase 1: run the 4 dimension scorers in parallel.
            tech_task = self._technical.digest(symbol, data.get("technicals", {}))
            fin_task = self._financial.digest(
                symbol,
                {
                    **(data.get("financials", {}) or {}),
                    "valuation": data.get("valuation", {}),
                },
            )
            news_task = self._news.digest(symbol, data.get("news", {}))
            peers_task = self._peers.digest(symbol, data.get("peers", {}))

            try:
                tech_card, fin_card, news_card, peers_card = await asyncio.wait_for(
                    asyncio.gather(tech_task, fin_task, news_task, peers_task),
                    timeout=_OVERALL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning("[Insights] Overall timeout for %s, using fallbacks", symbol)
                tech_card = self._technical._make_fallback_card(
                    data.get("technicals", {}),
                    now_iso,
                )
                fin_card = self._financial._make_fallback_card(
                    {
                        **(data.get("financials", {}) or {}),
                        "valuation": data.get("valuation", {}),
                    },
                    now_iso,
                )
                news_card = self._news._make_fallback_card(data.get("news", {}), now_iso)
                peers_card = self._peers._make_fallback_card(data.get("peers", {}), now_iso)

            # Phase 2: overview uses phase-1 sub-scores.
            self._overview.set_sub_scores(
                {
                    "technical": tech_card.score,
                    "financial": fin_card.score,
                    "news": news_card.score,
                    "peers": peers_card.score,
                }
            )
            overview_data = {
                "valuation": data.get("valuation", {}),
                "technicals": data.get("technicals", {}),
                "news_summary": f"{news_card.score_label}",
            }
            try:
                overview_card = await asyncio.wait_for(
                    self._overview.digest(symbol, overview_data),
                    timeout=scorer_runtime._DIGEST_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, Exception):
                overview_card = self._overview._make_fallback_card(overview_data, now_iso)

            # Attach sub_scores to overview if not present.
            if overview_card.sub_scores is None:
                overview_card = InsightCard(
                    **{
                        **overview_card.model_dump(),
                        "sub_scores": {
                            "technical": tech_card.score,
                            "financial": fin_card.score,
                            "news": news_card.score,
                            "peers": peers_card.score,
                        },
                    }
                )

            insights = {
                "overview": overview_card,
                "financial": fin_card,
                "technical": tech_card,
                "news": news_card,
                "peers": peers_card,
            }

            # Cache the results.
            self._cache.set(
                symbol,
                "insights",
                {
                    "insights": {k: v.model_dump() for k, v in insights.items()},
                    "generated_at": now_iso,
                },
                ttl=self._cache.TTL_INSIGHTS,
            )

            return DashboardInsightsResponse(
                symbol=symbol,
                insights=insights,
                generated_at=now_iso,
                cached=False,
                cache_age_seconds=0,
            )

    async def _refresh_in_background(self, symbol: str) -> None:
        """Background cache refresh (fire-and-forget)."""
        try:
            await self._generate_fresh(symbol)
            logger.info("[Insights] Background refresh completed for %s", symbol)
        except Exception as exc:
            logger.warning("[Insights] Background refresh failed for %s: %s", symbol, exc)
        finally:
            _refresh_tasks.pop(symbol, None)

    def _schedule_background_refresh(self, symbol: str) -> None:
        """Schedule one background refresh per symbol at a time."""
        existing = _refresh_tasks.get(symbol)
        if existing is not None and not existing.done():
            return
        _refresh_tasks[symbol] = asyncio.create_task(self._refresh_in_background(symbol))

    def _collect_dashboard_data(self, symbol: str) -> dict[str, Any]:
        """
        Gather pre-fetched dashboard data from DashboardCache.

        These are the same data that GET /api/dashboard already fetched
        and cached (snapshot, valuation, financials, technicals, news, peers).
        """
        result: dict[str, Any] = {}
        for data_type in ("snapshot", "valuation", "financials", "technicals", "news", "peers"):
            cached = self._cache.get(symbol, data_type)
            if _is_failure_marker(cached):
                result[data_type] = {}
            elif cached is not None:
                result[data_type] = cached
            else:
                result[data_type] = {}
        return result

    async def _hydrate_missing_data(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Best-effort hydration when insights are requested before dashboard cache is warm.

        This prevents mismatch such as:
          - News tab list has data (from /api/dashboard)
          - AI news card still shows "暂无近期新闻数据" (from stale /api/dashboard/insights)
        """
        hydrated = dict(data)
        tasks: list[tuple[str, asyncio.Task[Any]]] = []

        if _is_empty_mapping(hydrated.get("technicals")):
            tasks.append(
                (
                    "technicals",
                    asyncio.create_task(
                        self._run_fetch_with_timeout(
                            "fetch_technical_indicators",
                            self._fetch_technicals,
                            symbol,
                            timeout=6.0,
                        )
                    ),
                )
            )

        if _count_news_items(hydrated.get("news")) == 0:
            tasks.append(
                (
                    "news",
                    asyncio.create_task(
                        self._run_fetch_with_timeout(
                            "fetch_news",
                            self._fetch_news,
                            symbol,
                            timeout=8.0,
                        )
                    ),
                )
            )

        if not tasks:
            return hydrated

        for key, task in tasks:
            try:
                value = await task
            except Exception:
                value = None
            if key == "technicals" and isinstance(value, dict) and value:
                hydrated["technicals"] = value
                self._cache.set(symbol, "technicals", value, ttl=self._cache.TTL_TECHNICALS)
            if key == "news" and isinstance(value, dict):
                hydrated["news"] = value
                self._cache.set(symbol, "news", value, ttl=self._cache.TTL_NEWS)
        return hydrated

    async def _run_fetch_with_timeout(
        self,
        label: str,
        fn,
        symbol: str,
        *,
        timeout: float,
    ) -> Any:
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, symbol), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("[Insights] %s timeout for %s", label, symbol)
        except Exception as exc:
            logger.warning("[Insights] %s failed for %s: %s", label, symbol, exc)
        return None

    def _fetch_technicals(self, symbol: str) -> dict[str, Any] | None:
        from backend.dashboard.data_service import fetch_technical_indicators

        return fetch_technical_indicators(symbol)

    def _fetch_news(self, symbol: str) -> dict[str, Any] | None:
        from backend.dashboard.data_service import fetch_news

        return fetch_news(symbol, limit=20)

    def _cached_insights_need_refresh(self, symbol: str, insights: dict[str, InsightCard]) -> bool:
        news_card = insights.get("news")
        if news_card is None:
            return False
        if not _news_card_shows_empty_marker(news_card):
            return False
        cached_news = self._cache.get(symbol, "news")
        return _count_news_items(cached_news) > 0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_orchestrator: InsightsOrchestrator | None = None


def get_insights_orchestrator() -> InsightsOrchestrator:
    """Get the module-level InsightsOrchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = InsightsOrchestrator()
    return _orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_cache_age(generated_at: str) -> float:
    """Compute seconds since generated_at ISO timestamp."""
    if not generated_at:
        return 0
    try:
        gen_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - gen_dt).total_seconds())
    except (ValueError, TypeError):
        return 0


def _deserialize_insights(raw: dict[str, Any]) -> dict[str, InsightCard]:
    """Deserialize cached insight dicts back to InsightCard models."""
    result: dict[str, InsightCard] = {}
    for tab_name, card_data in raw.items():
        if isinstance(card_data, dict):
            try:
                result[tab_name] = InsightCard(**card_data)
            except Exception:
                logger.warning("[Insights] Failed to deserialize insight for tab=%s", tab_name)
    return result


def _is_empty_mapping(value: Any) -> bool:
    if _is_failure_marker(value):
        return True
    return not isinstance(value, dict) or len(value) == 0


def _is_failure_marker(value: Any) -> bool:
    return isinstance(value, dict) and value.get(_DASHBOARD_FAILURE_MARKER) is True


def _count_news_items(news_payload: Any) -> int:
    if not isinstance(news_payload, dict):
        return 0
    market = news_payload.get("market")
    impact = news_payload.get("impact")
    market_count = len(market) if isinstance(market, list) else 0
    impact_count = len(impact) if isinstance(impact, list) else 0
    return market_count + impact_count


def _news_card_shows_empty_marker(card: InsightCard) -> bool:
    points = card.key_points if isinstance(card.key_points, list) else []
    for point in points:
        if "暂无近期新闻数据" in str(point):
            return True
    return "暂无近期新闻数据" in str(card.summary or "")


__all__ = [
    # Preferred names
    "DashboardScorer",
    "TechnicalScorer",
    "FinancialScorer",
    "NewsScorer",
    "PeersScorer",
    "OverviewScorer",
    # Backward-compatible aliases
    "DigestAgent",
    "TechnicalDigest",
    "FinancialDigest",
    "NewsDigest",
    "PeersDigest",
    "OverviewDigest",
    # Orchestration entrypoints
    "InsightsOrchestrator",
    "get_insights_orchestrator",
    # Backward-compatible helpers used by tests and diagnostics
    "_DIGEST_TIMEOUT_SECONDS",
    "_get_llm",
    "_label_from_score",
    "_ensure_str_list",
    "_compute_cache_age",
    "_deserialize_insights",
]
