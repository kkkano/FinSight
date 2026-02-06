# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import Any

from backend.graph.adapters import (
    build_agent_invokers as _build_agent_invokers,
    build_tool_invokers as _build_tool_invokers,
)
from backend.graph.executor import execute_plan
from backend.graph.failure import FAILURE_STRATEGY_VERSION
from backend.graph.state import GraphState


def build_tool_invokers(allowed_tools: list[str]) -> dict[str, Any]:
    return _build_tool_invokers(allowed_tools=allowed_tools or [])


def build_agent_invokers(allowed_agents: list[str], state: GraphState) -> dict[str, Any]:
    # Backward-compatible wrapper for tests that monkeypatch this symbol.
    return _build_agent_invokers(allowed_agents=allowed_agents or [], state=state)


async def execute_plan_stub(state: GraphState) -> dict:
    """
    Phase 3 executor scaffold:
    - Runs the step scheduler (parallel_group + cache + optional failures)
    - Default: dry-run (no live tool calls) to keep behavior deterministic
    """
    trace = state.get("trace") or {}

    plan_ir = state.get("plan_ir") or {}

    live_tools = os.getenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false").lower() in ("true", "1", "yes", "on")

    tool_invokers = None
    agent_invokers = None
    if live_tools:
        policy = state.get("policy") or {}
        allowed_tools = policy.get("allowed_tools") if isinstance(policy, dict) else []
        allowed_agents = policy.get("allowed_agents") if isinstance(policy, dict) else []
        tool_invokers = build_tool_invokers(list(allowed_tools or []))
        agent_invokers = build_agent_invokers(list(allowed_agents or []), state)

    artifacts, exec_events = await execute_plan(
        plan_ir,
        tool_invokers=tool_invokers,
        agent_invokers=agent_invokers,
        dry_run=not live_tools,
    )

    # Phase 4: build a unified evidence_pool from selection (ephemeral, request-scoped).
    subject = state.get("subject") or {}
    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    evidence_pool: list[dict[str, Any]] = []
    if isinstance(selection_payload, list) and selection_payload:
        for item in selection_payload:
            if not isinstance(item, dict):
                continue
            evidence_pool.append(
                {
                    "title": item.get("title") or item.get("headline") or "",
                    "url": item.get("url"),
                    "snippet": item.get("snippet") or item.get("summary"),
                    "source": item.get("source") or "selection",
                    "published_date": item.get("ts") or item.get("datetime") or item.get("published_at"),
                    "confidence": item.get("confidence", 0.7),
                    "type": item.get("type") or "selection",
                    "id": item.get("id"),
                }
            )

    # Phase 4.2+: merge tool outputs into evidence_pool (best-effort normalization).
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else None
    step_index = {s.get("id"): s for s in (steps or []) if isinstance(s, dict) and s.get("id")}

    def _append_tool_evidence(tool_name: str, step_id: str, output: Any) -> None:
        if output is None:
            return
        if isinstance(output, dict) and output.get("skipped"):
            return

        # Some tools return JSON text (e.g. get_company_news). Try to parse.
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
                output = parsed
            except Exception:
                pass

        # Special-case: make technical snapshot readable in evidence list.
        if tool_name == "get_technical_snapshot" and isinstance(output, dict):
            if output.get("error"):
                evidence_pool.append(
                    {
                        "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                        "url": None,
                        "snippet": f"error={output.get('error')} points={output.get('points','N/A')}",
                        "source": tool_name,
                        "published_date": output.get("as_of"),
                        "confidence": 0.7,
                        "type": "tool",
                        "id": output.get("id") or f"{tool_name}:{step_id}",
                    }
                )
                return

            parts = []
            if output.get("close") is not None:
                parts.append(f"close={output.get('close')}")
            if output.get("ma20") is not None:
                parts.append(f"MA20={output.get('ma20')}")
            if output.get("ma50") is not None:
                parts.append(f"MA50={output.get('ma50')}")
            if output.get("rsi14") is not None:
                parts.append(f"RSI14={output.get('rsi14')}({output.get('rsi_state')})")
            if output.get("macd") is not None and output.get("macd_signal") is not None:
                parts.append(f"MACD={output.get('macd')} vs {output.get('macd_signal')}({output.get('momentum')})")
            if output.get("trend"):
                parts.append(f"trend={output.get('trend')}")

            evidence_pool.append(
                {
                    "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                    "url": None,
                    "snippet": " | ".join(parts) if parts else None,
                    "source": output.get("source") or tool_name,
                    "published_date": output.get("as_of"),
                    "confidence": 0.75,
                    "type": "tool",
                    "id": output.get("id") or f"{tool_name}:{step_id}",
                }
            )
            return

        if isinstance(output, list):
            for i, item in enumerate(output[:10]):
                if not isinstance(item, dict):
                    continue
                evidence_pool.append(
                    {
                        "title": item.get("title") or item.get("headline") or f"{tool_name} result {i+1}",
                        "url": item.get("url"),
                        "snippet": item.get("snippet") or item.get("summary") or item.get("content"),
                        "source": item.get("source") or tool_name,
                        "published_date": item.get("published_date") or item.get("published_at") or item.get("datetime"),
                        "confidence": item.get("confidence", 0.6),
                        "type": item.get("type") or "tool",
                        "id": item.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        snippet = json.dumps(output, ensure_ascii=False) if isinstance(output, (dict,)) else str(output)
        evidence_pool.append(
            {
                "title": f"{tool_name} output",
                "url": None,
                "snippet": snippet[:800],
                "source": tool_name,
                "published_date": None,
                "confidence": 0.6,
                "type": "tool",
                "id": f"{tool_name}:{step_id}",
            }
        )

    def _append_agent_evidence(agent_name: str, step_id: str, output: Any) -> None:
        if output is None:
            return
        if isinstance(output, dict) and output.get("skipped"):
            return

        if isinstance(output, str):
            try:
                output = json.loads(output)
            except Exception:
                output = {"summary": output}

        if not isinstance(output, dict):
            evidence_pool.append(
                {
                    "title": f"{agent_name} output",
                    "url": None,
                    "snippet": str(output)[:800],
                    "source": agent_name,
                    "published_date": None,
                    "confidence": 0.5,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}",
                }
            )
            return

        summary = output.get("summary")
        confidence_base = output.get("confidence", 0.6)
        as_of = output.get("as_of")

        if isinstance(summary, str) and summary.strip():
            evidence_pool.append(
                {
                    "title": f"{agent_name} summary",
                    "url": None,
                    "snippet": summary.strip()[:800],
                    "source": agent_name,
                    "published_date": as_of,
                    "confidence": confidence_base if isinstance(confidence_base, (int, float)) else 0.6,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}:summary",
                }
            )

        evidence = output.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return

        for i, item in enumerate(evidence[:10]):
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            snippet = item.get("text") or item.get("snippet") or item.get("summary")
            if not snippet:
                continue
            source = item.get("source") or agent_name
            evidence_pool.append(
                {
                    "title": item.get("title") or f"{agent_name} evidence {i+1}",
                    "url": item.get("url"),
                    "snippet": str(snippet).strip()[:800],
                    "source": source,
                    "published_date": item.get("timestamp") or as_of,
                    "confidence": item.get("confidence", confidence_base if isinstance(confidence_base, (int, float)) else 0.6),
                    "type": "agent",
                    "id": item.get("id") or f"{agent_name}:{step_id}:{i+1}",
                }
            )

    if isinstance(step_results, dict) and step_results:
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") != "tool":
                if step.get("kind") == "agent":
                    agent_name = step.get("name") or ""
                    if agent_name:
                        _append_agent_evidence(str(agent_name), str(step_id), item.get("output"))
                continue
            tool_name = step.get("name") or ""
            if not tool_name:
                continue
            _append_tool_evidence(str(tool_name), str(step_id), item.get("output"))

    # Dedupe by url or title+source
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in evidence_pool:
        if not isinstance(e, dict):
            continue
        key = e.get("url") or f"{e.get('title')}|{e.get('source')}"
        if not key or key in seen:
            continue
        seen.add(str(key))
        deduped.append(e)
    artifacts["evidence_pool"] = deduped

    trace.update(
        {
            "executor": {
                "type": "dry_run" if not live_tools else "live_tools",
                "ran_steps": len((plan_ir.get("steps") or []) if isinstance(plan_ir, dict) else []),
                "error_count": len((artifacts.get("errors") or []) if isinstance(artifacts, dict) else []),
                "failure_strategy_version": FAILURE_STRATEGY_VERSION,
                "events": exec_events,
            }
        }
    )
    return {"artifacts": artifacts, "trace": trace}
