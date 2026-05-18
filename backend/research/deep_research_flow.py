# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from backend.agents.base_agent import AgentOutput
from backend.agents.search_convergence import SearchConvergence


DEEP_RESEARCH_STAGES = (
    "plan_search",
    "fetch_sources",
    "extract_claims",
    "gap_check",
    "targeted_followup",
    "ledger_write",
)


@dataclass
class DeepResearchStageResult:
    stage: str
    query: str
    source_count: int = 0
    claim_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "query": self.query,
            "source_count": self.source_count,
            "claim_count": self.claim_count,
            **({"details": self.details} if self.details else {}),
        }


@dataclass
class DeepResearchFlowResult:
    query: str
    ticker: str
    output: AgentOutput
    stages: list[DeepResearchStageResult]

    @property
    def stage_records(self) -> list[dict[str, Any]]:
        return [stage.model_dump() for stage in self.stages]


def _count_sources(docs: Any) -> int:
    return len(docs) if isinstance(docs, list) else 0


def _count_claims(output: AgentOutput | None = None, summary: str | None = None) -> int:
    if output is not None:
        return len(output.claims or [])
    return 1 if str(summary or "").strip() else 0


async def run_deep_research_flow(
    agent: Any,
    query: str,
    ticker: str,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> DeepResearchFlowResult:
    """Run DeepSearch through a stable evidence-research stage facade."""

    trace: list[dict[str, Any]] = []
    stages: list[DeepResearchStageResult] = []

    def _add_stage(
        stage: str,
        *,
        source_count: int = 0,
        claim_count: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        record = DeepResearchStageResult(
            stage=stage,
            query=query,
            source_count=source_count,
            claim_count=claim_count,
            details=details or {},
        )
        stages.append(record)
        if on_event:
            try:
                on_event(
                    {
                        "event": "deep_research_stage",
                        "agent": getattr(agent, "AGENT_NAME", "deep_search"),
                        "details": record.model_dump(),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except Exception:
                pass

    def _log_event(event_type: str, details: dict[str, Any]) -> None:
        event = agent._trace_step(event_type, details)
        trace.append(event)
        if on_event:
            try:
                on_event(
                    {
                        "event": "agent_execution",
                        "agent": getattr(agent, "AGENT_NAME", "deep_search"),
                        "details": {"type": event_type, **details},
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except Exception:
                pass

    def _notify(message: str) -> None:
        if on_event:
            try:
                on_event(
                    {
                        "event": "agent_action",
                        "agent": getattr(agent, "AGENT_NAME", "deep_search"),
                        "details": {"message": message},
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except Exception:
                pass

    queries = agent._build_queries(query, ticker)
    _add_stage("plan_search", details={"queries": queries})

    convergence = SearchConvergence()

    _notify(f"开始初始搜索 (Queries: {len(queries)})...")
    results = await agent._initial_search(query, ticker, queries=queries)
    _add_stage("fetch_sources", source_count=_count_sources(results), details={"queries": queries})

    _notify("正在生成初步摘要...")
    summary = await agent._first_summary(results)

    unique_results, init_metrics = convergence.process_round(results, "")
    _log_event(
        "initial_search",
        {
            **agent._build_trace_payload(queries, results),
            "convergence": {
                "round": init_metrics.round_num,
                "info_gain": init_metrics.info_gain,
                "unique_docs": init_metrics.unique_docs_count,
            },
        },
    )
    agent._log_documents(results, "initial")
    _log_event("summary", {"summary_preview": agent._trim_text(summary, 400)})
    _add_stage("extract_claims", source_count=_count_sources(unique_results), claim_count=_count_claims(summary=summary))

    all_docs: list[dict[str, Any]] = list(unique_results) if isinstance(unique_results, list) else []
    targeted_docs: list[dict[str, Any]] = []
    first_gap_recorded = False

    for index in range(getattr(agent, "MAX_REFLECTIONS", 0)):
        _notify(f"正在分析信息缺口 (Round {index + 1})...")
        gaps = await agent._identify_gaps(summary)
        _log_event("self_rag_gap_detection", {"needs_more": bool(gaps), "queries": gaps})
        if not first_gap_recorded:
            _add_stage(
                "gap_check",
                source_count=_count_sources(all_docs),
                claim_count=_count_claims(summary=summary),
                details={"gaps": gaps},
            )
            first_gap_recorded = True
        if not gaps:
            break

        _notify(f"执行针对性搜索 (Gaps: {len(gaps)})...")
        new_data = await agent._targeted_search(gaps, ticker)
        if isinstance(new_data, list) and new_data:
            unique_new, metrics = convergence.process_round(new_data, summary)
            _log_event(
                "targeted_search",
                {
                    **agent._build_trace_payload(gaps, new_data),
                    "convergence": {
                        "round": metrics.round_num,
                        "info_gain": metrics.info_gain,
                        "unique_docs": metrics.unique_docs_count,
                        "should_stop": metrics.should_stop,
                        "reason": metrics.reason,
                    },
                },
            )
            agent._log_documents(unique_new, "targeted")
            if isinstance(unique_new, list):
                all_docs.extend(unique_new)
                targeted_docs.extend(unique_new)
            if metrics.should_stop:
                break

        _notify("更新摘要整合新信息...")
        summary = await agent._update_summary(summary, new_data)
        _log_event("summary_update", {"summary_preview": agent._trim_text(summary, 400)})

    if not first_gap_recorded:
        _add_stage("gap_check", source_count=_count_sources(all_docs), claim_count=_count_claims(summary=summary), details={"gaps": []})

    _add_stage(
        "targeted_followup",
        source_count=_count_sources(targeted_docs),
        claim_count=_count_claims(summary=summary),
    )

    _log_event("convergence_final", convergence.get_stats())

    final_docs = all_docs or results
    evidence_quality = agent._compute_evidence_quality(final_docs)
    _log_event("evidence_quality", evidence_quality)

    rag_observability = await agent._record_rag_observability(query=query, ticker=ticker, docs=final_docs)
    if rag_observability:
        _log_event("rag_observability", rag_observability)

    output = agent._format_output(
        summary,
        final_docs,
        trace=trace,
        evidence_quality=evidence_quality,
        query=query,
        ticker=ticker,
    )
    _add_stage("ledger_write", source_count=len(output.evidence), claim_count=_count_claims(output=output))

    return DeepResearchFlowResult(query=query, ticker=ticker, output=output, stages=stages)
