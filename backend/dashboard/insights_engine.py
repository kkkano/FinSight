"""
Dashboard Insights Engine — Lightweight Digest Agents.

Provides AI-powered analysis cards for each Dashboard tab.
Each DigestAgent takes pre-fetched API data and produces a structured
InsightCard via a single LLM call (target latency: 1-3s per agent).

Architecture:
    - DigestAgent (ABC): base class with digest() method
    - 5 concrete agents: Technical / Financial / News / Peers / Overview
    - InsightsOrchestrator: parallel execution + caching + fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from backend.dashboard.cache import dashboard_cache, DashboardCache
from backend.dashboard.insights_prompts import (
    build_financial_prompt,
    build_news_prompt,
    build_overview_prompt,
    build_peers_prompt,
    build_technical_prompt,
)
from backend.dashboard.insights_scorer import (
    clamp_score,
    score_financial,
    score_news,
    score_overview,
    score_peers,
    score_technical,
    metrics_financial,
    metrics_news,
    metrics_overview,
    metrics_peers,
    metrics_technical,
)
from backend.dashboard.schemas import DashboardInsightsResponse, InsightCard

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_INSIGHTS_ENABLED = os.getenv("INSIGHTS_ENABLED", "true").lower() in ("true", "1", "yes")
_DIGEST_TIMEOUT_SECONDS = float(os.getenv("INSIGHTS_DIGEST_TIMEOUT", "5"))
_OVERALL_TIMEOUT_SECONDS = float(os.getenv("INSIGHTS_OVERALL_TIMEOUT", "8"))
_MAX_CONCURRENT_SYMBOLS = int(os.getenv("INSIGHTS_MAX_CONCURRENT_SYMBOLS", "3"))

# Semaphore to limit concurrent symbol insight generation
_generation_semaphore: asyncio.Semaphore | None = None
# Background refresh tasks by symbol (dedupe stale-triggered refreshes)
_refresh_tasks: dict[str, asyncio.Task[None]] = {}


def _get_semaphore() -> asyncio.Semaphore:
    global _generation_semaphore
    if _generation_semaphore is None:
        _generation_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SYMBOLS)
    return _generation_semaphore


# ---------------------------------------------------------------------------
# LLM singleton (lazy init)
# ---------------------------------------------------------------------------

_llm_instance = None
_llm_init_attempted = False


def _get_llm():
    """Lazy-init LLM instance for digest agents."""
    global _llm_instance, _llm_init_attempted
    if _llm_instance is not None:
        return _llm_instance
    if _llm_init_attempted:
        return None
    _llm_init_attempted = True
    try:
        from backend.llm_config import create_llm

        _llm_instance = create_llm(
            temperature=0.2,
            max_tokens=1024,
            request_timeout=8,
        )
        logger.info("[Insights] LLM initialized for digest agents")
        return _llm_instance
    except Exception as exc:
        logger.warning("[Insights] LLM init failed, digest agents will use fallback: %s", exc)
        return None


# ---------------------------------------------------------------------------
# DigestAgent base class
# ---------------------------------------------------------------------------

class DigestAgent(ABC):
    """
    Lightweight digest agent — does NOT inherit BaseFinancialAgent.

    Each subclass implements:
      - _build_prompt(): construct LLM prompt from pre-fetched data
      - _deterministic_fallback(): rule-based scoring when LLM unavailable
    """

    AGENT_NAME: str = "base_digest"
    TAB: str = "overview"

    @abstractmethod
    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        """Build LLM prompt from dashboard data."""

    @abstractmethod
    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        """
        Deterministic fallback: (score, label, key_points).

        Called when LLM is unavailable or times out.
        """

    async def digest(self, ticker: str, data: dict[str, Any]) -> InsightCard:
        """
        Run a single LLM analysis call, falling back to deterministic scoring.

        Returns an InsightCard regardless of LLM availability.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        llm = _get_llm()
        if llm is None:
            return self._make_fallback_card(data, now_iso)

        try:
            prompt = self._build_prompt(ticker, data)
            response = await asyncio.wait_for(
                self._call_llm(llm, prompt),
                timeout=_DIGEST_TIMEOUT_SECONDS,
            )
            return self._parse_response(response, data, now_iso)
        except asyncio.TimeoutError:
            logger.warning("[Insights] %s timed out for %s", self.AGENT_NAME, ticker)
            return self._make_fallback_card(data, now_iso)
        except Exception as exc:
            logger.warning("[Insights] %s failed for %s: %s", self.AGENT_NAME, ticker, exc)
            return self._make_fallback_card(data, now_iso)

    async def _call_llm(self, llm: Any, prompt: str) -> str:
        """Invoke LLM and return raw text response."""
        result = await llm.ainvoke(prompt)
        # LangChain ChatOpenAI returns AIMessage
        if hasattr(result, "content"):
            return str(result.content)
        return str(result)

    def _parse_response(
        self, raw: str, data: dict[str, Any], now_iso: str
    ) -> InsightCard:
        """Parse LLM JSON response into InsightCard, with fallback."""
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("[Insights] %s JSON parse failed, using fallback", self.AGENT_NAME)
            return self._make_fallback_card(data, now_iso)

        # Validate and clamp
        score = clamp_score(float(parsed.get("score", 5.0)))
        fallback_score, _, _ = self._deterministic_fallback(data)

        # If LLM score diverges too much from deterministic, average them
        if abs(score - fallback_score) > 3.0:
            score = clamp_score((score + fallback_score) / 2)

        # 提取 key_metrics（LLM 生成的结构化指标）
        raw_metrics = parsed.get("key_metrics")
        key_metrics: list[dict[str, str]] | None = None
        if isinstance(raw_metrics, list):
            key_metrics = [
                {"label": str(m.get("label", "")), "value": str(m.get("value", ""))}
                for m in raw_metrics
                if isinstance(m, dict) and m.get("label") and m.get("value")
            ][:4]

        return InsightCard(
            agent_name=self.AGENT_NAME,
            tab=self.TAB,
            score=score,
            score_label=str(parsed.get("score_label", _label_from_score(score))),
            summary=str(parsed.get("summary", ""))[:800],
            key_points=_ensure_str_list(parsed.get("key_points", []))[:5],
            risks=_ensure_str_list(parsed.get("risks", []))[:3],
            key_metrics=key_metrics if key_metrics else None,
            confidence=0.8,
            as_of=now_iso,
            model_generated=True,
        )

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        """Override in subclass to provide deterministic key_metrics."""
        return None

    def _make_fallback_card(self, data: dict[str, Any], now_iso: str) -> InsightCard:
        """Generate card from deterministic scoring."""
        score, label, points = self._deterministic_fallback(data)
        return InsightCard(
            agent_name=self.AGENT_NAME,
            tab=self.TAB,
            score=score,
            score_label=label,
            summary="",
            key_points=points,
            risks=[],
            key_metrics=self._extract_fallback_metrics(data),
            confidence=0.4,
            as_of=now_iso,
            model_generated=False,
        )


