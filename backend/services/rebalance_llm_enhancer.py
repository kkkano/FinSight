# -*- coding: utf-8 -*-
"""Agent-backed LLM enhancer for the rebalance engine (P2).

Gathers fundamental/news data for candidate tickers and uses an LLM
to refine priorities and reasoning — while preserving the deterministic
constraint-solver output as safety fallback.

This module does NOT use the LangGraph pipeline (HC-2: write operation,
structured output, no Graph).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend.api.rebalance_schemas import (
    ActionType,
    EvidenceSnapshot,
    RebalanceAction,
)

logger = logging.getLogger(__name__)


class AgentBackedEnhancer:
    """Callable enhancer compatible with ``RebalanceEngine._maybe_enhance_candidates``.

    Construction requires tool functions and an LLM factory.
    The ``__call__`` signature matches ``(candidates, diag, ctx) -> list[RebalanceAction]``.
    """

    def __init__(
        self,
        *,
        get_company_news: Optional[Callable] = None,
        get_company_info: Optional[Callable] = None,
        create_llm_fn: Optional[Callable] = None,
    ):
        self._get_company_news = get_company_news
        self._get_company_info = get_company_info
        self._create_llm_fn = create_llm_fn

    async def __call__(
        self,
        candidates: list[RebalanceAction],
        diag: Any,
        ctx: Any,
    ) -> list[RebalanceAction]:
        """Enhance candidates with agent-backed LLM reasoning."""
        if not candidates:
            return candidates

        # 1. Gather news + info for unique tickers with non-HOLD actions
        actionable = [c for c in candidates if c.action != ActionType.HOLD]
        if not actionable:
            return candidates

        unique_tickers = list({c.ticker for c in actionable})[:6]
        agent_context = await self._gather_agent_data(unique_tickers)

        # 2. Call LLM for enhanced reasoning
        if not self._create_llm_fn:
            logger.info("[rebalance-enhancer] no LLM factory, returning original candidates")
            return candidates

        enhanced = await self._llm_enhance(candidates, diag, ctx, agent_context)
        return enhanced

    async def _gather_agent_data(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch news + company info for tickers in parallel."""
        result: dict[str, dict[str, Any]] = {}

        async def _fetch_one(ticker: str) -> tuple[str, dict[str, Any]]:
            data: dict[str, Any] = {}

            if self._get_company_news:
                try:
                    raw = await asyncio.to_thread(self._get_company_news, ticker, 3)
                    headlines = []
                    if isinstance(raw, list):
                        for item in raw[:3]:
                            if isinstance(item, dict):
                                title = item.get("headline") or item.get("title") or ""
                                if title:
                                    headlines.append(str(title).strip()[:100])
                            elif isinstance(item, str) and item.strip():
                                headlines.append(item.strip()[:100])
                    data["news"] = headlines
                except Exception as exc:
                    logger.debug("[rebalance-enhancer] news fetch failed for %s: %s", ticker, exc)

            if self._get_company_info:
                try:
                    raw = await asyncio.to_thread(self._get_company_info, ticker)
                    if isinstance(raw, dict):
                        data["sector"] = raw.get("sector") or raw.get("finnhubIndustry") or ""
                        data["industry"] = raw.get("industry") or ""
                except Exception as exc:
                    logger.debug("[rebalance-enhancer] info fetch failed for %s: %s", ticker, exc)

            return ticker, data

        pairs = await asyncio.gather(*[_fetch_one(t) for t in tickers])
        for ticker, data in pairs:
            result[ticker] = data

        return result

    async def _llm_enhance(
        self,
        candidates: list[RebalanceAction],
        diag: Any,
        ctx: Any,
        agent_context: dict[str, dict[str, Any]],
    ) -> list[RebalanceAction]:
        """Use LLM to refine candidate priorities and reasoning."""
        try:
            llm = self._create_llm_fn(temperature=0.2)
        except Exception as exc:
            logger.warning("[rebalance-enhancer] LLM init failed: %s", exc)
            return candidates

        # Build prompt
        candidate_summaries = []
        for c in candidates:
            news = agent_context.get(c.ticker, {}).get("news", [])
            news_str = " | ".join(news[:3]) if news else "无近期新闻"
            candidate_summaries.append(
                f"- {c.ticker}: action={c.action.value}, "
                f"current={c.current_weight:.1f}%, target={c.target_weight:.1f}%, "
                f"delta={c.delta_weight:+.1f}%, priority={c.priority}, "
                f"reason={c.reason}, news=[{news_str}]"
            )

        weights_str = ", ".join(f"{k}:{v:.1f}%" for k, v in (diag.weights or {}).items())
        risk_str = "; ".join(diag.risk_flags) if diag.risk_flags else "无"

        prompt = f"""你是一位专业的投资组合顾问。根据以下持仓诊断和候选调仓操作，结合最新新闻，
为每个操作提供增强的优先级评估和理由。

当前持仓权重: {weights_str}
风险提示: {risk_str}
风险等级: {ctx.risk_tier.value}

候选操作:
{chr(10).join(candidate_summaries)}

请以 JSON 数组格式返回，每个元素包含:
{{"ticker": "...", "adjusted_priority": 1-5, "enhanced_reason": "..."}}

注意:
- priority 1=最紧急, 5=最低
- 如有重大利空新闻，提高减仓优先级
- 如有利好新闻但过度集中，仍应减仓
- enhanced_reason 用中文，50字以内
- 只返回 JSON 数组，不要其他内容"""

        try:
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)
            enhancements = self._parse_llm_response(content)
        except Exception as exc:
            logger.warning("[rebalance-enhancer] LLM call failed: %s", exc)
            return candidates

        if not enhancements:
            return candidates

        # Apply enhancements to candidates
        enhanced_map = {e["ticker"]: e for e in enhancements if isinstance(e, dict) and "ticker" in e}
        captured_at = datetime.now(timezone.utc).isoformat()

        enhanced_candidates: list[RebalanceAction] = []
        for c in candidates:
            enh = enhanced_map.get(c.ticker)
            if enh and c.action != ActionType.HOLD:
                new_priority = enh.get("adjusted_priority", c.priority)
                new_reason = enh.get("enhanced_reason", c.reason)

                # Validate priority range
                if isinstance(new_priority, (int, float)):
                    new_priority = max(1, min(5, int(new_priority)))
                else:
                    new_priority = c.priority

                # Add LLM evidence
                llm_evidence = EvidenceSnapshot(
                    evidence_id=f"rebalance:{c.ticker}:llm_enhancement",
                    source="llm_agent_analysis",
                    quote=str(new_reason)[:200],
                    report_id="",
                    captured_at=captured_at,
                )
                new_evidence = list(c.evidence_snapshots or []) + [llm_evidence]
                new_evidence_ids = list(c.evidence_ids or []) + [llm_evidence.evidence_id]

                enhanced_candidates.append(
                    RebalanceAction(
                        ticker=c.ticker,
                        action=c.action,
                        current_weight=c.current_weight,
                        target_weight=c.target_weight,
                        delta_weight=c.delta_weight,
                        reason=str(new_reason)[:200] if isinstance(new_reason, str) and new_reason.strip() else c.reason,
                        priority=new_priority,
                        evidence_ids=new_evidence_ids,
                        evidence_snapshots=new_evidence,
                    )
                )
            else:
                enhanced_candidates.append(c)

        return enhanced_candidates

    @staticmethod
    def _parse_llm_response(content: str) -> list[dict]:
        """Parse LLM JSON array response with fallback."""
        if not isinstance(content, str) or not content.strip():
            return []
        # Try to extract JSON array
        text = content.strip()
        # Find first [ and last ]
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < 0 or end <= start:
            return []
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return []


__all__ = ["AgentBackedEnhancer"]
