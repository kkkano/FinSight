# -*- coding: utf-8 -*-
"""
Deterministic subject resolution with three-tier active_symbol binding.

Architecture for ``active_symbol`` fallback decision
(宁可多澄清，也不要误绑定):

  Tier 1 — Strong signal: explicit ticker in query / UI selection.
           Handled by ``extract_tickers`` — zero ambiguity.
  Tier 2 — High-precision rules: unambiguous financial vocabulary.
           Handled by ``has_financial_intent()`` — keyword + regex.
  Tier 3 — LLM binary classifier: ``financial_actionable`` vs
           ``non_financial``, with confidence threshold.
  Default — Don't bind ``active_symbol`` → let ``clarify`` handle it.
"""
from __future__ import annotations

import asyncio
import logging
import re

from langchain_core.messages import HumanMessage

from backend.graph.nodes.query_intent import has_financial_intent
from backend.graph.state import GraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 3: LLM binary classifier
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = (
    "判断以下用户查询是否包含明确的金融分析意图"
    "（如股票分析、行情查询、投资建议、公司研究等）。\n"
    "仅回复一个 0-100 的整数，表示金融意图的置信度。\n"
    "0=完全无关金融 100=明确金融分析。\n\n"
    "查询：\"{query}\"\n"
    "置信度："
)

# 宁可多澄清，也不要误绑定 → threshold 偏高
_FINANCIAL_CONFIDENCE_THRESHOLD = 75

# LLM call hard timeout (seconds)
_LLM_CLASSIFY_TIMEOUT = 5.0


async def _llm_classify_financial(query: str) -> tuple[bool, int]:
    """
    Tier 3: Ask a fast LLM for binary financial-intent classification.

    Returns ``(is_financial, confidence_score)``.
    On any failure → ``(False, 0)`` → safe fallback → clarify.
    """
    try:
        from backend.llm_config import create_llm

        llm = create_llm(temperature=0.0, max_tokens=256, request_timeout=10)
        prompt = _CLASSIFY_PROMPT.format(query=query)

        response = await asyncio.wait_for(
            llm.ainvoke([HumanMessage(content=prompt)]),
            timeout=_LLM_CLASSIFY_TIMEOUT,
        )
        text = (response.content or "").strip()
        match = re.search(r"\d+", text)
        if match:
            score = min(100, max(0, int(match.group())))
            return score >= _FINANCIAL_CONFIDENCE_THRESHOLD, score
        return False, 0
    except Exception as exc:
        logger.debug("[resolve_subject] Tier-3 LLM classify failed: %s", exc)
        return False, 0


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

async def resolve_subject(state: GraphState) -> dict:
    """
    Deterministic subject resolution.

    Priority: selection > query ticker > active_symbol (gated) > unknown.
    """
    ui = state.get("ui_context") or {}
    selections = ui.get("selections") or []
    active_symbol = ui.get("active_symbol")
    query = (state.get("query") or "").strip()

    subject_type = "unknown"
    tickers: list[str] = []
    selection_ids: list[str] = []
    selection_types: list[str] = []
    selection_payload: list[dict] = []

    # Binding tier tracking (for trace / debugging)
    binding_tier: str = "none"

    # Shared extract_tickers result — reused for is_comparison at the end.
    _ticker_meta: dict | None = None

    # ------------------------------------------------------------------
    # Path A: Selections present → type comes from selection
    # ------------------------------------------------------------------
    if isinstance(selections, list) and selections:
        selection_ids = [str(s.get("id")) for s in selections if isinstance(s, dict) and s.get("id")]
        selection_types = [str(s.get("type")) for s in selections if isinstance(s, dict) and s.get("type")]
        selection_payload = [s for s in selections if isinstance(s, dict)]

        if len(selections) == 1:
            first = selection_types[:1]
            if first == ["news"]:
                subject_type = "news_item"
            elif first == ["filing"]:
                subject_type = "filing"
            else:
                subject_type = "research_doc"
        else:
            if all(t == "news" for t in selection_types):
                subject_type = "news_set"
            elif all(t == "filing" for t in selection_types):
                subject_type = "filing"
            else:
                subject_type = "research_doc"

        binding_tier = "selection"

        # Carry ticker context: explicit in query > active_symbol.
        if query:
            try:  # pragma: no cover
                from backend.config.ticker_mapping import extract_tickers

                meta = extract_tickers(query)
                _ticker_meta = meta
                found = meta.get("tickers") if isinstance(meta, dict) else []
                found = [str(t).strip().upper() for t in (found or []) if str(t).strip()]
                if found:
                    tickers = found
            except Exception:
                pass
        if not tickers and isinstance(active_symbol, str) and active_symbol.strip():
            from backend.config.ticker_mapping import normalize_ticker
            tickers = [normalize_ticker(active_symbol)]

    # ------------------------------------------------------------------
    # Path B: No selection → try to resolve from query
    # ------------------------------------------------------------------
    elif query:
        # Tier 1: explicit ticker in query text
        try:  # pragma: no cover
            from backend.config.ticker_mapping import extract_tickers

            meta = extract_tickers(query)
            _ticker_meta = meta
            found = meta.get("tickers") if isinstance(meta, dict) else []
            found = [str(t).strip().upper() for t in (found or []) if str(t).strip()]
            if found:
                subject_type = "company"
                tickers = found
                binding_tier = "tier1_explicit_ticker"
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Fallback: active_symbol binding decision (three-tier gate)
    # ------------------------------------------------------------------
    if (
        subject_type == "unknown"
        and isinstance(active_symbol, str)
        and active_symbol.strip()
        and query
    ):
        from backend.config.ticker_mapping import normalize_ticker

        # Tier 2: high-precision keyword match (zero latency)
        if has_financial_intent(query):
            subject_type = "company"
            tickers = [normalize_ticker(active_symbol)]
            binding_tier = "tier2_keyword"
        else:
            # Tier 3: LLM binary classification (adds ~1-3s latency)
            is_financial, confidence = await _llm_classify_financial(query)
            if is_financial:
                subject_type = "company"
                tickers = [normalize_ticker(active_symbol)]
                binding_tier = f"tier3_llm(confidence={confidence})"
            else:
                # Default: don't bind → clarify will handle it
                binding_tier = f"none(llm_confidence={confidence})"

    # 最终防线：对 tickers 做规范化去重
    try:
        from backend.config.ticker_mapping import dedup_tickers
        tickers = dedup_tickers(tickers)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Extract comparison hint — reuse _ticker_meta from Path A / B.
    # ------------------------------------------------------------------
    is_comparison = False
    if _ticker_meta is not None:
        is_comparison = bool(_ticker_meta.get("is_comparison")) if isinstance(_ticker_meta, dict) else False

    return {
        "subject": {
            "subject_type": subject_type,
            "tickers": tickers,
            "selection_ids": selection_ids,
            "selection_types": selection_types,
            "selection_payload": selection_payload,
            "binding_tier": binding_tier,
            "is_comparison": is_comparison,
        }
    }
