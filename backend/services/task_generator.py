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
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.utils.quote import safe_float

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────


class AITask(BaseModel):
    """A single actionable task card shown in the Workbench."""

    id: str
    title: str
    category: Literal[
        "reanalyze",
        "review",
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
    action_url: str = "/workbench"
    execution_params: dict | None = None
    status: Literal["pending", "done", "expired"] = "pending"
    expires_at: str | None = None
    report_id: str | None = None
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
        expires_at = self._task_expiry_iso()

        for pos in ctx.portfolio:
            ticker = str(pos.get("ticker", "")).strip().upper()
            if not ticker:
                continue

            snap = ctx.snapshots.get(ticker, {})
            report = ctx.recent_reports.get(ticker, {})

            # Rule 1: Price anomaly (daily drop exceeds threshold)
            self._check_price_anomaly(tasks, ticker, snap, expires_at=expires_at)

            # Rule 2: Stale report (older than threshold days)
            self._check_stale_report(tasks, ticker, report, expires_at=expires_at)

            # Rule 3: No report at all for a held position
            self._check_missing_report(tasks, ticker, report, expires_at=expires_at)

            # Rule 3b: Fresh report available (show as done/readable item)
            self._check_recent_report(tasks, ticker, report, expires_at=expires_at)

        # Rule 4: Portfolio concentration check
        self._check_concentration(
            tasks,
            ctx.portfolio,
            ctx.snapshots,
            expires_at=expires_at,
        )

        # Rule 5: Market news scan (always present)
        tasks.append(
            AITask(
                id=self._hash("market_news"),
                title="\u5e02\u573a\u65b0\u95fb\u901f\u89c8",
                category="news",
                priority=4,
                reason="\u67e5\u770b\u6700\u65b0\u5e02\u573a\u52a8\u6001",
                icon="newspaper",
                action_url="/dashboard",
                expires_at=expires_at,
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
                    action_url="/workbench",
                    execution_params={
                        "query": "\u5206\u6790\u6211\u7684\u6301\u4ed3\u662f\u5426\u9700\u8981\u518d\u5e73\u8861",
                        "output_mode": "chat",
                    },
                    expires_at=expires_at,
                    source="rule",
                )
            )

        return tasks

    # ── Individual rule helpers ──────────────────────────────

    def _check_price_anomaly(
        self, tasks: list[AITask], ticker: str, snap: dict, *, expires_at: str
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
                    action_url=f"/chat?query=\u5206\u6790%20{ticker}%20\u4ef7\u683c\u5f02\u52a8\u539f\u56e0",
                    execution_params={
                        "query": f"\u5206\u6790 {ticker} \u4ef7\u683c\u5f02\u52a8\u539f\u56e0",
                        "tickers": [ticker],
                        "output_mode": "brief",
                    },
                    expires_at=expires_at,
                    source="rule",
                )
            )

    def _check_stale_report(
        self, tasks: list[AITask], ticker: str, report: dict, *, expires_at: str
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
                    action_url=f"/chat?query=\u91cd\u65b0\u5206\u6790%20{ticker}%20\u6700\u65b0\u60c5\u51b5",
                    execution_params={
                        "query": f"\u91cd\u65b0\u5206\u6790 {ticker} \u6700\u65b0\u60c5\u51b5",
                        "tickers": [ticker],
                        "output_mode": "brief",
                    },
                    expires_at=expires_at,
                    source="rule",
                )
            )

    def _check_missing_report(
        self, tasks: list[AITask], ticker: str, report: dict, *, expires_at: str
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
                    action_url=f"/chat?query=\u6df1\u5ea6\u5206\u6790%20{ticker}",
                    execution_params={
                        "query": f"\u6df1\u5ea6\u5206\u6790 {ticker}",
                        "tickers": [ticker],
                        "output_mode": "investment_report",
                    },
                    expires_at=expires_at,
                    source="rule",
                )
            )

    def _check_recent_report(
        self, tasks: list[AITask], ticker: str, report: dict, *, expires_at: str
    ) -> None:
        report_id = str(report.get("report_id", "")).strip()
        if not report_id:
            return
        report_age_days = report.get("age_days")
        if isinstance(report_age_days, (int, float)) and report_age_days > _REPORT_STALE_DAYS:
            return
        tasks.append(
            AITask(
                id=self._hash(f"review:{ticker}:{report_id}"),
                title=f"\u67e5\u770b {ticker} \u6700\u65b0\u62a5\u544a",
                category="review",
                priority=4,
                reason="\u5f53\u65e5\u6709\u6548\u62a5\u544a\u53ef\u76f4\u63a5\u56de\u653e",
                icon="file-text",
                action_url=f"/chat?report_id={report_id}",
                execution_params=None,
                status="done",
                report_id=report_id,
                expires_at=expires_at,
                source="rule",
            )
        )

    def _check_concentration(
        self,
        tasks: list[AITask],
        portfolio: list[dict],
        snapshots: dict[str, dict],
        *,
        expires_at: str,
    ) -> None:
        if len(portfolio) < 2:
            return

        position_values: dict[str, float] = {}
        estimated_by_cost: list[str] = []

        for pos in portfolio:
            ticker = str(pos.get("ticker", "")).strip().upper()
            shares = safe_float(pos.get("shares")) or 0.0
            if not ticker or shares <= 0:
                continue

            snapshot = snapshots.get(ticker, {})
            price = (
                safe_float(snapshot.get("price"))
                or safe_float(snapshot.get("close"))
                or safe_float(pos.get("avg_cost"))
            )
            if price is None or price <= 0:
                continue
            if safe_float(snapshot.get("price")) is None and safe_float(snapshot.get("close")) is None:
                estimated_by_cost.append(ticker)

            position_values[ticker] = shares * price

        total_value = sum(position_values.values())
        if total_value <= 0:
            return

        for ticker, value in position_values.items():
            weight = value / total_value * 100
            if weight > _CONCENTRATION_LIMIT_PCT:
                estimate_note = ""
                if estimated_by_cost:
                    estimated = "、".join(sorted(set(estimated_by_cost)))
                    estimate_note = f"（部分标的按成本价估算：{estimated}）"
                tasks.append(
                    AITask(
                        id=self._hash("concentration"),
                        title="\u6301\u4ed3\u96c6\u4e2d\u5ea6\u9884\u8b66",
                        category="risk",
                        priority=1,
                        reason=(
                            f"{ticker} \u5360\u6bd4 {weight:.0f}%\uff0c"
                            f"\u5efa\u8bae\u5206\u6563\u6295\u8d44{estimate_note}"
                        ),
                        icon="shield-alert",
                        action_url="/chat?query=\u5206\u6790\u6211\u7684\u6301\u4ed3\u98ce\u9669\u655e\u53e3",
                        execution_params={
                            "query": "\u5206\u6790\u6211\u7684\u6301\u4ed3\u98ce\u9669\u655e\u53e3",
                            "output_mode": "chat",
                        },
                        expires_at=expires_at,
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
        """Deterministic short hash for per-day task ID stability."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        material = f"{day}:{seed}"
        return hashlib.md5(material.encode()).hexdigest()[:12]

    @staticmethod
    def _task_expiry_iso() -> str:
        now = datetime.now(timezone.utc)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        return end_of_day.isoformat()


__all__ = ["AITask", "TaskContext", "TaskGenerator"]
