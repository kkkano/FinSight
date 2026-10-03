# -*- coding: utf-8 -*-
"""Risk agent and risk assessment helpers.

This module provides:
- Rule-based risk signal aggregation from multi-agent outputs
- Deterministic risk scoring / level mapping
- Lightweight ticker risk evaluation for alert scheduler
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
import json
from typing import Any, Dict, Iterable, Optional

from backend.agents.base_agent import AgentOutput, BaseFinancialAgent, EvidenceItem
from backend.agents.chart_specs_extra import build_risk_chart_specs
from backend.research.agent_quality_contract import (
    apply_agent_quality_contract,
    assign_evidence_source_ids,
    build_agent_claim,
)
from backend.research.agent_research_loop import apply_agent_self_check
from backend.research.prediction_contract import ForecastContext, ForecastResult
from backend.services.circuit_breaker import CircuitBreaker
from backend.utils.quote import resolve_live_quote, safe_float
from backend.tools.financial_facts import fact_date


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# 风险等级枚举 → 中文（用户可见 claim 中文化，B 类固定模板）
_RISK_LEVEL_CN: Dict[str, str] = {
    "low": "低",
    "medium": "中等",
    "high": "高",
    "critical": "极高",
}


def _risk_level_cn(level: str) -> str:
    """风险等级映射为中文，未知值原样返回。"""
    return _RISK_LEVEL_CN.get(str(level or "").strip().lower(), str(level or ""))


@dataclass(frozen=True)
class RiskSignal:
    source_agent: str
    category: str
    description: str
    severity: float


@dataclass(frozen=True)
class RiskAssessment:
    ticker: str
    risk_score: float
    risk_level: RiskLevel
    signals: list[RiskSignal]
    summary: str
    assessed_at: str


class RiskAgent(BaseFinancialAgent):
    """Rule-based risk evaluator.

    The constructor intentionally follows the same signature used by
    ``backend.graph.adapters.collector_adapter``.
    """

    AGENT_NAME = "risk_agent"

    def __init__(self, llm, cache, tools_module=None, circuit_breaker=None):
        super().__init__(llm, cache, tools_module, circuit_breaker)
        self._forecast_llm = llm

    CATEGORY_WEIGHTS: dict[str, float] = {
        "technical": 25.0,
        "fundamental": 30.0,
        "macro": 20.0,
        "news": 15.0,
        "data_quality": 10.0,
    }

    CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
        "technical": (
            "rsi",
            "macd",
            "overbought",
            "oversold",
            "bearish",
            "downtrend",
            "resistance",
            "support",
            "超买",
            "超卖",
            "下跌趋势",
            "技术",
        ),
        "fundamental": (
            "leverage",
            "debt",
            "liability",
            "earnings",
            "revenue decline",
            "negative income",
            "杠杆",
            "负债",
            "亏损",
            "营收下降",
            "估值",
            "现金流",
        ),
        "macro": (
            "yield curve",
            "inflation",
            "recession",
            "rate hike",
            "fed",
            "收益率曲线",
            "通胀",
            "衰退",
            "加息",
            "宏观",
        ),
        "news": (
            "lawsuit",
            "investigation",
            "fraud",
            "downgrade",
            "诉讼",
            "调查",
            "欺诈",
            "下调",
            "负面",
        ),
        "data_quality": (
            "missing",
            "unavailable",
            "conflict",
            "stale",
            "缺失",
            "不可用",
            "冲突",
            "过期",
            "fallback",
        ),
    }

    _SEVERITY_RULES: tuple[tuple[tuple[str, ...], float], ...] = (
        (("critical", "severe", "重大", "严重"), 0.9),
        (("high", "significant", "大幅", "高风险"), 0.7),
        (("moderate", "medium", "中等"), 0.5),
        (("low", "minor", "轻微", "低风险"), 0.3),
    )

    _RISK_LEVEL_ORDER: dict[RiskLevel, int] = {
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
        RiskLevel.CRITICAL: 4,
    }

    FORECAST_PROMPT_VERSION = "risk-drawdown-v1"

    async def forecast(self, context: ForecastContext, snapshot: Dict[str, Any]) -> ForecastResult:
        """Forecast a future close-based drawdown, not a historical stress-test label."""
        from backend.research.forecasting import run_forecast

        return await run_forecast(
            self._forecast_llm, context, snapshot,
            prediction_type="drawdown", prompt_version=self.FORECAST_PROMPT_VERSION,
            prompt=(
                "You are RiskAgent in prospective forecast mode. Use only the frozen input. "
                "Predict whether maximum close-based drawdown reaches 5% over the next 5 "
                "regular trading sessions. The scoring sequence is P0 (the future opening price "
                "at window_start), then each of the 5 session closing prices through window_end. "
                "For each close, drawdown is 1-close/prior running maximum of that sequence. "
                "event_occurs=true if the largest drawdown>=0.05, otherwise false. This is not "
                "intraday low drawdown or end-to-end return. Future prices are unknown. "
                "Use realized volatility, historical drawdown and trend as evidence for a NEW "
                "future event judgment; do not relabel a past drawdown or stress test. "
                "Both true and false are valid predictions. Do not output a probability or "
                "claim certainty. If evidence cannot support a judgment, explicitly abstain. "
                "Do not use external facts or future data. All identity, window, cutoff, "
                "thresholds and versions are fixed by context. Return ONLY one JSON object "
                "with exactly these keys: status (predicted or abstained), event_occurs "
                "(JSON true or false, or null only for abstention), reason (brief simplified "
                "Chinese, at most 600 characters), evidence_refs (a list of exact nonempty "
                "features keys, e.g. realized_vol20 or max_drawdown60, at least one for a "
                "prediction). Never return ticker, agent, dates, confidence, thresholds, "
                "versions or any extra keys."
            ),
        )


    @classmethod
    def risk_level_meets_threshold(cls, actual: RiskLevel, threshold: RiskLevel) -> bool:
        return cls._RISK_LEVEL_ORDER[actual] >= cls._RISK_LEVEL_ORDER[threshold]

    @classmethod
    def _level_from_score(cls, score: float) -> RiskLevel:
        if score <= 25:
            return RiskLevel.LOW
        if score <= 50:
            return RiskLevel.MEDIUM
        if score <= 75:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    @classmethod
    def _keyword_in_text(cls, text: str, keyword: str) -> bool:
        if not keyword:
            return False
        if any(ord(ch) > 127 for ch in keyword):
            return keyword in text
        if keyword.isalpha() and len(keyword) <= 5:
            pattern = rf"\b{re.escape(keyword)}\b"
            return re.search(pattern, text) is not None
        return keyword in text

    @classmethod
    def _severity_from_text(cls, text: str) -> float:
        lowered = str(text or "").lower()
        for keywords, severity in cls._SEVERITY_RULES:
            if any(cls._keyword_in_text(lowered, keyword) for keyword in keywords):
                return severity
        return 0.5

    @classmethod
    def _categorize_text(cls, text: str) -> str:
        lowered = str(text or "").lower()
        for category, keywords in cls.CATEGORY_KEYWORDS.items():
            if any(cls._keyword_in_text(lowered, keyword) for keyword in keywords):
                return category
        return "data_quality"

    @classmethod
    def _coerce_signals_from_agent_outputs(cls, agent_outputs: Iterable[Any]) -> list[RiskSignal]:
        signals: list[RiskSignal] = []
        for output in agent_outputs or []:
            if isinstance(output, AgentOutput):
                source = output.agent_name
                risks = output.risks
            elif isinstance(output, dict):
                source = str(output.get("agent_name") or "unknown")
                raw_risks = output.get("risks")
                risks = raw_risks if isinstance(raw_risks, list) else []
            else:
                continue

            for risk_text in risks:
                text = str(risk_text or "").strip()
                if not text:
                    continue
                signals.append(
                    RiskSignal(
                        source_agent=source or "unknown",
                        category=cls._categorize_text(text),
                        description=text,
                        severity=cls._severity_from_text(text),
                    )
                )
        return signals

    @classmethod
    def _score_signals(cls, signals: list[RiskSignal]) -> float:
        if not signals:
            return 0.0

        score = 0.0
        for category, weight in cls.CATEGORY_WEIGHTS.items():
            bucket = [signal for signal in signals if signal.category == category]
            if not bucket:
                continue
            severity_sum = sum(max(0.0, min(1.0, float(signal.severity))) for signal in bucket)
            category_factor = min(1.0, severity_sum)
            score += weight * category_factor
        return round(min(100.0, score), 2)

    @classmethod
    def _dimension_scores(cls, signals: list[RiskSignal]) -> dict[str, float]:
        """各风险维度独立归一到 0-100（用于雷达图）。

        每个维度取该维度所有信号 severity 之和并 cap 到 1.0，再 ×100，
        反映该维度的风险饱和度。无信号的维度记 0，供雷达图等尺度对比。
        """
        scores: dict[str, float] = {}
        for category in cls.CATEGORY_WEIGHTS:
            bucket = [s for s in signals if s.category == category]
            severity_sum = sum(max(0.0, min(1.0, float(s.severity))) for s in bucket)
            scores[category] = round(min(1.0, severity_sum) * 100.0, 2)
        return scores

    @classmethod
    def _build_summary(cls, ticker: str, score: float, level: RiskLevel, signals: list[RiskSignal]) -> str:
        if not signals:
            return f"{ticker} 已取得的指标未触发预设风险阈值；这不代表整体投资风险低，也不抵消已经发生的历史回撤。"

        category_counts: dict[str, int] = {}
        for signal in signals:
            category_counts[signal.category] = category_counts.get(signal.category, 0) + 1
        sorted_categories = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
        top_category = sorted_categories[0][0]
        top_signal = max(signals, key=lambda item: item.severity)
        return (
            f"{ticker} 风险评分 {score:.1f}/100，等级 {level.value}。"
            f" 主要风险维度：{top_category}（{category_counts[top_category]} 条信号）；"
            f" 关键信号：{top_signal.description}"
        )

    @classmethod
    def assess_risk(cls, ticker: str, agent_outputs: Iterable[Any]) -> RiskAssessment:
        signals = cls._coerce_signals_from_agent_outputs(agent_outputs)
        score = cls._score_signals(signals)
        level = cls._level_from_score(score)
        assessed_at = datetime.now(timezone.utc).isoformat()
        summary = cls._build_summary(ticker=ticker, score=score, level=level, signals=signals)
        return RiskAssessment(
            ticker=ticker,
            risk_score=score,
            risk_level=level,
            signals=signals,
            summary=summary,
            assessed_at=assessed_at,
        )

    @classmethod
    def evaluate_ticker_risk_lightweight(
        cls,
        ticker: str,
        price_snapshot: Any,
    ) -> RiskAssessment:
        """Lightweight risk eval for scheduler (price/volatility based)."""
        signals: list[RiskSignal] = []

        if isinstance(price_snapshot, dict):
            price = safe_float(price_snapshot.get("price"))
            change_percent = safe_float(price_snapshot.get("change_percent"))
            if change_percent is None:
                change_percent = safe_float(price_snapshot.get("change_pct"))
            volatility = safe_float(price_snapshot.get("volatility"))
        else:
            price = safe_float(getattr(price_snapshot, "price", None))
            change_percent = safe_float(getattr(price_snapshot, "change_percent", None))
            volatility = safe_float(getattr(price_snapshot, "volatility", None))

        if price is None or change_percent is None:
            signals.append(
                RiskSignal(
                    source_agent=cls.AGENT_NAME,
                    category="data_quality",
                    description=f"{ticker} 实时价格数据缺失，风险评估置信度下降。",
                    severity=0.7,
                )
            )
        else:
            move = abs(change_percent)
            if move >= 8.0:
                signals.extend(
                    [
                        RiskSignal(
                            source_agent=cls.AGENT_NAME,
                            category="technical",
                            description=f"{ticker} 单日波动 {change_percent:+.2f}%（极端波动）。",
                            severity=0.9,
                        ),
                        RiskSignal(
                            source_agent=cls.AGENT_NAME,
                            category="news",
                            description=f"{ticker} 价格出现极端波动，可能存在突发事件风险。",
                            severity=0.75,
                        ),
                        RiskSignal(
                            source_agent=cls.AGENT_NAME,
                            category="macro",
                            description=f"{ticker} 波动显著高于常态，需警惕市场环境冲击。",
                            severity=0.65,
                        ),
                        RiskSignal(
                            source_agent=cls.AGENT_NAME,
                            category="fundamental",
                            description=f"{ticker} 大幅波动可能反映估值或基本面再定价风险。",
                            severity=0.6,
                        ),
                    ]
                )
            elif move >= 5.0:
                signals.extend(
                    [
                        RiskSignal(
                            source_agent=cls.AGENT_NAME,
                            category="technical",
                            description=f"{ticker} 单日波动 {change_percent:+.2f}%（高波动）。",
                            severity=0.7,
                        ),
                        RiskSignal(
                            source_agent=cls.AGENT_NAME,
                            category="news",
                            description=f"{ticker} 波动偏高，建议复核近期新闻与公告。",
                            severity=0.5,
                        ),
                        RiskSignal(
                            source_agent=cls.AGENT_NAME,
                            category="macro",
                            description=f"{ticker} 风险暴露上升，建议关注市场风格切换。",
                            severity=0.45,
                        ),
                    ]
                )
            elif move >= 3.0:
                signals.append(
                    RiskSignal(
                        source_agent=cls.AGENT_NAME,
                        category="technical",
                        description=f"{ticker} 单日波动 {change_percent:+.2f}%（中等波动）。",
                        severity=0.45,
                    )
                )

        if volatility is not None and volatility >= 0.04:
            signals.append(
                RiskSignal(
                    source_agent=cls.AGENT_NAME,
                    category="technical",
                    description=f"{ticker} 近期波动率约 {volatility:.2%}，处于偏高区间。",
                    severity=0.6,
                )
            )

        score = cls._score_signals(signals)
        level = cls._level_from_score(score)
        assessed_at = datetime.now(timezone.utc).isoformat()
        summary = cls._build_summary(ticker=ticker, score=score, level=level, signals=signals)
        return RiskAssessment(
            ticker=ticker,
            risk_score=score,
            risk_level=level,
            signals=signals,
            summary=summary,
            assessed_at=assessed_at,
        )

    def _build_factor_signals(
        self,
        ticker: str,
        factor_payload: Any,
    ) -> list[RiskSignal]:
        signals: list[RiskSignal] = []

        if isinstance(factor_payload, dict) and not factor_payload.get("error"):
            factor_beta = factor_payload.get("factor_beta")
            if isinstance(factor_beta, dict):
                market_beta = safe_float(factor_beta.get("market"))
                growth_beta = safe_float(factor_beta.get("growth"))
                if market_beta is not None and market_beta >= 1.25:
                    signals.append(
                        RiskSignal(
                            source_agent=self.AGENT_NAME,
                            category="macro",
                            description=f"{ticker} market beta={market_beta:.2f}, downside sensitivity elevated.",
                            severity=0.65,
                        )
                    )
                if growth_beta is not None and growth_beta >= 1.35:
                    signals.append(
                        RiskSignal(
                            source_agent=self.AGENT_NAME,
                            category="technical",
                            description=f"{ticker} growth-factor tilt is high (beta={growth_beta:.2f}).",
                            severity=0.55,
                        )
                    )

            ann_vol = safe_float(factor_payload.get("annualized_volatility"))
            if ann_vol is not None and ann_vol >= 0.35:
                signals.append(
                    RiskSignal(
                        source_agent=self.AGENT_NAME,
                        category="technical",
                        description=f"{ticker} estimated annualized volatility {ann_vol:.1%} is elevated.",
                        severity=0.6,
                    )
                )

        return signals

    @staticmethod
    def _risk_tool_payload(raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                return {"error": "invalid_risk_payload"}
        return raw if isinstance(raw, dict) else {"error": "invalid_risk_payload"}

    @staticmethod
    async def _call_risk_tool(tool: Any, *args: Any, **kwargs: Any) -> Any:
        if not callable(tool):
            return {"error": "risk_tool_unavailable"}
        try:
            return await asyncio.to_thread(tool, *args, **kwargs)
        except Exception as exc:
            return {"error": "risk_tool_failed", "error_type": type(exc).__name__}

    @classmethod
    def _historical_drawdown_payload(cls, raw: Any, ticker: str) -> dict[str, Any]:
        payload = cls._risk_tool_payload(raw)
        if not payload.get("error"):
            subject = str(payload.get("ticker") or ticker).upper()
            value = safe_float(payload.get("max_drawdown"))
            if subject != ticker.upper() or value is None or not -1 <= value <= 0:
                return {"error": "historical_drawdown_unverified"}
            return payload
        if not isinstance(raw, str):
            return payload
        coverage = re.search(r"(?:Top 3 Historical Drawdowns|No significant drawdowns found) for ([A-Za-z0-9.^=-]+).*?(?:coverage|Coverage:)\s*([\d-]{10}) to ([\d-]{10})", raw, re.IGNORECASE | re.DOTALL)
        if not coverage or coverage.group(1).upper() != ticker.upper() or not fact_date(coverage.group(2)) or not fact_date(coverage.group(3)) or coverage.group(2) > coverage.group(3):
            return {"error": "historical_drawdown_unverified"}
        values = [safe_float(value) for value in re.findall(r"- Drawdown:\s*(-?\d+(?:\.\d+)?)%", raw)]
        values = [value / 100 for value in values if value is not None and -100 <= value <= 0]
        if not values and "No significant drawdowns found" not in raw:
            return {"error": "historical_drawdown_unverified"}
        return {"ticker": ticker, "source": "historical_price_analysis", "period_start": coverage.group(2), "period_end": coverage.group(3), "max_drawdown": min(values) if values else 0.0, "definition": "historical_close_to_running_peak", "error": None}

    async def research(
        self,
        query: str,
        ticker: str,
        on_event: Optional[Any] = None,
    ) -> AgentOutput:
        """Adapter-compatible entrypoint for report pipeline."""
        query_text = str(query or "")
        del on_event

        clean_ticker = str(ticker or "").strip().upper() or "N/A"
        get_stock_price = getattr(self.tools, "get_stock_price", None)
        quote, raw_payload = await asyncio.to_thread(
            resolve_live_quote,
            clean_ticker,
            get_stock_price,
        )
        assessment = self.evaluate_ticker_risk_lightweight(clean_ticker, quote or {})

        positions = [{"ticker": clean_ticker, "weight": 1.0}]
        get_factor_exposure = getattr(self.tools, "get_factor_exposure", None)
        factor_payload = await self._call_risk_tool(get_factor_exposure, positions, lookback_days=252)
        factor_payload = self._risk_tool_payload(factor_payload)
        positions_payload = factor_payload.get("positions")
        if isinstance(positions_payload, list) and any(str(position.get("ticker") or "").upper() != clean_ticker for position in positions_payload if isinstance(position, dict)):
            factor_payload = {"error": "factor_subject_mismatch"}
        valid_factor = not factor_payload.get("error") and (
            any(safe_float((factor_payload.get("factor_beta") or {}).get(key)) is not None for key in ("market", "growth"))
            if isinstance(factor_payload.get("factor_beta"), dict) else False
        )
        volatility_value = safe_float(factor_payload.get("annualized_volatility"))
        valid_factor = valid_factor or (not factor_payload.get("error") and volatility_value is not None and volatility_value >= 0)
        get_drawdowns = getattr(self.tools, "analyze_historical_drawdowns", None)
        drawdown_payload = self._historical_drawdown_payload(
            await self._call_risk_tool(get_drawdowns, clean_ticker), clean_ticker,
        )

        extra_signals = self._build_factor_signals(
            ticker=clean_ticker,
            factor_payload=factor_payload,
        )
        if extra_signals:
            merged_signals = list(assessment.signals) + extra_signals
            merged_score = self._score_signals(merged_signals)
            merged_level = self._level_from_score(merged_score)
            assessment = RiskAssessment(
                ticker=assessment.ticker,
                risk_score=merged_score,
                risk_level=merged_level,
                signals=merged_signals,
                summary=self._build_summary(
                    ticker=assessment.ticker,
                    score=merged_score,
                    level=merged_level,
                    signals=merged_signals,
                ),
                assessed_at=assessment.assessed_at,
            )

        source = str((quote or {}).get("source") or "risk_rule_engine")
        fallback_used = source == "yfinance_fallback" or quote is None
        evidence_text = str(raw_payload) if raw_payload is not None else str(quote or {})

        score_available = valid_factor or any(signal.category != "data_quality" for signal in assessment.signals)
        evidence = [
            EvidenceItem(
                text=evidence_text[:1000],
                source=source,
                timestamp=assessment.assessed_at,
                meta={
                    "risk_score": assessment.risk_score if score_available else None,
                    "risk_level": assessment.risk_level.value if score_available else "unknown",
                    "risk_score_available": score_available,
                },
            )
        ] if quote is not None else []
        data_sources = [source] if quote is not None else []

        if (
            valid_factor
        ):
            evidence.append(
                EvidenceItem(
                    text="Single-symbol factor exposure snapshot.",
                    source=str(factor_payload.get("source") or "factor_model"),
                    timestamp=str(factor_payload.get("as_of") or assessment.assessed_at),
                    meta=factor_payload,
                )
            )
            data_sources.append(str(factor_payload.get("source") or "factor_model"))
        if not drawdown_payload.get("error") and safe_float(drawdown_payload.get("max_drawdown")) is not None:
            evidence.append(EvidenceItem(
                text=f"历史最大回撤 {safe_float(drawdown_payload['max_drawdown']):.2%}，覆盖 {drawdown_payload.get('period_start') or '未知起点'} 至 {drawdown_payload.get('period_end') or '未知终点'}；这是历史事实，不是未来回撤预测。",
                source=str(drawdown_payload.get("source") or "historical_price_analysis"),
                timestamp=drawdown_payload.get("period_end"), meta=drawdown_payload,
            ))
            data_sources.append(str(drawdown_payload.get("source") or "historical_price_analysis"))

        if not valid_factor:
            fallback_used = True

        assign_evidence_source_ids(evidence, agent_name=self.AGENT_NAME)
        claims = self._build_native_claims(
            ticker=clean_ticker,
            query=query_text,
            assessment=assessment,
            evidence=evidence,
            factor_payload=factor_payload,
            confidence=0.75 if quote is not None else 0.45,
        ) if score_available else []

        # P2-8：风险维度雷达图 + 综合风险仪表盘，维度/评分不足时返回 []
        chart_specs = build_risk_chart_specs(
            clean_ticker,
            assessment.risk_score,
            assessment.risk_level.value,
            self._dimension_scores(assessment.signals),
        ) if score_available else []

        output = AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=(assessment.summary if score_available else f"{clean_ticker} 综合风险评分未知。[数据缺失] 未取得有效因子/波动风险输入，不能据此断言低风险。") + (" [数据缺失] 因子风险数据不可用，当前评分仅覆盖已取得的风险输入。" if score_available and not valid_factor else ""),
            evidence=evidence,
            confidence=0.75 if quote is not None else 0.45,
            data_sources=list(dict.fromkeys(data_sources)),
            as_of=assessment.assessed_at,
            claims=claims,
            chart_specs=chart_specs,
            fallback_used=fallback_used,
            risks=[signal.description for signal in assessment.signals],
            fallback_reason="risk_inputs_unavailable" if not score_available else "quote_unavailable" if quote is None else None,
            retryable=True,
        )
        output = apply_agent_quality_contract(output, query=query_text, ticker=clean_ticker)
        return apply_agent_self_check(output, query=query_text, ticker=clean_ticker)

    def _build_native_claims(
        self,
        *,
        ticker: str,
        query: str,
        assessment: RiskAssessment,
        evidence: list[EvidenceItem],
        factor_payload: dict[str, Any],
        confidence: float,
    ) -> list[dict[str, Any]]:
        source_ids = [
            str((item.meta or {}).get("source_id") or "").strip()
            for item in evidence
            if str((item.meta or {}).get("source_id") or "").strip()
        ]
        claims: list[dict[str, Any]] = []
        if source_ids:
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=(f"{ticker} 已取得的指标未触发预设风险阈值；这不代表整体投资风险低。"
                           if not assessment.signals else
                           f"{ticker} 已观测规则的风险评分为 {assessment.risk_score:.1f}/100（{_risk_level_cn(assessment.risk_level.value)}规则信号强度）。"),
                    evidence_ids=source_ids,
                    stance="risk",
                    confidence=confidence,
                    limitations=["仅衡量本轮可观测指标触发预设规则的程度，不等于对整体投资风险的完整评级。"],
                    metadata={"claim_type": "risk_score", "risk_level": assessment.risk_level.value,
                              "assessment_scope": "observed_rule_signals"},
                )
            )

        factor_source_ids = [str((item.meta or {}).get("source_id") or "") for item in evidence if isinstance((item.meta or {}).get("factor_beta"), dict)]
        if factor_source_ids and isinstance(factor_payload.get("factor_beta"), dict):
            beta = factor_payload.get("factor_beta") or {}
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=(
                        f"{ticker} 因子暴露快照：市场 beta={safe_float(beta.get('market'))}，"
                        f"成长 beta={safe_float(beta.get('growth'))}。"
                    ),
                    evidence_ids=factor_source_ids,
                    stance="risk",
                    confidence=confidence,
                    limitations=["因子暴露基于历史模型快照，不代表未来表现。"],
                    metadata={"claim_type": "factor_exposure"},
                )
            )
        return claims


__all__ = [
    "RiskAgent",
    "RiskAssessment",
    "RiskLevel",
    "RiskSignal",
]
