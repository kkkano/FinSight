# -*- coding: utf-8 -*-
"""Rebalance suggestion engine (suggestion_only mode).

Four-step pipeline:
  1. Diagnose  -- compute weights, sector distribution, risk flags
  2. Generate  -- rule-based candidate actions
  3. Solve     -- greedy constraint solver (turnover budget, position caps)
  4. Explain   -- template-based Chinese explanations

HC-2: ``executable`` is always ``False``, ``mode`` is always ``suggestion_only``.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any
import inspect

from pydantic import BaseModel, Field

from backend.api.rebalance_schemas import (
    ActionType,
    EvidenceSnapshot,
    ExpectedImpact,
    RebalanceAction,
    RebalanceConstraints,
    RebalanceSuggestion,
    RiskTier,
)

logger = logging.getLogger(__name__)


# ── Context model ───────────────────────────────────────────


class RebalanceContext(BaseModel):
    """Input context for the rebalance engine."""

    session_id: str
    portfolio: list[dict] = Field(default_factory=list)
    risk_tier: RiskTier = RiskTier.MODERATE
    constraints: RebalanceConstraints = Field(default_factory=RebalanceConstraints)
    # ticker -> live price (optional, mock if absent)
    live_prices: dict[str, float] = Field(default_factory=dict)
    # ticker -> sector string (optional)
    sector_map: dict[str, str] = Field(default_factory=dict)
    # when key inputs are missing, switch to diagnosis-only mode
    diagnostics_only: bool = False
    fallback_reasons: list[str] = Field(default_factory=list)
    # optional enhancement switch (fallback to deterministic when unavailable)
    use_llm_enhancement: bool = False


# ── Diagnosis result ────────────────────────────────────────


class _PortfolioDiagnosis(BaseModel):
    """Internal diagnosis produced by step 1."""

    total_value: float = 0.0
    weights: dict[str, float] = Field(default_factory=dict)
    sector_weights: dict[str, float] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)
    position_values: dict[str, float] = Field(default_factory=dict)


# ── Mock price fallback ─────────────────────────────────────

_MOCK_PRICES: dict[str, float] = {
    "AAPL": 185.0,
    "GOOGL": 140.0,
    "MSFT": 420.0,
    "AMZN": 180.0,
    "TSLA": 250.0,
    "NVDA": 800.0,
    "META": 500.0,
    "BRK-B": 410.0,
    "JPM": 195.0,
    "V": 280.0,
}

_DEFAULT_MOCK_PRICE = 100.0


def _get_price(ticker: str, live_prices: dict[str, float]) -> float:
    """Return live price if available, else optional mock price."""
    price = live_prices.get(ticker)
    if price is not None and price > 0:
        return price
    if os.getenv("REBALANCE_USE_MOCK_PRICES", "false").lower() in {"1", "true", "yes", "on"}:
        return _MOCK_PRICES.get(ticker, _DEFAULT_MOCK_PRICE)
    return 0.0


# ── Engine ──────────────────────────────────────────────────


class RebalanceEngine:
    """Four-step rebalance suggestion engine.

    All suggestions are non-executable (HC-2).
    """

    def __init__(self, llm_enhancer: Any | None = None):
        self._llm_enhancer = llm_enhancer

    async def generate(self, ctx: RebalanceContext) -> RebalanceSuggestion:
        """Run the full pipeline and return a RebalanceSuggestion."""
        diagnosis = self._diagnose_portfolio(ctx)
        warnings = self._collect_warnings(diagnosis, ctx)

        if ctx.diagnostics_only:
            solved: list[RebalanceAction] = []
            explanation = self._generate_diagnostics_summary(diagnosis, ctx)
            turnover = 0.0
        else:
            candidates = self._generate_candidates(diagnosis, ctx)
            candidates = await self._maybe_enhance_candidates(candidates, diagnosis, ctx)
            solved = self._solve_constraints(candidates, ctx.constraints)
            explanation = self._generate_explanation(solved, diagnosis, ctx)
            turnover = self._estimate_turnover(solved)

        fallback_reason = "; ".join(ctx.fallback_reasons) if ctx.fallback_reasons else None

        return RebalanceSuggestion(
            suggestion_id=uuid.uuid4().hex[:16],
            mode="suggestion_only",
            executable=False,
            risk_tier=ctx.risk_tier,
            constraints=ctx.constraints,
            summary=explanation,
            actions=solved,
            expected_impact=ExpectedImpact(
                diversification_delta=self._diversification_assessment(diagnosis),
                risk_delta=self._risk_assessment(ctx.risk_tier, diagnosis),
                estimated_turnover_pct=round(turnover, 2),
            ),
            warnings=warnings,
            status="draft",
            created_at=datetime.now(timezone.utc).isoformat(),
            degraded_mode=ctx.diagnostics_only,
            fallback_reason=fallback_reason,
        )

    # ── Step 1: Diagnose ────────────────────────────────────

    def _diagnose_portfolio(self, ctx: RebalanceContext) -> _PortfolioDiagnosis:
        """Compute current weights, sector distribution, risk flags."""
        position_values: dict[str, float] = {}

        for pos in ctx.portfolio:
            ticker = str(pos.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            shares = float(pos.get("shares", 0))
            if shares <= 0:
                continue
            price = _get_price(ticker, ctx.live_prices)
            if price <= 0:
                continue
            position_values[ticker] = shares * price

        total_value = sum(position_values.values())

        # Compute weights
        weights: dict[str, float] = {}
        if total_value > 0:
            weights = {
                t: round(v / total_value * 100, 2)
                for t, v in position_values.items()
            }

        # Compute sector weights
        sector_weights: dict[str, float] = {}
        for ticker, weight in weights.items():
            sector = ctx.sector_map.get(ticker, "Unknown")
            sector_weights[sector] = round(
                sector_weights.get(sector, 0.0) + weight, 2
            )

        # Identify risk flags
        risk_flags: list[str] = []
        for ticker, weight in weights.items():
            if weight > ctx.constraints.max_single_position_pct:
                risk_flags.append(
                    f"{ticker} \u5360\u6bd4 {weight:.1f}% "
                    f"\u8d85\u8fc7\u9650\u5236 {ctx.constraints.max_single_position_pct:.0f}%"
                )

        for sector, sw in sector_weights.items():
            if sw > ctx.constraints.sector_concentration_limit:
                risk_flags.append(
                    f"{sector} \u677f\u5757\u5360\u6bd4 {sw:.1f}% "
                    f"\u8d85\u8fc7\u9650\u5236 {ctx.constraints.sector_concentration_limit:.0f}%"
                )

        if len(position_values) == 1:
            risk_flags.append("\u4ec5\u6301\u6709\u5355\u4e00\u6807\u7684\uff0c\u5206\u6563\u5316\u4e0d\u8db3")
        if not position_values:
            risk_flags.append("缺少有效价格输入，暂无法计算持仓权重。")

        return _PortfolioDiagnosis(
            total_value=round(total_value, 2),
            weights=weights,
            sector_weights=sector_weights,
            risk_flags=risk_flags,
            position_values=position_values,
        )

    def _generate_diagnostics_summary(
        self,
        diag: _PortfolioDiagnosis,
        ctx: RebalanceContext,
    ) -> str:
        reasons = "；".join(ctx.fallback_reasons) if ctx.fallback_reasons else "关键输入不足"
        if diag.risk_flags:
            return (
                f"当前进入仅诊断模式（{reasons}），暂不输出目标仓位。"
                f"已识别风险：{'；'.join(diag.risk_flags)}。"
            )
        return f"当前进入仅诊断模式（{reasons}），暂不输出目标仓位。"

    # ── Step 2: Generate candidates ─────────────────────────

    def _generate_candidates(
        self, diag: _PortfolioDiagnosis, ctx: RebalanceContext
    ) -> list[RebalanceAction]:
        """Produce candidate actions based on diagnosis rules."""
        candidates: list[RebalanceAction] = []
        num_positions = len(diag.weights)
        if num_positions == 0:
            return candidates

        equal_weight = round(100.0 / num_positions, 2)

        for ticker, current_weight in diag.weights.items():
            # Rule: Over-concentration -> REDUCE toward equal weight
            if current_weight > ctx.constraints.max_single_position_pct:
                target = min(equal_weight, ctx.constraints.max_single_position_pct)
                delta = round(target - current_weight, 2)
                evidence = self._build_action_evidence(
                    ticker=ticker,
                    current_weight=current_weight,
                    target_weight=target,
                    trigger=(
                        f"single_position_limit={ctx.constraints.max_single_position_pct:.1f}% "
                        f"breached by current_weight={current_weight:.1f}%"
                    ),
                    ctx=ctx,
                )
                candidates.append(
                    RebalanceAction(
                        ticker=ticker,
                        action=ActionType.REDUCE,
                        current_weight=current_weight,
                        target_weight=target,
                        delta_weight=delta,
                        reason=(
                            f"{ticker} \u5360\u6bd4 {current_weight:.1f}% "
                            f"\u8d85\u8fc7\u4e0a\u9650 {ctx.constraints.max_single_position_pct:.0f}%\uff0c"
                            f"\u5efa\u8bae\u51cf\u4ed3\u81f3 {target:.1f}%"
                        ),
                        priority=1,
                        evidence_ids=[item.evidence_id for item in evidence],
                        evidence_snapshots=evidence,
                    )
                )
                continue

            # Rule: Under-weight -> INCREASE toward equal weight
            if current_weight < equal_weight * 0.5 and num_positions >= 3:
                target = equal_weight
                delta = round(target - current_weight, 2)
                evidence = self._build_action_evidence(
                    ticker=ticker,
                    current_weight=current_weight,
                    target_weight=target,
                    trigger=(
                        f"under_weight_detected: current_weight={current_weight:.1f}% "
                        f"vs equal_weight={equal_weight:.1f}%"
                    ),
                    ctx=ctx,
                )
                candidates.append(
                    RebalanceAction(
                        ticker=ticker,
                        action=ActionType.INCREASE,
                        current_weight=current_weight,
                        target_weight=target,
                        delta_weight=delta,
                        reason=(
                            f"{ticker} \u5360\u6bd4\u4ec5 {current_weight:.1f}%\uff0c"
                            f"\u663e\u8457\u4f4e\u4e8e\u5747\u8861\u6bd4\u4f8b {equal_weight:.1f}%"
                        ),
                        priority=3,
                        evidence_ids=[item.evidence_id for item in evidence],
                        evidence_snapshots=evidence,
                    )
                )
                continue

            # Rule: Within tolerance -> HOLD
            delta_from_equal = abs(current_weight - equal_weight)
            if delta_from_equal <= ctx.constraints.min_action_delta_pct:
                evidence = self._build_action_evidence(
                    ticker=ticker,
                    current_weight=current_weight,
                    target_weight=current_weight,
                    trigger=(
                        f"within_tolerance: delta={delta_from_equal:.2f}% "
                        f"<= min_action_delta={ctx.constraints.min_action_delta_pct:.2f}%"
                    ),
                    ctx=ctx,
                )
                candidates.append(
                    RebalanceAction(
                        ticker=ticker,
                        action=ActionType.HOLD,
                        current_weight=current_weight,
                        target_weight=current_weight,
                        delta_weight=0.0,
                        reason=f"{ticker} \u6743\u91cd\u63a5\u8fd1\u5747\u8861\uff0c\u7ef4\u6301\u4e0d\u53d8",
                        priority=5,
                        evidence_ids=[item.evidence_id for item in evidence],
                        evidence_snapshots=evidence,
                    )
                )

        return candidates

    # ── Step 3: Constraint solver ───────────────────────────

    def _solve_constraints(
        self, candidates: list[RebalanceAction], constraints: RebalanceConstraints
    ) -> list[RebalanceAction]:
        """Greedy constraint solver: apply by priority, respect turnover limit."""
        if not candidates:
            return []

        # Sort by priority (1 = highest)
        sorted_candidates = sorted(candidates, key=lambda a: a.priority)

        accepted: list[RebalanceAction] = []
        remaining_turnover = constraints.max_turnover_pct

        for action in sorted_candidates:
            abs_delta = abs(action.delta_weight)

            # Skip actions below minimum delta threshold
            if action.action != ActionType.HOLD and abs_delta < constraints.min_action_delta_pct:
                continue

            # HOLD actions always pass through
            if action.action == ActionType.HOLD:
                accepted.append(action)
                continue

            # Check turnover budget
            if abs_delta > remaining_turnover:
                # Partially apply if there is remaining budget
                if remaining_turnover >= constraints.min_action_delta_pct:
                    capped_delta = remaining_turnover
                    new_target = round(
                        action.current_weight + (
                            capped_delta if action.delta_weight > 0 else -capped_delta
                        ),
                        2,
                    )
                    accepted.append(
                        RebalanceAction(
                            ticker=action.ticker,
                            action=action.action,
                            current_weight=action.current_weight,
                            target_weight=new_target,
                            delta_weight=round(
                                new_target - action.current_weight, 2
                            ),
                            reason=action.reason + " (\u53d7\u6362\u624b\u7387\u9650\u5236\u90e8\u5206\u6267\u884c)",
                            priority=action.priority,
                            evidence_ids=action.evidence_ids,
                            evidence_snapshots=action.evidence_snapshots,
                        )
                    )
                    remaining_turnover = 0.0
                continue

            accepted.append(action)
            remaining_turnover = round(remaining_turnover - abs_delta, 2)

        return accepted

    # ── Step 4: Explanation ─────────────────────────────────

    def _generate_explanation(
        self,
        actions: list[RebalanceAction],
        diag: _PortfolioDiagnosis,
        ctx: RebalanceContext,
    ) -> str:
        """Template-based Chinese explanation for the suggestion."""
        if not actions:
            return "\u5f53\u524d\u6301\u4ed3\u65e0\u9700\u8c03\u6574\u3002"

        parts: list[str] = []

        # Summary header
        non_hold = [a for a in actions if a.action != ActionType.HOLD]
        hold_count = len(actions) - len(non_hold)

        if non_hold:
            parts.append(
                f"\u57fa\u4e8e\u5f53\u524d\u6301\u4ed3\u5206\u6790\uff0c"
                f"\u5efa\u8bae\u8c03\u6574 {len(non_hold)} \u4e2a\u6807\u7684\uff0c"
                f"\u4fdd\u6301 {hold_count} \u4e2a\u6807\u7684\u4e0d\u53d8\u3002"
            )
        else:
            parts.append(
                "\u5f53\u524d\u6301\u4ed3\u914d\u7f6e\u8f83\u4e3a\u5747\u8861\uff0c"
                "\u5efa\u8bae\u7ef4\u6301\u73b0\u6709\u6301\u4ed3\u3002"
            )

        # Risk flag summary
        if diag.risk_flags:
            parts.append(
                "\u98ce\u9669\u63d0\u793a\uff1a" + "\uff1b".join(diag.risk_flags) + "\u3002"
            )

        # Action details
        for a in non_hold:
            action_verb = _ACTION_VERB_MAP.get(a.action, "\u8c03\u6574")
            parts.append(
                f"  \u2022 {action_verb} {a.ticker}\uff1a"
                f"{a.current_weight:.1f}% \u2192 {a.target_weight:.1f}% "
                f"(\u53d8\u52a8 {a.delta_weight:+.1f}%)"
            )

        return "\n".join(parts)

    # ── Helpers ─────────────────────────────────────────────

    def _collect_warnings(
        self, diag: _PortfolioDiagnosis, ctx: RebalanceContext
    ) -> list[str]:
        """Collect user-facing warnings."""
        warnings: list[str] = []

        if not ctx.portfolio:
            warnings.append("\u672a\u68c0\u6d4b\u5230\u6301\u4ed3\u6570\u636e\uff0c\u65e0\u6cd5\u751f\u6210\u5efa\u8bae\u3002")
            return warnings

        if len(ctx.portfolio) == 1:
            warnings.append(
                "\u4ec5\u6301\u6709\u5355\u4e00\u6807\u7684\uff0c\u5206\u6563\u5316\u98ce\u9669\u8f83\u9ad8\u3002"
                "\u5efa\u8bae\u8003\u8651\u589e\u52a0\u6301\u4ed3\u54c1\u79cd\u3002"
            )

        if not ctx.live_prices:
            warnings.append(
                "\u672a\u83b7\u53d6\u5b9e\u65f6\u4ef7\u683c\uff0c\u5df2\u4f7f\u7528\u4f30\u7b97\u4ef7\u683c\u8ba1\u7b97\u3002"
                "\u5b9e\u9645\u6743\u91cd\u53ef\u80fd\u5b58\u5728\u504f\u5dee\u3002"
            )

        for flag in diag.risk_flags:
            warnings.append(flag)

        for reason in ctx.fallback_reasons:
            warnings.append(f"降级原因：{reason}")

        return warnings

    async def _maybe_enhance_candidates(
        self,
        candidates: list[RebalanceAction],
        diag: _PortfolioDiagnosis,
        ctx: RebalanceContext,
    ) -> list[RebalanceAction]:
        if not ctx.use_llm_enhancement:
            return candidates
        if self._llm_enhancer is None:
            logger.warning(
                "[rebalance] use_llm_enhancement=true but no enhancer configured, fallback to deterministic"
            )
            return candidates

        try:
            result = self._llm_enhancer(candidates, diag, ctx)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, list) and all(isinstance(item, RebalanceAction) for item in result):
                return result
            logger.warning("[rebalance] enhancer returned invalid payload, fallback to deterministic")
            return candidates
        except Exception as exc:
            logger.warning("[rebalance] enhancer failed, fallback to deterministic: %s", exc)
            return candidates

    @staticmethod
    def _build_action_evidence(
        *,
        ticker: str,
        current_weight: float,
        target_weight: float,
        trigger: str,
        ctx: RebalanceContext,
    ) -> list[EvidenceSnapshot]:
        captured_at = datetime.now(timezone.utc).isoformat()
        live_price = ctx.live_prices.get(ticker)
        sector = ctx.sector_map.get(ticker, "Unknown")
        snapshots = [
            EvidenceSnapshot(
                evidence_id=f"rebalance:{ticker}:price",
                source="live_price",
                quote=f"{ticker} live_price={live_price if live_price is not None else 'N/A'}",
                report_id="",
                captured_at=captured_at,
            ),
            EvidenceSnapshot(
                evidence_id=f"rebalance:{ticker}:weights",
                source="portfolio_diagnosis",
                quote=(
                    f"{ticker} current_weight={current_weight:.2f}% "
                    f"target_weight={target_weight:.2f}% sector={sector}"
                ),
                report_id="",
                captured_at=captured_at,
            ),
            EvidenceSnapshot(
                evidence_id=f"rebalance:{ticker}:constraint",
                source="constraint_rule",
                quote=trigger,
                report_id="",
                captured_at=captured_at,
            ),
        ]
        return snapshots

    @staticmethod
    def _estimate_turnover(actions: list[RebalanceAction]) -> float:
        """Total absolute weight change (one-sided)."""
        return sum(abs(a.delta_weight) for a in actions if a.action != ActionType.HOLD)

    @staticmethod
    def _diversification_assessment(diag: _PortfolioDiagnosis) -> str:
        """Qualitative diversification change description."""
        num = len(diag.weights)
        if num >= 5:
            return "\u8f83\u597d"
        if num >= 3:
            return "\u4e2d\u7b49"
        if num >= 2:
            return "\u504f\u4f4e"
        return "\u6781\u4f4e"

    @staticmethod
    def _risk_assessment(risk_tier: RiskTier, diag: _PortfolioDiagnosis) -> str:
        """Qualitative risk change description based on tier."""
        if diag.risk_flags:
            return "\u5efa\u8bae\u964d\u4f4e\u96c6\u4e2d\u5ea6\u98ce\u9669"
        return "\u98ce\u9669\u6c34\u5e73\u53ef\u63a5\u53d7"


# ── Constants ───────────────────────────────────────────────

_ACTION_VERB_MAP: dict[ActionType, str] = {
    ActionType.REDUCE: "\u51cf\u4ed3",
    ActionType.INCREASE: "\u52a0\u4ed3",
    ActionType.BUY: "\u4e70\u5165",
    ActionType.SELL: "\u5356\u51fa",
    ActionType.HOLD: "\u6301\u6709",
}


__all__ = ["RebalanceContext", "RebalanceEngine"]
