# -*- coding: utf-8 -*-
"""Execute-plan orchestration entrypoint."""
from __future__ import annotations

import logging
from typing import Any

from backend.config.settings import executor_settings
from backend.graph.adapters import (
    build_agent_invokers as _build_agent_invokers,
    build_tool_invokers as _build_tool_invokers,
)
from backend.graph.dag_executor import execute_plan_dag
from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.executor import execute_plan
from backend.graph.failure import FAILURE_STRATEGY_VERSION
from backend.graph.state import GraphState
from backend.rag.execution_pipeline import run_execution_rag_pipeline
from backend.rag.execution_support import (
    _build_chunk_record_id,
    _build_rag_run_id,
    _build_source_doc_content,
    _build_source_doc_obs_id,
    _build_vector_source_id,
    _chunk_profile,
    _decorate_rag_hit,
    _bounded_env_int as _env_int,
    _HIGH_RELIABILITY_SOURCE_HINTS,
    _infer_chunk_doc_type,
    _infer_chunk_strategy,
    _parse_datetime,
    _resolve_rag_user_id,
    _resolve_session_id,
    _safe_event_payload,
    _stable_id,
)
from backend.rag.ingestion import (
    _build_memory_context_specs,
    _build_rag_doc_id,
    _collection_from_thread_id,
    _estimate_source_reliability,
    _kb_collection_from_subject,
    _memory_collection_from_thread,
    _normalize_memory_focus_list,
    _normalize_watchlist_items,
    _resolve_hit_layer,
    _sanitize_collection_segment,
    _summarize_layer_hits,
    _ttl_hours_for_evidence,
)
from backend.rag.layering import (
    build_kb_vector_source_id,
    build_subject_kb_collection,
    build_thread_memory_collection,
    build_thread_working_set_collection,
    collection_details,
    compute_doc_fingerprint,
    enrich_metadata,
    is_long_term_candidate,
    preferred_retrieval_collections,
)


__all__ = [
    "_build_chunk_record_id",
    "_build_memory_context_specs",
    "_build_rag_doc_id",
    "_build_rag_run_id",
    "_build_source_doc_content",
    "_build_source_doc_obs_id",
    "_build_vector_source_id",
    "_chunk_profile",
    "_collection_from_thread_id",
    "_decorate_rag_hit",
    "_env_int",
    "_estimate_source_reliability",
    "_HIGH_RELIABILITY_SOURCE_HINTS",
    "_infer_chunk_doc_type",
    "_infer_chunk_strategy",
    "_kb_collection_from_subject",
    "_memory_collection_from_thread",
    "_normalize_memory_focus_list",
    "_normalize_watchlist_items",
    "_parse_datetime",
    "_resolve_hit_layer",
    "_resolve_rag_user_id",
    "_resolve_session_id",
    "_safe_event_payload",
    "_sanitize_collection_segment",
    "_stable_id",
    "_summarize_layer_hits",
    "_ttl_hours_for_evidence",
    "build_agent_invokers",
    "build_kb_vector_source_id",
    "build_subject_kb_collection",
    "build_thread_memory_collection",
    "build_thread_working_set_collection",
    "build_tool_invokers",
    "collection_details",
    "compute_doc_fingerprint",
    "enrich_metadata",
    "execute_plan_node",
    "is_long_term_candidate",
    "preferred_retrieval_collections",
]


logger = logging.getLogger(__name__)


def build_tool_invokers(allowed_tools: list[str]) -> dict[str, Any]:
    return _build_tool_invokers(allowed_tools=allowed_tools or [])


def build_agent_invokers(allowed_agents: list[str], state: GraphState) -> dict[str, Any]:
    # Backward-compatible wrapper for tests that monkeypatch this symbol.
    return _build_agent_invokers(allowed_agents=allowed_agents or [], state=state)


_EXECUTION_OWNED_ARTIFACT_KEYS = {
    "agent_diagnostics",
    "brief_data",
    "draft_markdown",
    "errors",
    "evidence_by_task",
    "evidence_ledger",
    "evidence_pool",
    "rag_context",
    "rag_stats",
    "render_vars",
    "response",
    "signals",
    "step_results",
    "task_results",
    "tool_diagnostics",
    "verifier_result",
}


def _merge_prior_artifacts(prior: Any, current: Any) -> dict[str, Any]:
    if not isinstance(prior, dict):
        prior = {}
    if not isinstance(current, dict):
        current = {}
    preserved = {key: value for key, value in prior.items() if key not in _EXECUTION_OWNED_ARTIFACT_KEYS}
    return {**preserved, **current}


async def execute_plan_node(state: GraphState) -> dict:
    """Run the plan scheduler and assemble execution-scoped artifacts."""
    trace = state.get("trace") or {}
    plan_ir = state.get("plan_ir") or {}
    settings = executor_settings()
    live_tools = settings.live_tools

    tool_invokers = None
    agent_invokers = None
    if live_tools:
        policy = state.get("policy") or {}
        allowed_tools = policy.get("allowed_tools") if isinstance(policy, dict) else []
        allowed_agents = policy.get("allowed_agents") if isinstance(policy, dict) else []
        tool_invokers = build_tool_invokers(list(allowed_tools or []))
        agent_invokers = build_agent_invokers(list(allowed_agents or []), state)

    if settings.dag_executor:
        context_bus: dict[str, str] | None = (
            {} if settings.evidence_bus else None
        )
        artifacts, exec_events = await execute_plan_dag(
            plan_ir,
            tool_invokers=tool_invokers,
            agent_invokers=agent_invokers,
            dry_run=not live_tools,
            context_bus=context_bus,
        )
    else:
        artifacts, exec_events = await execute_plan(
            plan_ir,
            tool_invokers=tool_invokers,
            agent_invokers=agent_invokers,
            dry_run=not live_tools,
        )
    artifacts = _merge_prior_artifacts(state.get("artifacts"), artifacts)

    deduped, step_index, evidence_input_count = normalize_execution_evidence(
        state=state,
        plan_ir=plan_ir,
        artifacts=artifacts,
    )
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    rag_trace = await run_execution_rag_pipeline(
        state=state,
        subject=subject,
        deduped=deduped,
        step_index=step_index,
        artifacts=artifacts,
        evidence_input_count=evidence_input_count,
    )

    if settings.research_ledger_enabled:
        try:
            from backend.research.ledger_builder import build_ledger_from_artifacts

            artifacts["evidence_ledger"] = build_ledger_from_artifacts(state, artifacts)
        except Exception as exc:
            logger.warning("Evidence ledger build failed: %s", exc)
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
    trace["rag"] = rag_trace
    return {"artifacts": artifacts, "trace": trace}
