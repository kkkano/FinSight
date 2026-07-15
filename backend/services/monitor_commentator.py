# -*- coding: utf-8 -*-
"""受限 LangGraph 实时点评生产者。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.prediction_contract import AgentPrediction
from backend.metrics import increment_monitor_comment
from backend.services.monitor_comment_store import get_monitor_comment_store
from backend.services.monitor_signals import MarketSnapshot, MonitorTrigger


class CommentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["info", "warn", "alert"]
    text: str = Field(min_length=1, max_length=500)


class _State(TypedDict, total=False):
    prompt: str
    raw: str


def _extract_json(raw: str) -> dict[str, Any]:
    text_value = str(raw or "").strip()
    start, end = text_value.find("{"), text_value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("commentator did not return JSON")
    return json.loads(text_value[start:end + 1])


async def _default_generate(prompt: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, StateGraph
    from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm

    async def call_model(state: _State) -> _State:
        response = await ainvoke_configured_llm(
            [HumanMessage(content=state["prompt"])],
            context=LLMCallContext.create(
                stage="monitor_comment", agent="monitor_commentator", layer="analysis", max_provider_attempts=2,
            ),
            temperature=0.1,
            max_tokens=300,
            request_timeout=12,
        )
        return {"raw": response.content if hasattr(response, "content") else str(response)}

    graph = StateGraph(_State)
    graph.add_node("comment", call_model)
    graph.add_edge(START, "comment")
    graph.add_edge("comment", END)
    result = await asyncio.wait_for(graph.compile().ainvoke({"prompt": prompt}), timeout=15)
    return _extract_json(result.get("raw", ""))


def _prompt(target, snapshot: MarketSnapshot, trigger: MonitorTrigger, prediction: AgentPrediction | None) -> str:
    prediction_summary = "无"
    if prediction is not None:
        prediction_summary = json.dumps({
            "id": prediction.id, "direction": getattr(prediction, "direction", None),
            "confidence": getattr(prediction, "confidence", None),
            "entry": getattr(prediction, "entry", None), "stop": getattr(prediction, "stop", None),
            "target1": getattr(prediction, "target1", None), "target2": getattr(prediction, "target2", None),
        }, ensure_ascii=False)
    return f"""你是金融工作台的实时点评员。只根据服务端提供的真实快照和确定性触发写一句中文点评。
返回严格 JSON：{{"level":"info|warn|alert","text":"不超过120字"}}。
heartbeat 必须 level=info；显式突破可 warn/alert。不得补造价格、新闻或原因。
source、是否升级和 prediction 关联由服务端决定，禁止输出这些字段。
标的={target.symbol}
真实快照={json.dumps(snapshot.__dict__, ensure_ascii=False, default=str)}
触发={json.dumps(trigger.__dict__, ensure_ascii=False)}
可选prediction={prediction_summary}"""


async def produce_monitor_comments(
    target, snapshot: MarketSnapshot, triggers: list[MonitorTrigger],
    prediction: AgentPrediction | None = None,
    *, prediction_escalated: bool = False,
    generator: Callable[[str], Awaitable[dict[str, Any]]] | None = None, store=None,
) -> int:
    comment_store = store or get_monitor_comment_store()
    generate = generator or _default_generate
    written = 0
    for trigger in triggers:
        escalated = bool(prediction_escalated and trigger.escalates_prediction)
        try:
            from backend.services.llm_usage import LLMAttribution, reset_llm_attribution, set_llm_attribution

            attribution_token = set_llm_attribution(LLMAttribution(
                agent=str(getattr(prediction, "agent", None) or "monitor_commentator"),
                layer="monitor_commentator",
                prediction_id=str(getattr(prediction, "id", "") or "").strip() or None,
            ))
            try:
                raw = await generate(_prompt(target, snapshot, trigger, prediction))
            finally:
                reset_llm_attribution(attribution_token)
            draft = CommentDraft.model_validate(raw)
            if trigger.kind == "heartbeat" and draft.level != "info":
                raise ValueError("heartbeat comment must be info")
            prediction_id = prediction.id if prediction is not None else None
            source, level, text_value = "agent", draft.level, draft.text
        except Exception as exc:
            prediction_id = prediction.id if prediction is not None and escalated else None
            source, level = "system", "error"
            text_value = f"实时点评生成失败：{type(exc).__name__}"
        try:
            item = comment_store.create(
                user_id=target.user_id, session_id=target.session_id, symbol=target.symbol,
                ts=datetime.now(timezone.utc), level=level, text_value=text_value,
                trigger_kind=trigger.kind, trigger_detail=trigger.detail,
                trigger_observed_at=trigger.observed_at, source=source, escalated=escalated,
                prediction_id=prediction_id,
            )
        except Exception:
            increment_monitor_comment(source=source, level=level, result="store_error")
            raise
        increment_monitor_comment(
            source=source,
            level=level,
            result="written" if item is not None else "deduplicated",
        )
        written += int(item is not None)
    return written


def produce_monitor_comments_sync(
    target,
    snapshot,
    triggers,
    prediction=None,
    *,
    prediction_escalated: bool = False,
) -> bool:
    return asyncio.run(produce_monitor_comments(
        target,
        snapshot,
        triggers,
        prediction,
        prediction_escalated=prediction_escalated,
    )) > 0


__all__ = ["CommentDraft", "produce_monitor_comments", "produce_monitor_comments_sync"]
