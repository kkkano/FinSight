# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
import logging
import os
import time
from typing import Any, Iterable, Mapping

from backend.graph.event_bus import emit_event

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def _serialize_agent_output(output: Any, *, step_name: str) -> dict[str, Any]:
    if output is None:
        return {"agent_name": step_name, "summary": "", "evidence": []}

    if isinstance(output, dict):
        return output

    if is_dataclass(output):
        try:
            payload = asdict(output)
            if isinstance(payload, dict):
                payload.setdefault("agent_name", step_name)
                return payload
        except Exception:
            pass

    summary = getattr(output, "summary", "")
    evidence = getattr(output, "evidence", None) or []
    confidence = getattr(output, "confidence", None)
    as_of = getattr(output, "as_of", None)
    evidence_quality = getattr(output, "evidence_quality", None)
    data_sources = getattr(output, "data_sources", None)
    fallback_used = getattr(output, "fallback_used", None)
    risks = getattr(output, "risks", None)
    trace = getattr(output, "trace", None)

    serialized_evidence: list[dict[str, Any]] = []
    for item in evidence[:12]:
        if isinstance(item, dict):
            serialized_evidence.append(item)
            continue
        if is_dataclass(item):
            try:
                serialized_evidence.append(asdict(item))
                continue
            except Exception:
                pass
        serialized_evidence.append(
            {
                "text": getattr(item, "text", None) or str(item),
                "source": getattr(item, "source", None),
                "url": getattr(item, "url", None),
                "timestamp": getattr(item, "timestamp", None),
                "confidence": getattr(item, "confidence", None),
                "title": getattr(item, "title", None),
                "meta": getattr(item, "meta", None),
            }
        )

    return {
        "agent_name": getattr(output, "agent_name", None) or step_name,
        "summary": summary,
        "confidence": confidence,
        "as_of": as_of,
        "evidence_quality": evidence_quality,
        "data_sources": data_sources,
        "fallback_used": fallback_used,
        "risks": risks,
        "trace": trace,
        "evidence": serialized_evidence,
    }


def _classify_exception(exc: Exception) -> tuple[str, bool, str]:
    """Classify an exception into (fallback_reason, retryable, error_stage).

    Returns
    -------
    fallback_reason : str
        One of: rate_limit_timeout | execution_error | confidence_skip | budget_exceeded
    retryable : bool
    error_stage : str
        One of: token_acquire | llm_invoke | parse | tool | unknown
    """
    exc_name = type(exc).__name__.lower()
    exc_msg = str(exc).lower()

    # Timeout → likely waiting for rate-limit token
    if isinstance(exc, asyncio.TimeoutError):
        return "rate_limit_timeout", True, "token_acquire"

    # Known rate-limit / quota errors from LLM providers
    rate_limit_keywords = ("rate_limit", "ratelimit", "429", "quota", "too many requests", "resource_exhausted")
    if any(kw in exc_name or kw in exc_msg for kw in rate_limit_keywords):
        return "rate_limit_timeout", True, "llm_invoke"

    # Parse / validation errors
    parse_keywords = ("json", "parse", "decode", "validation", "pydantic", "schema")
    if any(kw in exc_name or kw in exc_msg for kw in parse_keywords):
        return "execution_error", False, "parse"

    # Tool / data source errors
    tool_keywords = ("api", "request", "connection", "http", "socket", "fetch", "tool")
    if any(kw in exc_name or kw in exc_msg for kw in tool_keywords):
        return "execution_error", True, "tool"

    # Fallback
    return "execution_error", False, "unknown"


def _build_agent_fallback_output(
    *,
    step_name: str,
    query: str,
    ticker: str,
    error: str,
    fallback_reason: str = "execution_error",
    retryable: bool = False,
    error_stage: str = "unknown",
) -> dict[str, Any]:
    safe_query = str(query or "").strip()[:160]
    safe_ticker = str(ticker or "N/A").strip().upper() or "N/A"
    safe_error = str(error or "unknown")[:300]
    summary = (
        f"{step_name} 已降级：{safe_ticker} 的分析暂不可用，"
        f"系统已返回最小可用结果（query={safe_query or 'N/A'}）。"
    )
    return {
        "agent_name": step_name,
        "summary": summary,
        "confidence": 0.2,
        "as_of": None,
        "evidence_quality": {"overall_score": 0.0, "fallback": True},
        "data_sources": ["agent_fallback"],
        "fallback_used": True,
        "fallback_reason": fallback_reason,
        "retryable": retryable,
        "error_stage": error_stage,
        "risks": [
            "当前 Agent 执行失败，结果已降级，请稍后重试。",
            f"错误摘要: {safe_error}",
        ],
        "trace": [{"event": "agent_fallback", "agent": step_name, "error": safe_error}],
        "evidence": [],
    }


