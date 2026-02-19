# -*- coding: utf-8 -*-
"""
Dashboard scorer implementations.

This module hosts lightweight scorer classes that generate dashboard
InsightCard payloads from pre-fetched data via a single LLM call, with
deterministic fallback when LLM is unavailable.

Compatibility:
- Keep legacy `*Digest` names as aliases.
- Keep `AGENT_NAME` values unchanged because downstream cache keys and API
  payloads rely on these identifiers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from backend.dashboard.insights_prompts import (
    build_financial_prompt,
    build_news_prompt,
    build_overview_prompt,
    build_peers_prompt,
    build_technical_prompt,
)
from backend.dashboard.insights_scorer import (
    clamp_score,
    metrics_financial,
    metrics_news,
    metrics_overview,
    metrics_peers,
    metrics_technical,
    score_financial,
    score_financial_details,
    score_news,
    score_news_details,
    score_overview,
    score_overview_details,
    score_peers,
    score_peers_details,
    score_technical,
    score_technical_details,
)
from backend.dashboard.schemas import InsightCard

logger = logging.getLogger(__name__)


_DIGEST_TIMEOUT_SECONDS = float(os.getenv("INSIGHTS_DIGEST_TIMEOUT", "5"))


# ---------------------------------------------------------------------------
# LLM singleton (lazy init)
# ---------------------------------------------------------------------------

_llm_instance = None
_llm_init_attempted = False


def _get_llm():
    """Lazy-init LLM instance for dashboard scorers."""
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
        logger.info("[Insights] LLM initialized for dashboard scorers")
        return _llm_instance
    except Exception as exc:
        logger.warning("[Insights] LLM init failed, dashboard scorers will use fallback: %s", exc)
        return None


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


# ---------------------------------------------------------------------------
# DashboardScorer base class
# ---------------------------------------------------------------------------


class DashboardScorer(ABC):
    """
    Lightweight dashboard scorer.

    This component does NOT inherit BaseFinancialAgent and does not perform
    autonomous planning, tool orchestration, or reflection loops.
    The legacy class name `DigestAgent` is retained as an alias for backward
    compatibility with existing imports. Identifiers such as
    InsightCard.agent_name / AGENT_NAME and related cache mappings are stable.

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

    def _deterministic_fallback_details(
        self, data: dict[str, Any],
    ) -> tuple[float, str, list[str], list[dict[str, Any]]]:
        score, label, points = self._deterministic_fallback(data)
        return score, label, points, []

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
        self, raw: str, data: dict[str, Any], now_iso: str,
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
        fallback_score, fallback_label, fallback_points, fallback_breakdown = self._deterministic_fallback_details(data)

        # If LLM score diverges too much from deterministic, average them
        if abs(score - fallback_score) > 3.0:
            score = clamp_score((score + fallback_score) / 2)

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
            score_label=str(parsed.get("score_label", fallback_label or _label_from_score(score))),
            summary=str(parsed.get("summary", ""))[:800],
            key_points=(_ensure_str_list(parsed.get("key_points", []))[:5] or fallback_points[:5]),
            risks=_ensure_str_list(parsed.get("risks", []))[:3],
            key_metrics=key_metrics if key_metrics else None,
            score_breakdown=fallback_breakdown,
            confidence=0.8,
            as_of=now_iso,
            model_generated=True,
        )

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        """Override in subclass to provide deterministic key_metrics."""
        return None

    def _make_fallback_card(self, data: dict[str, Any], now_iso: str) -> InsightCard:
        """Generate card from deterministic scoring."""
        score, label, points, breakdown = self._deterministic_fallback_details(data)
        return InsightCard(
            agent_name=self.AGENT_NAME,
            tab=self.TAB,
            score=score,
            score_label=label,
            summary="",
            key_points=points,
            risks=[],
            key_metrics=self._extract_fallback_metrics(data),
            score_breakdown=breakdown,
            confidence=0.4,
            as_of=now_iso,
            model_generated=False,
        )


# ---------------------------------------------------------------------------
# Concrete dashboard scorers
# ---------------------------------------------------------------------------


class TechnicalScorer(DashboardScorer):
    AGENT_NAME = "technical_digest"
    TAB = "technical"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_technical_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_technical(data)

    def _deterministic_fallback_details(
        self, data: dict[str, Any],
    ) -> tuple[float, str, list[str], list[dict[str, Any]]]:
        return score_technical_details(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_technical(data) or None


class FinancialScorer(DashboardScorer):
    AGENT_NAME = "financial_digest"
    TAB = "financial"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_financial_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_financial(data)

    def _deterministic_fallback_details(
        self, data: dict[str, Any],
    ) -> tuple[float, str, list[str], list[dict[str, Any]]]:
        return score_financial_details(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_financial(data) or None


class NewsScorer(DashboardScorer):
    AGENT_NAME = "news_digest"
    TAB = "news"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_news_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_news(data)

    def _deterministic_fallback_details(
        self, data: dict[str, Any],
    ) -> tuple[float, str, list[str], list[dict[str, Any]]]:
        return score_news_details(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_news(data) or None


class PeersScorer(DashboardScorer):
    AGENT_NAME = "peers_digest"
    TAB = "peers"

    def _build_prompt(self, ticker: str, data: dict[str, Any]) -> str:
        return build_peers_prompt(ticker, data)

    def _deterministic_fallback(self, data: dict[str, Any]) -> tuple[float, str, list[str]]:
        return score_peers(data)

    def _deterministic_fallback_details(
        self, data: dict[str, Any],
    ) -> tuple[float, str, list[str], list[dict[str, Any]]]:
        return score_peers_details(data)

    def _extract_fallback_metrics(self, data: dict[str, Any]) -> list[dict[str, str]] | None:
        return metrics_peers(data) or None


class OverviewScorer(DashboardScorer):
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

    def _deterministic_fallback_details(
        self, data: dict[str, Any],
    ) -> tuple[float, str, list[str], list[dict[str, Any]]]:
        return score_overview_details(
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
# Backward-compatible aliases
# ---------------------------------------------------------------------------

DigestAgent = DashboardScorer
TechnicalDigest = TechnicalScorer
FinancialDigest = FinancialScorer
NewsDigest = NewsScorer
PeersDigest = PeersScorer
OverviewDigest = OverviewScorer


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
    # Internal helpers reused by orchestration/tests
    "_DIGEST_TIMEOUT_SECONDS",
    "_get_llm",
    "_label_from_score",
    "_ensure_str_list",
]

