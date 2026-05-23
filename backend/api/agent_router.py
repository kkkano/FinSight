from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES
from backend.graph.preference_timeouts import normalize_timeout_seconds

_VALID_DEPTHS = {"standard", "deep", "off"}
_MAX_ROUNDS_MIN = 1
_MAX_ROUNDS_MAX = 10
_MAX_ROUNDS_DEFAULT = 10


@dataclass(frozen=True)
class AgentRouterDeps:
    memory_service: Any


def _default_preferences() -> dict[str, Any]:
    return {
        "agents": {name: "deep" for name in REPORT_AGENT_CANDIDATES},
        "maxRounds": _MAX_ROUNDS_DEFAULT,
        "concurrentMode": True,
        "timeoutSeconds": 1200,
        "enableLLMAnalysis": True,
        "reflectionRounds": 3,
        "analysisTimeoutSeconds": 120,
        "tokenAcquireTimeoutSeconds": 60,
    }


def _normalize_preferences(raw: Any) -> dict[str, Any]:
    defaults = _default_preferences()
    if not isinstance(raw, dict):
        return defaults

    normalized_agents = dict(defaults["agents"])
    raw_agents = raw.get("agents")
    if isinstance(raw_agents, dict):
        for name, depth in raw_agents.items():
            if not isinstance(name, str) or name not in normalized_agents:
                continue
            depth_text = str(depth).strip().lower()
            if depth_text in _VALID_DEPTHS:
                normalized_agents[name] = depth_text

    max_rounds = raw.get("maxRounds", defaults["maxRounds"])
    try:
        max_rounds_value = int(max_rounds)
    except Exception:
        max_rounds_value = defaults["maxRounds"]
    max_rounds_value = max(_MAX_ROUNDS_MIN, min(_MAX_ROUNDS_MAX, max_rounds_value))

    concurrent_mode = raw.get("concurrentMode", defaults["concurrentMode"])
    if not isinstance(concurrent_mode, bool):
        concurrent_mode = defaults["concurrentMode"]

    timeout = normalize_timeout_seconds(raw.get("timeoutSeconds", raw.get("timeout_seconds")))
    timeout_seconds = int(timeout) if timeout is not None else 0

    enable_llm = raw.get("enableLLMAnalysis", defaults["enableLLMAnalysis"])
    if not isinstance(enable_llm, bool):
        enable_llm = defaults["enableLLMAnalysis"]

    reflection_raw = raw.get("reflectionRounds", defaults["reflectionRounds"])
    try:
        reflection_rounds = int(reflection_raw)
    except Exception:
        reflection_rounds = defaults["reflectionRounds"]
    reflection_rounds = max(0, min(3, reflection_rounds))

    analysis_timeout_raw = raw.get("analysisTimeoutSeconds", defaults["analysisTimeoutSeconds"])
    try:
        analysis_timeout = int(analysis_timeout_raw)
    except Exception:
        analysis_timeout = 0
    analysis_timeout = max(10, min(120, analysis_timeout)) if analysis_timeout > 0 else 0

    token_timeout_raw = raw.get("tokenAcquireTimeoutSeconds", defaults["tokenAcquireTimeoutSeconds"])
    try:
        token_timeout = int(token_timeout_raw)
    except Exception:
        token_timeout = 0
    token_timeout = max(5, min(60, token_timeout)) if token_timeout > 0 else 0

    return {
        "agents": normalized_agents,
        "maxRounds": max_rounds_value,
        "concurrentMode": concurrent_mode,
        "timeoutSeconds": timeout_seconds,
        "enableLLMAnalysis": enable_llm,
        "reflectionRounds": reflection_rounds,
        "analysisTimeoutSeconds": analysis_timeout,
        "tokenAcquireTimeoutSeconds": token_timeout,
    }


def create_agent_router(deps: AgentRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Agent"])

    @router.get("/api/agents/preferences")
    async def get_agent_preferences(user_id: str = "default_user"):
        if not deps.memory_service:
            return {"success": False, "error": "MemoryService not initialized"}

        try:
            profile = deps.memory_service.get_user_profile(user_id)
            prefs = profile.preferences if isinstance(profile.preferences, dict) else {}
            agent_preferences = _normalize_preferences(prefs.get("agent_preferences"))
            return {"success": True, "user_id": user_id, "preferences": agent_preferences}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @router.put("/api/agents/preferences")
    async def update_agent_preferences(request: dict):
        if not deps.memory_service:
            return {"success": False, "error": "MemoryService not initialized"}

        try:
            user_id = str(request.get("user_id") or "default_user").strip() or "default_user"
            profile = deps.memory_service.get_user_profile(user_id)
            profile.preferences = profile.preferences if isinstance(profile.preferences, dict) else {}

            normalized = _normalize_preferences(request.get("preferences"))
            profile.preferences["agent_preferences"] = normalized

            success = deps.memory_service.update_user_profile(profile)
            return {"success": bool(success), "user_id": user_id, "preferences": normalized}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    return router