# ---------------------------------------------------------------------------
# Concrete Digest Agents
# ---------------------------------------------------------------------------

class TechnicalDigest(DigestAgent):
    AGENT_NAME = "technical_digest"
    TAB = "technical"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_technical_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_technical(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_technical(data) or None


class FinancialDigest(DigestAgent):
    AGENT_NAME = "financial_digest"
    TAB = "financial"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_financial_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_financial(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_financial(data) or None


class NewsDigest(DigestAgent):
    AGENT_NAME = "news_digest"
    TAB = "news"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_news_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_news(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_news(data) or None


class PeersDigest(DigestAgent):
    AGENT_NAME = "peers_digest"
    TAB = "peers"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_peers_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_peers(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_peers(data) or None


class OverviewDigest(DigestAgent):
    AGENT_NAME = "overview_digest"
    TAB = "overview"

    def __init__(self) -> None:
        self._sub_scores: dict[str, float] = {}

    def set_sub_scores(self, sub_scores: dict[str, float]) -> None:
        """Set dimension sub-scores before calling digest()."""
        self._sub_scores = sub_scores

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_overview_prompt(ticker, data, sub_scores=self._sub_scores)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_overview(
            tech_score=self._sub_scores.get("technical", 5.0),
            fin_score=self._sub_scores.get("financial", 5.0),
            news_score=self._sub_scores.get("news", 5.0),
            peers_score=self._sub_scores.get("peers", 5.0),
        )

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_overview(self._sub_scores) or None

    def _make_fallback_card(self, data: dict[str, Any], now_iso: str) -> InsightCard:
        card = super()._make_fallback_card(data, now_iso)
        # Attach sub_scores to overview card
        return InsightCard(
            **{**card.model_dump(), "sub_scores": dict(self._sub_scores)}
        )


# ---------------------------------------------------------------------------
# InsightsOrchestrator
# ---------------------------------------------------------------------------

class InsightsOrchestrator:
    """
    Orchestrate parallel digest agent execution with caching.

    Usage::

        orchestrator = InsightsOrchestrator()
        response = await orchestrator.generate("AAPL")
    """

    def __init__(self, cache: DashboardCache | None = None) -> None:
        self._cache = cache or dashboard_cache
        self._technical = TechnicalDigest()
        self._financial = FinancialDigest()
        self._news = NewsDigest()
        self._peers = PeersDigest()
        self._overview = OverviewDigest()

    async def generate(
        self,
        symbol: str,
        *,
        force: bool = False,
    ) -> DashboardInsightsResponse:
        """
        Generate insights for a symbol.

        1. Check cache (stale-while-revalidate)
        2. If fresh → return immediately
        3. If stale → return stale, schedule background refresh
        4. If miss → generate and return
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

                response = DashboardInsightsResponse(
                    symbol=sym_upper,
                    insights=insights_dict,
                    generated_at=cache_generated_at,
                    cached=True,
                    cache_age_seconds=cache_age,
                )

                if is_stale:
                    # Schedule deduplicated background refresh
                    self._schedule_background_refresh(sym_upper)

                return response

        # Generate fresh insights
        return await self._generate_fresh(sym_upper)

    async def _generate_fresh(self, symbol: str) -> DashboardInsightsResponse:
        """Run all digest agents in parallel."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Acquire semaphore to limit concurrent generations
        semaphore = _get_semaphore()
        async with semaphore:
            # Gather pre-fetched dashboard data from cache
            data = self._collect_dashboard_data(symbol)

            # Phase 1: Run the 4 dimension agents in parallel
            tech_task = self._technical.digest(symbol, data.get("technicals", {}))
            fin_task = self._financial.digest(symbol, {
                **(data.get("financials", {}) or {}),
                "valuation": data.get("valuation", {}),
            })
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
                    data.get("technicals", {}), now_iso
                )
                fin_card = self._financial._make_fallback_card(
                    {**(data.get("financials", {}) or {}), "valuation": data.get("valuation", {})},
                    now_iso,
                )
                news_card = self._news._make_fallback_card(data.get("news", {}), now_iso)
                peers_card = self._peers._make_fallback_card(data.get("peers", {}), now_iso)

            # Phase 2: Overview uses sub-scores from phase 1
            self._overview.set_sub_scores({
                "technical": tech_card.score,
                "financial": fin_card.score,
                "news": news_card.score,
                "peers": peers_card.score,
            })
            overview_data = {
                "valuation": data.get("valuation", {}),
                "technicals": data.get("technicals", {}),
                "news_summary": f"{news_card.score_label}",
            }
            try:
                overview_card = await asyncio.wait_for(
                    self._overview.digest(symbol, overview_data),
                    timeout=_DIGEST_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, Exception):
                overview_card = self._overview._make_fallback_card(overview_data, now_iso)

            # Attach sub_scores to overview
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

            # Cache the results
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
            if cached is not None:
                result[data_type] = cached
            else:
                result[data_type] = {}
        return result


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

def _label_from_score(score: float) -> str:
    if score >= 8:
        return "强势"
    if score >= 6.5:
        return "偏多"
    if score >= 4.5:
        return "中性"
    if score >= 3:
        return "偏空"
    return "弱势"


def _ensure_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


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
