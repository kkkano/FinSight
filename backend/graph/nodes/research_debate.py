# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.graph.state import GraphState
from backend.prompts.risk_challenge import RISK_CHALLENGE_SYSTEM_PROMPT


def _env_enabled(name: str, default: str = "true") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


class RiskChallenge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_agent: str = Field(min_length=1, max_length=80)
    challenge_zh: str = Field(min_length=1, max_length=80)
    severity: Literal["low", "med", "high"]


def _extract_json_array(raw: str) -> list[Any]:
    text = str(raw or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("challenge round did not return JSON array")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, list):
        raise ValueError("challenge round payload must be a list")
    return payload


async def _generate_challenges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm

    response = await asyncio.wait_for(
        ainvoke_configured_llm(
            [
                SystemMessage(content=RISK_CHALLENGE_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            context=LLMCallContext.create(
                stage="research_debate", agent="research_debate", layer="analysis", max_provider_attempts=2,
            ),
            temperature=0.0,
            max_tokens=600,
            request_timeout=12,
        ),
        timeout=15,
    )
    raw = response.content if hasattr(response, "content") else str(response)
    return [
        RiskChallenge.model_validate(item).model_dump()
        for item in _extract_json_array(raw)[:3]
    ]


def _agent_challenge_payload(state: GraphState) -> dict[str, Any]:
    plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    agents: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("kind") != "agent":
            continue
        agent_name = str(step.get("name") or "").strip()
        step_id = str(step.get("id") or "").strip()
        raw = step_results.get(step_id) if step_id else None
        output = raw.get("output") if isinstance(raw, dict) else None
        if not agent_name or not isinstance(output, dict) or output.get("skipped") is True:
            continue
        summary = str(output.get("summary") or output.get("analysis") or "").strip()
        if not summary:
            continue
        evidence = output.get("evidence") if isinstance(output.get("evidence"), list) else []
        evidence_titles = []
        for item in evidence[:8]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("text") or "").strip()
            if title:
                evidence_titles.append(title[:180])
        agents.append(
            {
                "agent": agent_name,
                "summary": summary[:1200],
                "evidence_titles": evidence_titles,
            }
        )
    return {"query": str(state.get("query") or ""), "agents": agents}


async def research_debate(state: GraphState) -> dict[str, Any]:
    """由风险分析师对多 Agent 投资报告执行一次受限结构化质询。"""
    if not _env_enabled("DEBATE_GRAPH_ENABLED", "true"):
        return {}

    artifacts = dict(state.get("artifacts") or {})
    trace = dict(state.get("trace") or {})
    if str(state.get("output_mode") or "") != "investment_report":
        trace["research_debate"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "not_investment_report",
        }
        return {"artifacts": artifacts, "trace": trace}

    payload = _agent_challenge_payload(state)
    agent_names = {
        str(item.get("agent") or "")
        for item in payload.get("agents", [])
        if isinstance(item, dict)
    }
    if len(agent_names) < 3:
        trace["research_debate"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "insufficient_agent_outputs",
            "agent_count": len(agent_names),
        }
        return {"artifacts": artifacts, "trace": trace}

    try:
        raw_challenges = await _generate_challenges(payload)
        challenges = []
        for item in raw_challenges[:3]:
            challenge = RiskChallenge.model_validate(item)
            if challenge.target_agent not in agent_names or challenge.target_agent == "risk_agent":
                raise ValueError("challenge target must be a participating non-risk agent")
            challenges.append(challenge.model_dump())
        if not challenges:
            raise ValueError("challenge round returned no valid challenges")

        ledger = artifacts.get("evidence_ledger")
        if isinstance(ledger, dict) and ledger:
            from backend.research.debate import build_debate_artifact

            debate = build_debate_artifact(
                ledger,
                query=str(state.get("query") or ""),
                challenges=challenges,
            )
        else:
            debate = {
                "enabled": True,
                "status": "done",
                "query": str(state.get("query") or ""),
                "challenges": challenges,
            }
        artifacts["debate"] = debate
        trace["research_debate"] = {
            "enabled": True,
            "status": "done",
            "challenger": "risk_agent",
            "challenge_count": len(challenges),
            "agent_count": len(agent_names),
        }
    except Exception as exc:
        artifacts.pop("debate", None)
        trace["research_debate"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "challenge_round_failed",
            "error_type": type(exc).__name__,
        }
    return {"artifacts": artifacts, "trace": trace}


__all__ = ["RiskChallenge", "research_debate"]
