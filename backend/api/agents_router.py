# -*- coding: utf-8 -*-
"""
agents_router — 暴露可手动选择的研究 Agent 清单。

用于对话「手动选 Agent」双模式：前端输入 ``@`` 触发 autocomplete，
从该端点拉取 agent 列表，选中后以 ``@{name}`` 形式插入，发送时解析为
ExecuteRequest.agents 覆盖自动编排。

agent 清单与面向用户的身份元数据统一读取 AgentProfile 注册表。
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Annotated, Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BeforeValidator

from backend.agents.profiles import profile
from backend.config.ticker_mapping import normalize_ticker
from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES
from backend.graph.preference_timeouts import normalize_timeout_seconds
from backend.services.agent_prediction_store import PredictionStoreUnavailable

logger = logging.getLogger(__name__)

_VALID_DEPTHS = {"standard", "deep", "off"}
_MAX_ROUNDS_MIN = 1
_MAX_ROUNDS_MAX = 10
_MAX_ROUNDS_DEFAULT = 3
_PREDICTION_SYMBOL_PATTERN = re.compile(
    r"^(?=.{1,32}$)(?:\^[A-Z0-9][A-Z0-9.-]*|[A-Z0-9][A-Z0-9.-]*(?:=[A-Z])?)$",
    flags=re.ASCII,
)


def _normalize_prediction_symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("symbol must be a string")
    normalized = normalize_ticker(value.strip())
    if not _PREDICTION_SYMBOL_PATTERN.fullmatch(normalized):
        raise ValueError("invalid prediction symbol")
    return normalized


PredictionSymbol = Annotated[
    str,
    BeforeValidator(_normalize_prediction_symbol),
    Query(description="规范化后的行情 symbol"),
]


@dataclass(frozen=True)
class AgentsRouterDeps:
    memory_service: Any
    get_prediction_store: Callable[[], Any] | None = None
    get_outcome_store: Callable[[], Any] | None = None
    get_run_archive: Callable[[], Any] | None = None


def _prediction_overlay(prediction: Any) -> dict[str, Any]:
    overlay = {
        "predictionId": prediction.id,
        "symbol": prediction.symbol,
        "direction": prediction.direction,
        "anchor": prediction.anchor.model_dump(mode="json"),
        "entry": prediction.entry,
        "stop": prediction.stop,
        "target1": prediction.target1,
        "target2": prediction.target2,
        "status": prediction.status,
    }
    if prediction.range_low is not None and prediction.range_high is not None:
        overlay["range"] = {"low": prediction.range_low, "high": prediction.range_high}
    return {key: value for key, value in overlay.items() if value is not None}


def _default_preferences() -> dict[str, Any]:
    return {
        "agents": {name: "standard" for name in REPORT_AGENT_CANDIDATES},
        "maxRounds": _MAX_ROUNDS_DEFAULT,
        "concurrentMode": True,
        "timeoutSeconds": 0,
        "enableLLMAnalysis": False,
        "reflectionRounds": 0,
        "analysisTimeoutSeconds": 0,
        "tokenAcquireTimeoutSeconds": 0,
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

    try:
        max_rounds = int(raw.get("maxRounds", defaults["maxRounds"]))
    except (TypeError, ValueError):
        max_rounds = defaults["maxRounds"]
    max_rounds = max(_MAX_ROUNDS_MIN, min(_MAX_ROUNDS_MAX, max_rounds))

    concurrent_mode = raw.get("concurrentMode", defaults["concurrentMode"])
    if not isinstance(concurrent_mode, bool):
        concurrent_mode = defaults["concurrentMode"]

    timeout = normalize_timeout_seconds(raw.get("timeoutSeconds", raw.get("timeout_seconds")))
    timeout_seconds = int(timeout) if timeout is not None else 0

    enable_llm = raw.get("enableLLMAnalysis", defaults["enableLLMAnalysis"])
    if not isinstance(enable_llm, bool):
        enable_llm = defaults["enableLLMAnalysis"]

    try:
        reflection_rounds = int(raw.get("reflectionRounds", defaults["reflectionRounds"]))
    except (TypeError, ValueError):
        reflection_rounds = defaults["reflectionRounds"]
    reflection_rounds = max(0, min(3, reflection_rounds))

    try:
        analysis_timeout = int(raw.get("analysisTimeoutSeconds", defaults["analysisTimeoutSeconds"]))
    except (TypeError, ValueError):
        analysis_timeout = 0
    analysis_timeout = max(10, min(120, analysis_timeout)) if analysis_timeout > 0 else 0

    try:
        token_timeout = int(raw.get("tokenAcquireTimeoutSeconds", defaults["tokenAcquireTimeoutSeconds"]))
    except (TypeError, ValueError):
        token_timeout = 0
    token_timeout = max(5, min(60, token_timeout)) if token_timeout > 0 else 0

    return {
        "agents": normalized_agents,
        "maxRounds": max_rounds,
        "concurrentMode": concurrent_mode,
        "timeoutSeconds": timeout_seconds,
        "enableLLMAnalysis": enable_llm,
        "reflectionRounds": reflection_rounds,
        "analysisTimeoutSeconds": analysis_timeout,
        "tokenAcquireTimeoutSeconds": token_timeout,
    }


def create_agents_router(deps: AgentsRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Agents"])

    @router.get("/api/agents")
    async def list_agents(
        request: Request,
        query: str = Query("", description="按名称或描述子串过滤 agent"),
        limit: int = Query(20, description="最大条目数", ge=1, le=50),
    ) -> dict[str, Any]:
        q = str(query or "").strip().lower()
        user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
        items: list[dict[str, Any]] = []
        for name in REPORT_AGENT_CANDIDATES:
            item_profile = profile(name)
            display_name = item_profile.name_zh
            description = item_profile.mandate_zh
            if (
                q
                and q not in name.lower()
                and q not in display_name.lower()
                and q not in description.lower()
            ):
                continue
            track_record: dict[str, Any] = {
                "hits": 0, "misses": 0, "invalidated": 0, "sample_count": 0,
                "hit_rate": None, "sample_state": "样本不足", "latest_evaluated_at": None,
                "by_direction": {},
            }
            cost_summary = {
                "days_7": {"days": 7, "tokens": 0, "cost_usd": 0.0, "run_count": 0, "call_count": 0, "failed_call_count": 0, "unscored_runs": 0},
                "days_30": {"days": 30, "tokens": 0, "cost_usd": 0.0, "run_count": 0, "call_count": 0, "failed_call_count": 0, "unscored_runs": 0},
            }
            if user_id and user_id != "public":
                if deps.get_outcome_store is not None:
                    try:
                        track_record = deps.get_outcome_store().track_record(
                            user_id=user_id, agent=name, days=90,
                        )
                    except Exception as exc:
                        logger.warning("读取 Agent 历史命中率失败，使用空样本降级: agent=%s error=%s", name, exc)
                if deps.get_run_archive is not None:
                    try:
                        archive = deps.get_run_archive()
                        cost_summary = {
                            "days_7": archive.cost_summary(user_id=user_id, agent=name, days=7),
                            "days_30": archive.cost_summary(user_id=user_id, agent=name, days=30),
                        }
                    except Exception as exc:
                        logger.warning("读取 Agent 成本摘要失败，使用零值降级: agent=%s error=%s", name, exc)
            items.append({
                "name": name,
                "display_name": display_name,
                "short_zh": item_profile.short_zh,
                "description": description,
                "glyph": item_profile.glyph,
                "color_token": item_profile.color_token,
                "mandate": item_profile.mandate_zh,
                "dashboard_tabs": list(item_profile.dashboard_tabs),
                "insert_text": f"@{name} ",
                "track_record": track_record,
                "cost_summary": cost_summary,
            })
            if len(items) >= limit:
                break
        return {"success": True, "query": q, "count": len(items), "items": items}

    @router.get("/api/agents/predictions/latest", response_model=None)
    async def get_latest_prediction(
        request: Request,
        symbol: PredictionSymbol,
    ) -> dict[str, Any] | Response:
        user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
        if user_id == "public":
            raise HTTPException(status_code=401, detail="登录后才能读取 AI prediction")
        if deps.get_prediction_store is None:
            raise HTTPException(status_code=503, detail="AI prediction store unavailable")
        try:
            prediction = deps.get_prediction_store().get_latest(user_id=user_id, symbol=symbol)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="AI prediction store unavailable") from exc
        if prediction is None:
            return Response(status_code=204)
        return {"prediction": _prediction_overlay(prediction)}

    @router.get("/api/agents/predictions/{prediction_id}")
    async def get_prediction(prediction_id: str, request: Request) -> dict[str, Any]:
        user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
        if user_id == "public":
            raise HTTPException(status_code=401, detail="登录后才能读取 AI prediction")
        if deps.get_prediction_store is None:
            raise HTTPException(status_code=503, detail="AI prediction store unavailable")
        try:
            prediction = deps.get_prediction_store().get(prediction_id, user_id=user_id)
        except PredictionStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail="AI prediction store unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="AI prediction store unavailable") from exc
        if prediction is None:
            # 404 不区分不存在与跨租户，避免泄露资源存在性。
            raise HTTPException(status_code=404, detail="prediction not found")
        return {"prediction": _prediction_overlay(prediction)}

    @router.get("/api/agents/preferences")
    async def get_agent_preferences(user_id: str = "default_user") -> dict[str, Any]:
        if not deps.memory_service:
            return {"success": False, "error": "MemoryService not initialized"}

        try:
            profile = deps.memory_service.get_user_profile(user_id)
            prefs = profile.preferences if isinstance(profile.preferences, dict) else {}
            preferences = _normalize_preferences(prefs.get("agent_preferences"))
            return {"success": True, "user_id": user_id, "preferences": preferences}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @router.put("/api/agents/preferences")
    async def update_agent_preferences(request: dict[str, Any]) -> dict[str, Any]:
        if not deps.memory_service:
            return {"success": False, "error": "MemoryService not initialized"}

        try:
            user_id = str(request.get("user_id") or "default_user").strip() or "default_user"
            profile = deps.memory_service.get_user_profile(user_id)
            profile.preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
            preferences = _normalize_preferences(request.get("preferences"))
            profile.preferences["agent_preferences"] = preferences
            success = deps.memory_service.update_user_profile(profile)
            return {
                "success": bool(success),
                "user_id": user_id,
                "preferences": preferences,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    return router
