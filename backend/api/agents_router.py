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

from typing import Any

from fastapi import APIRouter, Query


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


def create_agents_router() -> APIRouter:
    router = APIRouter(tags=["Agents"])

    @router.get("/api/agents")
    async def list_agents(
        query: str = Query("", description="按名称或描述子串过滤 agent"),
        limit: int = Query(20, description="最大条目数", ge=1, le=50),
    ) -> dict[str, Any]:
        from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES

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

    return router