def _normalize_agent_output(*, step_name: str, output: Any, query: str, ticker: str) -> dict[str, Any]:
    payload = _serialize_agent_output(output, step_name=step_name)
    if not isinstance(payload, dict):
        return _build_agent_fallback_output(
            step_name=step_name,
            query=query,
            ticker=ticker,
            error="invalid_agent_output",
        )

    payload["agent_name"] = step_name

    summary = str(payload.get("summary") or "").strip()
    if not summary:
        return _build_agent_fallback_output(
            step_name=step_name,
            query=query,
            ticker=ticker,
            error="empty_summary",
        )
    payload["summary"] = summary[:5000]

    try:
        confidence = float(payload.get("confidence", 0.3))
    except Exception:
        confidence = 0.3
    payload["confidence"] = max(0.0, min(1.0, confidence))

    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    payload["evidence"] = evidence[:20]

    data_sources = payload.get("data_sources")
    if not isinstance(data_sources, list):
        data_sources = []
    data_sources = [str(item).strip() for item in data_sources if str(item).strip()]
    payload["data_sources"] = data_sources or ["unknown"]

    payload["fallback_used"] = bool(payload.get("fallback_used", False))
    # Preserve structured fallback fields if present
    if "fallback_reason" not in payload:
        payload["fallback_reason"] = None
    if "retryable" not in payload:
        payload["retryable"] = None
    if "error_stage" not in payload:
        payload["error_stage"] = None
    risks = payload.get("risks")
    if not isinstance(risks, list):
        risks = []
    risks = [str(item).strip() for item in risks if str(item).strip()]
    if payload["fallback_used"] and not risks:
        risks = ["Agent 触发降级路径，建议复核关键数据。"]
    payload["risks"] = risks

    trace = payload.get("trace")
    if not isinstance(trace, list):
        payload["trace"] = []

    return payload


