# -*- coding: utf-8 -*-
"""报告 claim 验证/删改（WP3 Task4 机械搬运自 backend/graph/nodes/synthesize.py:372-560）。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from typing import TYPE_CHECKING

from backend.services.llm_retry import ainvoke_with_rate_limit_retry, is_rate_limit_error

if TYPE_CHECKING:  # GraphState 仅作类型注解——避免触发 backend.graph.__init__ 饿加载环
    from backend.graph.state import GraphState


def _synth():
    """宿主符号延迟解析：verifier 与 synthesize 相互引用，import 期破环、调用期取真身。
    这些共享 helper 的物理归位在 WP3-T8 收尾统一评估（一个函数一个家）。"""
    import importlib

    return importlib.import_module("backend.graph.nodes.synthesize")

logger = logging.getLogger(__name__)


def _normalize_verifier_claims(raw_claims: Any, *, max_items: int) -> list[dict[str, str]]:
    if not isinstance(raw_claims, list):
        return []

    claims: list[dict[str, str]] = []
    for item in raw_claims:
        if len(claims) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not claim:
            continue
        claims.append(
            {
                "claim": claim[:240],
                "reason": reason[:240] if reason else "证据池中未找到明确支撑",
            }
        )
    return claims


def _apply_verifier_redactions(text: str, claims: list[dict[str, str]]) -> str:
    cleaned = str(text or "")
    if not cleaned.strip() or not claims:
        return cleaned

    for item in claims:
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue
        if claim in cleaned:
            cleaned = cleaned.replace(claim, _synth()._HALLUCINATION_SAFE_PLACEHOLDER)

    cleaned = re.sub(
        rf"(?:{re.escape(_synth()._HALLUCINATION_SAFE_PLACEHOLDER)}\s*){{2,}}",
        _synth()._HALLUCINATION_SAFE_PLACEHOLDER + " ",
        cleaned,
    ).strip()
    return cleaned


def _contains_claim_after_redaction(text: str, claim: str) -> bool:
    cleaned_text = str(text or "").strip()
    cleaned_claim = str(claim or "").strip()
    if not cleaned_text or not cleaned_claim:
        return False

    if cleaned_claim in cleaned_text:
        return True

    normalized_text = _synth()._normalize_for_match(cleaned_text)
    normalized_claim = _synth()._normalize_for_match(cleaned_claim)
    if not normalized_text or not normalized_claim:
        return False
    return normalized_claim in normalized_text


def _compute_unresolved_unsupported_claims(
    text: str,
    claims: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    if not claims:
        return []

    unresolved: list[dict[str, str]] = []
    for item in claims:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue
        if _contains_claim_after_redaction(text, claim):
            unresolved.append(
                {
                    "claim": claim[:240],
                    "reason": str(item.get("reason") or "").strip()[:240],
                }
            )
    return unresolved


async def _run_deep_report_verifier(
    *,
    state: "GraphState",
    generated_text: str,
    grounding_text: str,
) -> dict[str, Any]:
    enabled = _synth()._env_bool("LANGGRAPH_DEEP_VERIFIER_ENABLED", True)
    if not enabled or not _synth()._is_deep_research_run(state):
        return {"enabled": False, "checked": False, "unsupported_claims": []}

    candidate_text = str(generated_text or "").strip()
    if not candidate_text:
        return {"enabled": True, "checked": False, "unsupported_claims": [], "reason": "empty_text"}

    max_issues = max(1, _synth()._env_int("LANGGRAPH_DEEP_VERIFIER_MAX_ISSUES", 6))
    verifier_tokens = max(256, _synth()._env_int("LANGGRAPH_DEEP_VERIFIER_MAX_TOKENS", 900))
    retry_attempts = 0

    try:
        from backend.llm_config import create_llm
    except Exception as exc:
        logger.warning("[Synthesize/verifier] create_llm unavailable: %s", exc)
        return {"enabled": True, "checked": False, "unsupported_claims": [], "error": str(exc)}

    def _new_verifier_llm():
        try:
            return create_llm(
                temperature=0.0,
                max_tokens=verifier_tokens,
                request_timeout=_synth()._DEEP_VERIFIER_MAX_REQUEST_TIMEOUT_SEC,
                max_retries=0,
            )
        except TypeError:
            # Test doubles may only accept `temperature`.
            return create_llm(temperature=0.0)

    verifier_llm = _new_verifier_llm()

    current_date = utc_now_iso()[:10]
    prompt = f"""你是金融报告事实核查员，只做一件事：识别报告中缺少证据支撑的“事实性断言”。

当前日期：{current_date}

<report>
{candidate_text[:9000]}
</report>

<evidence>
{str(grounding_text or '')[:16000]}
</evidence>

核查规则：
1) 只检查“事实性断言”（数字、日期、产品发布、并购、监管事件等）。
2) 若 evidence 中找不到直接支撑，标记 unsupported。
3) 主观判断/泛化表述（如“竞争加剧”）不算 unsupported。
4) 输出最多 {max_issues} 条。

【高优先级核查目标】——以下格式断言无论语气多肯定，必须严格比对 evidence：
- 带时间戳的事件：「XXX发布（2月底）」「XXX推出（2026Q1）」「XXX于N月完成/落地」
- 产品/模型版本号 + 具体时间（如「Gemini 1.5模型发布（2月底）」）
- 并购/合作/融资 + 季度/月份时间戳
如 evidence 中无该时间+事件的明确对应记录，必须标记为 unsupported。

仅输出 JSON：
{{
  "unsupported_claims": [
    {{"claim": "...", "reason": "..."}}
  ]
}}"""

    def _on_retry(attempt: int, _exc: BaseException) -> None:
        nonlocal retry_attempts
        retry_attempts = max(retry_attempts, int(attempt))

    try:
        resp = await ainvoke_with_rate_limit_retry(
            verifier_llm,
            [HumanMessage(content=prompt)],
            llm_factory=_new_verifier_llm,
            acquire_token=True,
            agent_name="deep_report_verifier",
            max_attempts=_synth()._DEEP_VERIFIER_MAX_ATTEMPTS,
            acquire_timeout_seconds=float(_synth()._DEEP_VERIFIER_MAX_ACQUIRE_TIMEOUT_SEC),
            on_retry=_on_retry,
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        payload = json.loads(_synth()._extract_json_object(str(content)))
        claims = _normalize_verifier_claims(payload.get("unsupported_claims"), max_items=max_issues)
        return {
            "enabled": True,
            "checked": True,
            "retry_attempts": retry_attempts,
            "unsupported_claims": claims,
        }
    except Exception as exc:
        logger.warning("[Synthesize/verifier] verification failed: %s", exc)
        return {
            "enabled": True,
            "checked": False,
            "retry_attempts": retry_attempts,
            "unsupported_claims": [],
            "error": str(exc)[:300],
        }
