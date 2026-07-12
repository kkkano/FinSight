# -*- coding: utf-8 -*-
"""
agents_router — 暴露可手动选择的研究 Agent 清单。

用于对话「手动选 Agent」双模式：前端输入 ``@`` 触发 autocomplete，
从该端点拉取 agent 列表，选中后以 ``@{name}`` 形式插入，发送时解析为
ExecuteRequest.agents 覆盖自动编排。

agent 清单复用 capability_registry.REPORT_AGENT_CANDIDATES（单一数据源），
此处仅补充面向用户的中文展示元数据（display_name / description）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request

from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES
from backend.graph.preference_timeouts import normalize_timeout_seconds
from backend.services.agent_prediction_store import PredictionStoreUnavailable

_VALID_DEPTHS = {"standard", "deep", "off"}
_MAX_ROUNDS_MIN = 1
_MAX_ROUNDS_MAX = 10
_MAX_ROUNDS_DEFAULT = 3
# 面向用户的中文展示元数据（key 必须是 REPORT_AGENT_CANDIDATES 中的 agent 名）
_AGENT_DISPLAY_META: dict[str, dict[str, str]] = {
    "price_agent": {
        "display_name": "价格行为分析师",
        "description": "趋势、动量、关键价位、量价确认与价格行为风险",
    },
    "news_agent": {
        "display_name": "舆情新闻分析师",
        "description": "新闻情绪量化、催化事件识别、情绪与价格传导",
    },
    "fundamental_agent": {
        "display_name": "基本面分析师",
        "description": "增长、盈利质量、现金流、EPS 修正与估值支撑",
    },
    "technical_agent": {
        "display_name": "技术面分析师",
        "description": "RSI / MACD / 均线等技术指标与买卖信号研判",
    },
    "macro_agent": {
        "display_name": "宏观分析师",
        "description": "CPI / 利率 / 就业等宏观数据对标的的影响",
    },
    "risk_agent": {
        "display_name": "风险分析师",
        "description": "波动率、回撤、敞口与下行风险评估",
    },
    "deep_search_agent": {
        "display_name": "深度研究员",
        "description": "研报、SEC filing 等长文档深度调研",
    },
}

_missing_display_meta = set(REPORT_AGENT_CANDIDATES) - set(_AGENT_DISPLAY_META)
assert not _missing_display_meta, f"agents missing display meta: {_missing_display_meta}"


@dataclass(frozen=True)
class AgentsRouterDeps:
    memory_service: Any
    get_prediction_store: Callable[[], Any] | None = None


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
        query: str = Query("", description="按名称或描述子串过滤 agent"),
        limit: int = Query(20, description="最大条目数", ge=1, le=50),
    ) -> dict[str, Any]:
        q = str(query or "").strip().lower()
        items: list[dict[str, Any]] = []
        for name in REPORT_AGENT_CANDIDATES:
            meta = _AGENT_DISPLAY_META.get(name, {})
            display_name = meta.get("display_name", name)
            description = meta.get("description", "")
            if (
                q
                and q not in name.lower()
                and q not in display_name.lower()
                and q not in description.lower()
            ):
                continue
            items.append({
                "name": name,
                "display_name": display_name,
                "description": description,
                "insert_text": f"@{name} ",
            })
            if len(items) >= limit:
                break
        return {"success": True, "query": q, "count": len(items), "items": items}

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
        return {"prediction": {key: value for key, value in overlay.items() if value is not None}}

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