def build_agent_invokers(*, allowed_agents: Iterable[str], state: Mapping[str, Any]) -> dict[str, Any]:
    """
    Build best-effort invokers for legacy specialist agents.

    Node layer should call this adapter only; direct imports stay isolated here.
    """
    names = [str(n).strip() for n in (allowed_agents or []) if str(n).strip()]
    if not names:
        return {}

    try:  # pragma: no cover - runtime dependency path
        from backend.orchestration.cache import DataCache
        import backend.tools as tools_module

        from backend.agents.deep_search_agent import DeepSearchAgent
        from backend.agents.fundamental_agent import FundamentalAgent
        from backend.agents.macro_agent import MacroAgent
        from backend.agents.news_agent import NewsAgent
        from backend.agents.price_agent import PriceAgent
        from backend.agents.technical_agent import TechnicalAgent
    except Exception:
        logger.exception("agent adapter failed to import legacy agents")
        return {}

    llm = None
    try:  # pragma: no cover - runtime dependency path
        from backend.llm_config import create_llm

        llm = create_llm(temperature=float(os.getenv("LANGGRAPH_AGENT_TEMPERATURE", "0.2")))
    except Exception:
        llm = None

    cache = DataCache()
    agent_classes: dict[str, Any] = {
        "price_agent": PriceAgent,
        "news_agent": NewsAgent,
        "fundamental_agent": FundamentalAgent,
        "technical_agent": TechnicalAgent,
        "macro_agent": MacroAgent,
        "deep_search_agent": DeepSearchAgent,
    }

    subject = state.get("subject") if isinstance(state, Mapping) else {}
    subject = subject if isinstance(subject, dict) else {}
    subject_tickers = subject.get("tickers")
    subject_tickers = subject_tickers if isinstance(subject_tickers, list) else []
    default_ticker = (subject_tickers or [None])[0]
    default_ticker = (
        str(default_ticker).strip().upper()
        if isinstance(default_ticker, str) and default_ticker.strip()
        else ""
    )
    default_query = str(state.get("query") or "").strip()

    agents: dict[str, Any] = {}
    init_errors: dict[str, str] = {}
    for name in names:
        cls = agent_classes.get(name)
        if not cls:
            init_errors[name] = "agent_class_not_found"
            continue
        try:
            agents[name] = cls(llm, cache, tools_module)
        except Exception as exc:
            logger.exception("agent adapter failed to instantiate %s", name)
            init_errors[name] = f"init_failed:{exc.__class__.__name__}"

    invokers: dict[str, Any] = {}
    timeout_seconds = max(15.0, _env_float("LANGGRAPH_AGENT_INVOKER_TIMEOUT_SECONDS", 180.0))
    deep_search_timeout_seconds = max(
        timeout_seconds,
        _env_float("LANGGRAPH_DEEP_SEARCH_AGENT_TIMEOUT_SECONDS", timeout_seconds),
    )
    max_attempts = max(1, _env_int("LANGGRAPH_AGENT_INVOKER_RETRY_ATTEMPTS", 2))

    for name in names:
        agent = agents.get(name)
        init_error = init_errors.get(name)

        async def _invoke(inputs: dict[str, Any], *, _agent=agent, _name=name, _init_error=init_error) -> dict[str, Any]:
            query = inputs.get("query") if isinstance(inputs, dict) else None
            query = str(query).strip() if isinstance(query, str) and query.strip() else default_query
            ticker = inputs.get("ticker") if isinstance(inputs, dict) else None
            ticker = (
                str(ticker).strip().upper()
                if isinstance(ticker, str) and ticker.strip()
                else default_ticker
            )
            if not ticker:
                ticker = "N/A"

            await emit_event({
                "type": "agent_start",
                "agent": _name,
                "query": query,
                "ticker": ticker,
                "attempt": 1,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

            if _agent is None:
                return _build_agent_fallback_output(
                    step_name=_name,
                    query=query,
                    ticker=ticker,
                    error=_init_error or "agent_not_available",
                )

            last_error = "unknown"
            last_reason = "execution_error"
            last_retryable = False
            last_stage = "unknown"
            for attempt in range(1, max_attempts + 1):
                try:
                    invoke_timeout = (
                        deep_search_timeout_seconds if _name == "deep_search_agent" else timeout_seconds
                    )
                    result = await asyncio.wait_for(
                        _agent.research(query=query or "N/A", ticker=ticker),
                        timeout=invoke_timeout,
                    )
                    normalized = _normalize_agent_output(
                        step_name=_name,
                        output=result,
                        query=query,
                        ticker=ticker,
                    )
                    if normalized.get("summary"):
                        await emit_event({
                            "type": "agent_done",
                            "agent": _name,
                            "status": "success",
                            "confidence": normalized.get("confidence", 0),
                            "data_sources": normalized.get("data_sources", []),
                            "summary_length": len(normalized.get("summary", "")),
                            "evidence_count": len(normalized.get("evidence", [])),
                            "attempt": attempt,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        })
                        return normalized
                    last_error = "empty_summary"
                    last_reason = "confidence_skip"
                    last_retryable = False
                    last_stage = "parse"
                except Exception as exc:
                    last_error = f"{exc.__class__.__name__}: {exc}"
                    last_reason, last_retryable, last_stage = _classify_exception(exc)
                    await emit_event({
                        "type": "agent_error",
                        "agent": _name,
                        "error": str(exc)[:300],
                        "error_type": exc.__class__.__name__,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "retryable": last_retryable,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })
                    if attempt < max_attempts:
                        log_fn = logger.info if last_retryable else logger.warning
                        log_fn(
                            "[AgentAdapter] %s attempt %d/%d failed (%s/%s), retrying: %s",
                            _name,
                            attempt,
                            max_attempts,
                            last_reason,
                            last_stage,
                            exc,
                        )
                        continue

            await emit_event({
                "type": "agent_done",
                "agent": _name,
                "status": "fallback",
                "fallback_reason": last_reason,
                "error": last_error[:200],
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return _build_agent_fallback_output(
                step_name=_name,
                query=query,
                ticker=ticker,
                error=last_error,
                fallback_reason=last_reason,
                retryable=last_retryable,
                error_stage=last_stage,
            )

        invokers[name] = _invoke

    return invokers


__all__ = ["build_agent_invokers"]
