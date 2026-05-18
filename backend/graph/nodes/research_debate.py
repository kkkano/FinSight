# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Any

from backend.graph.state import GraphState


def _env_enabled(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


async def research_debate(state: GraphState) -> dict[str, Any]:
    """在证据账本之上生成确定性的多空辩论 artifact。"""
    if not _env_enabled("DEBATE_GRAPH_ENABLED", "false"):
        return {}

    artifacts = dict(state.get("artifacts") or {})
    trace = dict(state.get("trace") or {})
    ledger = artifacts.get("evidence_ledger")
    if not isinstance(ledger, dict) or not ledger:
        artifacts["debate"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "missing_evidence_ledger",
        }
        trace["research_debate"] = {"enabled": True, "status": "skipped", "reason": "missing_evidence_ledger"}
        return {"artifacts": artifacts, "trace": trace}

    from backend.research.debate import build_debate_artifact

    try:
        debate = build_debate_artifact(ledger, query=str(state.get("query") or ""))
        artifacts["debate"] = debate
        scorecard = debate.get("judge_scorecard") if isinstance(debate.get("judge_scorecard"), dict) else {}
        trace["research_debate"] = {
            "enabled": True,
            "status": "done",
            "evidence_balance": scorecard.get("evidence_balance"),
            "claim_count": scorecard.get("claim_count"),
            "source_count": scorecard.get("source_count"),
        }
    except Exception as exc:
        artifacts["debate"] = {
            "enabled": True,
            "status": "error",
            "reason": str(exc)[:300],
        }
        trace["research_debate"] = {"enabled": True, "status": "error", "reason": str(exc)[:300]}
    return {"artifacts": artifacts, "trace": trace}


__all__ = ["research_debate"]
