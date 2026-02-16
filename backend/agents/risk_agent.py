# -*- coding: utf-8 -*-
"""Risk agent and risk assessment helpers.

This module provides:
- Rule-based risk signal aggregation from multi-agent outputs
- Deterministic risk scoring / level mapping
- Lightweight ticker risk evaluation for alert scheduler
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Iterable, Optional

from backend.agents.base_agent import AgentOutput, BaseFinancialAgent, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker
from backend.utils.quote import resolve_live_quote, safe_float


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


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
    ``backend.graph.adapters.agent_adapter``.
    """

    AGENT_NAME = "risk_agent"

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

    def __init__(self, llm: Any, cache: Any, tools_module: Any, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

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
    def _build_summary(cls, ticker: str, score: float, level: RiskLevel, signals: list[RiskSignal]) -> str:
        if not signals:
            return f"{ticker} 风险评分 {score:.1f}/100，等级 {level.value}，未发现显著风险信号。"

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

    async def research(
        self,
        query: str,
        ticker: str,
        on_event: Optional[Any] = None,
    ) -> AgentOutput:
        """Adapter-compatible entrypoint for report pipeline."""
        del query  # rule-only agent, does not need user query text today
        del on_event

        clean_ticker = str(ticker or "").strip().upper() or "N/A"
        get_stock_price = getattr(self.tools, "get_stock_price", None)
        quote, raw_payload = resolve_live_quote(clean_ticker, get_stock_price)
        assessment = self.evaluate_ticker_risk_lightweight(clean_ticker, quote or {})

        source = str((quote or {}).get("source") or "risk_rule_engine")
        fallback_used = source == "yfinance_fallback" or quote is None
        evidence_text = str(raw_payload) if raw_payload is not None else str(quote or {})

        evidence = [
            EvidenceItem(
                text=evidence_text[:1000],
                source=source,
                timestamp=assessment.assessed_at,
                meta={
                    "risk_score": assessment.risk_score,
                    "risk_level": assessment.risk_level.value,
                },
            )
        ]

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=assessment.summary,
            evidence=evidence,
            confidence=0.75 if quote is not None else 0.45,
            data_sources=[source],
            as_of=assessment.assessed_at,
            fallback_used=fallback_used,
            risks=[signal.description for signal in assessment.signals],
            fallback_reason="quote_unavailable" if quote is None else None,
            retryable=True,
        )


__all__ = [
    "RiskAgent",
    "RiskAssessment",
    "RiskLevel",
    "RiskSignal",
]
