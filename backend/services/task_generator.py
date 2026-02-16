# -*- coding: utf-8 -*-
"""AI-powered task generation with rule-based + LLM dual layers.

Dual-layer engine:
  1. Rule layer (deterministic) -- always runs, zero cost.
  2. LLM layer (optional) -- reserved for future enhancement.

The rule layer inspects portfolio positions, snapshot prices, and recent
report metadata to produce prioritised task cards the frontend can render
immediately or pass to ``/api/execute`` for one-click execution.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────


class AITask(BaseModel):
    """A single actionable task card shown in the Workbench."""

    id: str
    title: str
    category: Literal[
        "reanalyze",
        "generate",
        "news",
        "risk",
        "opportunity",
        "rebalance",
        "anomaly",
        "earnings",
    ]
    priority: int = Field(default=3, ge=1, le=5)
    reason: str = ""
    icon: str = "activity"
    execution_params: dict | None = None
    source: Literal["rule", "llm"] = "rule"


class TaskContext(BaseModel):
    """Input context for the task generator."""

    # List of portfolio positions: [{ticker, shares, avg_cost, ...}]
    portfolio: list[dict] = Field(default_factory=list)
    # ticker -> latest report summary: {age_days, report_id, ...}
    recent_reports: dict[str, dict] = Field(default_factory=dict)
    # ticker -> snapshot data: {price, change_pct, volume, ...}
    snapshots: dict[str, dict] = Field(default_factory=dict)


# ── Thresholds ──────────────────────────────────────────────

_PRICE_DROP_THRESHOLD = -3.0  # daily drop > 3%
_REPORT_STALE_DAYS = 3
_CONCENTRATION_LIMIT_PCT = 40.0
_MIN_POSITIONS_FOR_REBALANCE = 3
_MAX_TASKS = 8


# ── Generator ───────────────────────────────────────────────


class TaskGenerator:
    """Dual-layer task generator: rules (deterministic) + LLM (optional)."""

    async def generate(self, context: TaskContext) -> list[AITask]:
        """Run the rule layer and return deduplicated, ranked tasks."""
        rule_tasks = self._rule_based_tasks(context)
        # LLM layer intentionally not called in MVP to reduce cost.
        # When needed: llm_tasks = await self._llm_enhanced_tasks(context, rule_tasks)
        return self._deduplicate_and_rank(rule_tasks, max_tasks=_MAX_TASKS)

    # ── Rule layer ──────────────────────────────────────────

    def _rule_based_tasks(self, ctx: TaskContext) -> list[AITask]:
        tasks: list[AITask] = []

        for pos in ctx.portfolio:
            ticker = str(pos.get("ticker", "")).strip().upper()
            if not ticker:
                continue

            snap = ctx.snapshots.get(ticker, {})
            report = ctx.recent_reports.get(ticker, {})

            # Rule 1: Price anomaly (daily drop exceeds threshold)
            self._check_price_anomaly(tasks, ticker, snap)

            # Rule 2: Stale report (older than threshold days)
            self._check_stale_report(tasks, ticker, report)

            # Rule 3: No report at all for a held position
            self._check_missing_report(tasks, ticker, report)

        # Rule 4: Portfolio concentration check
        self._check_concentration(tasks, ctx.portfolio)

        # Rule 5: Market news scan (always present)
        tasks.append(
            AITask(
                id=self._hash("market_news"),
                title="\u5e02\u573a\u65b0\u95fb\u901f\u89c8",
                category="news",
                priority=4,
                reason="\u67e5\u770b\u6700\u65b0\u5e02\u573a\u52a8\u6001",
                icon="newspaper",
                source="rule",
            )
        )

        # Rule 6: Rebalance suggestion (if portfolio has 3+ positions)
        if len(ctx.portfolio) >= _MIN_POSITIONS_FOR_REBALANCE:
            tasks.append(
                AITask(
                    id=self._hash("rebalance"),
                    title="\u667a\u80fd\u8c03\u4ed3\u5efa\u8bae",
                    category="rebalance",
                    priority=3,
                    reason="\u57fa\u4e8e\u6301\u4ed3\u5206\u6790\u751f\u6210\u8c03\u4ed3\u5efa\u8bae",
                    icon="bar-chart-3",
                    source="rule",
                )
            )

        return tasks

    # ── Individual rule helpers ──────────────────────────────

    def _check_price_anomaly(
        self, tasks: list[AITask], ticker: str, snap: dict
    ) -> None:
        change_pct = snap.get("change_percent")
        if change_pct is None:
            change_pct = snap.get("change_pct")
        if change_pct is not None and change_pct < _PRICE_DROP_THRESHOLD:
            tasks.append(
                AITask(
                    id=self._hash(f"anomaly:{ticker}"),
                    title=f"{ticker} \u4ef7\u683c\u5f02\u52a8\u5206\u6790",
                    category="anomaly",
                    priority=1,
                    reason=f"{ticker} \u65e5\u8dcc\u5e45 {change_pct:.1f}%\uff0c\u5efa\u8bae\u5206\u6790\u539f\u56e0",
                    icon="alert-triangle",
                    execution_params={
                        "query": f"\u5206\u6790 {ticker} \u4ef7\u683c\u5f02\u52a8\u539f\u56e0",
                        "tickers": [ticker],
                        "output_mode": "brief",
                    },
                    source="rule",
                )
            )

    def _check_stale_report(
        self, tasks: list[AITask], ticker: str, report: dict
    ) -> None:
        report_age_days = report.get("age_days")
        if report_age_days is not None and report_age_days > _REPORT_STALE_DAYS:
            tasks.append(
                AITask(
                    id=self._hash(f"reanalyze:{ticker}"),
                    title=f"\u66f4\u65b0 {ticker} \u5206\u6790\u62a5\u544a",
                    category="reanalyze",
                    priority=2,
                    reason=f"\u4e0a\u6b21\u5206\u6790\u8ddd\u4eca {report_age_days} \u5929\uff0c\u5efa\u8bae\u66f4\u65b0",
                    icon="refresh-cw",
                    execution_params={
                        "query": f"\u91cd\u65b0\u5206\u6790 {ticker} \u6700\u65b0\u60c5\u51b5",
                        "tickers": [ticker],
                        "output_mode": "brief",
                    },
                    source="rule",
                )
            )

    def _check_missing_report(
        self, tasks: list[AITask], ticker: str, report: dict
    ) -> None:
        if not report:
            tasks.append(
                AITask(
                    id=self._hash(f"generate:{ticker}"),
                    title=f"\u751f\u6210 {ticker} \u5206\u6790\u62a5\u544a",
                    category="generate",
                    priority=2,
                    reason=f"\u6301\u4ed3 {ticker} \u5c1a\u65e0\u5206\u6790\u62a5\u544a",
                    icon="file-text",
                    execution_params={
                        "query": f"\u6df1\u5ea6\u5206\u6790 {ticker}",
                        "tickers": [ticker],
                        "output_mode": "investment_report",
                    },
                    source="rule",
                )
            )

    def _check_concentration(
        self, tasks: list[AITask], portfolio: list[dict]
    ) -> None:
        if len(portfolio) < 2:
            return

        total_shares = sum(float(p.get("shares", 0)) for p in portfolio)
        if total_shares <= 0:
            return

        for pos in portfolio:
            ticker = str(pos.get("ticker", "")).strip().upper()
            weight = float(pos.get("shares", 0)) / total_shares * 100
            if weight > _CONCENTRATION_LIMIT_PCT:
                tasks.append(
                    AITask(
                        id=self._hash("concentration"),
                        title="\u6301\u4ed3\u96c6\u4e2d\u5ea6\u9884\u8b66",
                        category="risk",
                        priority=1,
                        reason=(
                            f"{ticker} \u5360\u6bd4 {weight:.0f}%\uff0c"
                            "\u5efa\u8bae\u5206\u6563\u6295\u8d44"
                        ),
                        icon="shield-alert",
                        source="rule",
                    )
                )
                # Only one concentration warning needed
                break

    # ── Dedup / rank ────────────────────────────────────────

    def _deduplicate_and_rank(
        self, tasks: list[AITask], max_tasks: int = _MAX_TASKS
    ) -> list[AITask]:
        """Remove duplicate task IDs, sort by priority (1=highest), truncate."""
        seen: set[str] = set()
        unique: list[AITask] = []
        for t in tasks:
            if t.id not in seen:
                seen.add(t.id)
                unique.append(t)
        unique.sort(key=lambda t: t.priority)
        return unique[:max_tasks]

    # ── Utility ─────────────────────────────────────────────

    @staticmethod
    def _hash(seed: str) -> str:
        """Deterministic short hash for task ID stability."""
        return hashlib.md5(seed.encode()).hexdigest()[:12]


__all__ = ["AITask", "TaskContext", "TaskGenerator"]
