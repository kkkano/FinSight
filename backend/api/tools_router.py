from __future__ import annotations

import os

from fastapi import APIRouter, Query

from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES
from backend.tools.manifest import TOOL_MANIFEST, select_tools


def create_tools_router() -> APIRouter:
    router = APIRouter(tags=["Tools"])

    @router.get("/api/tools/capabilities")
    async def list_tool_capabilities(
        market: str = Query("US", description="Market scope"),
        operation: str = Query("qa", description="Operation name"),
        analysis_depth: str = Query("report", description="Analysis depth"),
        output_mode: str = Query("brief", description="Output mode"),
    ):
        market_norm = str(market or "US").strip().upper() or "US"
        operation_norm = str(operation or "qa").strip().lower() or "qa"
        depth_norm = str(analysis_depth or "report").strip().lower() or "report"
        output_mode_norm = str(output_mode or "brief").strip().lower() or "brief"

        if depth_norm not in {"quick", "report", "deep_research"}:
            depth_norm = "report"

        selected_tools = select_tools(
            subject_type="company",
            operation_name=operation_norm,
            output_mode=output_mode_norm,
            analysis_depth=depth_norm,
            market=market_norm,
        )
        selected_set = set(selected_tools)

        tools: list[dict[str, object]] = []
        for entry in TOOL_MANIFEST:
            missing_env = [key for key in entry.requires_env if not os.getenv(key)]
            tools.append(
                {
                    "name": entry.name,
                    "group": entry.group,
                    "markets": list(entry.markets),
                    "operations": list(entry.operations),
                    "depths": list(entry.depths),
                    "risk_level": entry.risk_level,
                    "timeout_ms": entry.timeout_ms,
                    "cache_ttl_s": entry.cache_ttl_s,
                    "requires_env": list(entry.requires_env),
                    "default_enabled": bool(entry.default_enabled),
                    "env_ready": len(missing_env) == 0,
                    "missing_env": missing_env,
                    "selected": entry.name in selected_set,
                }
            )

        return {
            "success": True,
            "market": market_norm,
            "operation": operation_norm,
            "analysis_depth": depth_norm,
            "output_mode": output_mode_norm,
            "agents": list(REPORT_AGENT_CANDIDATES),
            "selected_tools": selected_tools,
            "tools": tools,
        }

    return router
