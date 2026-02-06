# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import logging
import os
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


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
        "data_sources": data_sources,
        "fallback_used": fallback_used,
        "risks": risks,
        "trace": trace,
        "evidence": serialized_evidence,
    }


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
    for name in names:
        cls = agent_classes.get(name)
        if not cls:
            continue
        try:
            agents[name] = cls(llm, cache, tools_module)
        except Exception:
            logger.exception("agent adapter failed to instantiate %s", name)

    invokers: dict[str, Any] = {}
    for name, agent in agents.items():

        async def _invoke(inputs: dict[str, Any], *, _agent=agent, _name=name) -> dict[str, Any]:
            query = inputs.get("query") if isinstance(inputs, dict) else None
            query = str(query).strip() if isinstance(query, str) and query.strip() else default_query
            ticker = inputs.get("ticker") if isinstance(inputs, dict) else None
            ticker = (
                str(ticker).strip().upper()
                if isinstance(ticker, str) and ticker.strip()
                else default_ticker
            )
            if not ticker:
                raise ValueError(f"agent step missing ticker: {_name}")

            result = await _agent.research(query=query or "N/A", ticker=ticker)
            return _serialize_agent_output(result, step_name=_name)

        invokers[name] = _invoke

    return invokers


__all__ = ["build_agent_invokers"]

