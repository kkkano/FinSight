# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/report_builder.py（WP3 Task5，零行为变更）。
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from backend.report.util import _safe_str


def _host():
    """宿主延迟解析：_agent_summaries_from_steps 仍居 report_builder（互引破环，T8 评估归位）。"""
    import importlib

    return importlib.import_module("backend.graph.report_builder")

_GROUNDING_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?<!\d)\d+(?:\.\d+)?\s*(?:%|倍|x|X|亿美元|万亿美元|亿|万|bps|bp|美元|元|点|亿元|万元)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"20\d{2}\s*(?:年|Q[1-4])[^\n。；;]{0,16}(?:发布|推出|上线|发售|量产|并购|收购|拆分)",
        flags=re.IGNORECASE,
    ),
)


def _normalize_for_grounding(value: Any) -> str:
    return re.sub(r"\s+", "", _safe_str(value)).lower()

def _extract_grounding_claims(text: str, *, max_claims: int = 80) -> list[str]:
    raw = _safe_str(text).strip()
    if not raw:
        return []

    claims: list[str] = []
    seen: set[str] = set()
    for pattern in _GROUNDING_CLAIM_PATTERNS:
        for match in pattern.finditer(raw):
            claim = _safe_str(match.group(0)).strip()
            if not claim:
                continue
            key = _normalize_for_grounding(claim)
            if not key or key in seen:
                continue
            seen.add(key)
            claims.append(claim)
            if len(claims) >= max_claims:
                return claims
    return claims

def _build_grounding_corpus(
    *,
    citations: list[dict[str, Any]],
    agent_summaries: list[dict[str, Any]] | dict[str, str],
    step_results: dict[str, Any],
) -> str:
    parts: list[str] = []

    for citation in citations:
        if not isinstance(citation, dict):
            continue
        parts.extend([
            _safe_str(citation.get("title")),
            _safe_str(citation.get("snippet")),
            _safe_str(citation.get("url")),
            _safe_str(citation.get("source")),
            _safe_str(citation.get("published_date")),
        ])

    # agent_summaries may be list[dict] (from _agent_summaries_from_steps) or dict[str, str]
    if isinstance(agent_summaries, list):
        for item in agent_summaries:
            if isinstance(item, dict):
                parts.append(_safe_str(item.get("summary", "")))
            else:
                parts.append(_safe_str(item))
    elif isinstance(agent_summaries, dict):
        for _, summary in agent_summaries.items():
            parts.append(_safe_str(summary))

    for _, item in (step_results or {}).items():
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        if isinstance(output, dict):
            parts.append(_safe_str(output.get("summary")))
            parts.append(_safe_str(output.get("analysis")))
            parts.append(_safe_str(output.get("text")))
            evidence = output.get("evidence")
            if isinstance(evidence, list):
                for ev in evidence[:12]:
                    if isinstance(ev, dict):
                        parts.extend([
                            _safe_str(ev.get("title")),
                            _safe_str(ev.get("snippet")),
                            _safe_str(ev.get("url")),
                            _safe_str(ev.get("source")),
                        ])
        else:
            parts.append(_safe_str(output))

    return "\n".join([p for p in parts if p])

def _is_claim_grounded(claim: str, normalized_corpus: str) -> bool:
    normalized_claim = _normalize_for_grounding(claim)
    if not normalized_claim or not normalized_corpus:
        return False

    if normalized_claim in normalized_corpus:
        return True

    number_tokens = re.findall(r"\d+(?:\.\d+)?", claim)
    if not number_tokens:
        return False
    if not all(num in normalized_corpus for num in number_tokens[:2]):
        return False

    keyword_match = re.search(
        r"(发布|推出|上线|并购|收购|营收|利润|增速|增长|同比|环比|eps|pe|rsi|毛利率|现金流|10-k|10-q|业绩会|电话会)",
        claim,
        flags=re.IGNORECASE,
    )
    if keyword_match:
        keyword = _normalize_for_grounding(keyword_match.group(0))
        if keyword and keyword not in normalized_corpus:
            return False

    return True

def _compute_grounding_stats(
    *,
    generated_text: str,
    citations: list[dict[str, Any]],
    agent_summaries: list[dict[str, Any]] | dict[str, str],
    render_vars: dict[str, Any],
    step_results: dict[str, Any],
) -> dict[str, Any]:
    claims = _extract_grounding_claims(generated_text)
    if not claims:
        render_text = "\n".join(
            _safe_str(render_vars.get(key))
            for key in (
                "investment_summary",
                "valuation",
                "analysis",
                "highlights",
                "company_overview",
                "catalysts",
                "risks",
                "summary",
            )
            if _safe_str(render_vars.get(key)).strip()
        )
        claims = _extract_grounding_claims(render_text)

    if not claims:
        return {
            "grounding_rate": None,
            "claim_count": 0,
            "grounded_count": 0,
            "sample_ungrounded_claims": [],
        }

    corpus = _build_grounding_corpus(
        citations=citations,
        agent_summaries=agent_summaries,
        step_results=step_results,
    )
    normalized_corpus = _normalize_for_grounding(corpus)

    grounded_count = 0
    ungrounded: list[str] = []
    for claim in claims:
        if _is_claim_grounded(claim, normalized_corpus):
            grounded_count += 1
        elif len(ungrounded) < 5:
            ungrounded.append(claim)

    claim_count = len(claims)
    grounding_rate = grounded_count / claim_count if claim_count > 0 else None

    return {
        "grounding_rate": grounding_rate,
        "claim_count": claim_count,
        "grounded_count": grounded_count,
        "sample_ungrounded_claims": ungrounded,
    }
