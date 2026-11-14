"""用同一循环只读核查已生成的回答；核查结果只提供标注。"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import time
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.services.run_context import RunCancelledError, RunContext, run_context_scope

from .context import dumps
from .envelope import ToolResult
from .loop import AgentRuntime, AgentSpec, run
from .model import ModelProtocolError
from .registry import ToolSpec

REVIEW_TIMEOUT_SECONDS = 90.0


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    quote: str = Field(min_length=1, description="回答中逐字存在的原文，不可改写或省略。")
    issue: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requirement: str = Field(min_length=1)
    met: bool


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    verdict: Literal["pass", "revise", "insufficient"]
    findings: list[ReviewFinding]
    coverage: list[Coverage]


def should_review(runtime: AgentRuntime) -> bool:
    """仅根据本轮实际数据工具调用判断；报告由交付入口强制核查。"""
    for attempt in runtime.registry.attempts:
        name = attempt["name"]
        tool = runtime.base_tools.get(name)
        if (attempt.get("data_refs") or name in {"read_data", "run_python", "search_memory"}
                or tool is not None and tool.financial):
            return True
    return False


async def review_answer(runtime: AgentRuntime, answer: str, model=None, max_seconds: float = REVIEW_TIMEOUT_SECONDS) -> dict:
    """核查独立计时，共享原运行身份、数据与用量，不解析其他用户的模型配置。"""
    review_id = "reviewer_" + uuid.uuid4().hex[:12]
    seconds = max(0.0, min(REVIEW_TIMEOUT_SECONDS, max_seconds, runtime.context.remaining_seconds))
    selected_model = runtime.model if model is None else model
    reviewer = None
    submitted = None
    result = {"status": "unavailable", "error_code": "review_failed", "review_id": review_id}

    async def emit(kind, payload, agent_id):
        if kind in {"tool.started", "tool.result", "tool.failed", "activity.updated"}:
            await runtime.emit(kind, {**payload, "role": "reviewer", "agent_label": "核查员"}, agent_id=agent_id)

    def submit_review(args):
        nonlocal submitted
        if submitted is not None:
            raise ValueError("review_already_submitted")
        try:
            review = Review.model_validate(args)
        except ValidationError as exc:
            raise ValueError("invalid_review_submission") from exc
        if any(finding.quote not in answer for finding in review.findings):
            raise ValueError("review_quote_not_in_answer")
        submitted = review
        return ToolResult(status="ok", kind="control", data=review.model_dump(mode="json"))

    await runtime.emit("review.started", {"status": "running", "review_id": review_id,
        "role": "reviewer", "agent_label": "核查员"}, agent_id=review_id)
    try:
        context = RunContext(owner=runtime.context.owner, entry="review", run_id=runtime.context.run_id,
            deadline=time.monotonic() + seconds, selected_model=selected_model.config.model,
            cancelled=runtime.context.cancelled, quota_checker=runtime.context.quota_checker)
        context.usage = runtime.context.usage
        reviewer = AgentRuntime(context=context, session_id=runtime.session_id, query=runtime.query,
            model=selected_model, emit=emit, ui_context=runtime.ui_context, tools={}, limiter=runtime.limiter)
        reviewer.data, reviewer.budget = runtime.data, runtime.budget
        reviewer._knowledge = runtime._knowledge
        reviewer._agent_roles[review_id] = "reviewer"
        allowed = reviewer.registry.available(review_id, "reviewer", depth=1)
        tools = {name: allowed[name] for name in ("read_data", "run_python")}
        tools["submit_review"] = ToolSpec("submit_review", "提交结构化核查标注；quote 必须逐字存在于给定回答。不能修改回答。",
            Review.model_json_schema(), submit_review, enveloped=True)
        spec = AgentSpec(agent_id=review_id, role="reviewer", max_turns=4, depth=1, model=selected_model,
            system_prompt=(Path(__file__).with_name("prompts") / "verifier.md").read_text(encoding="utf-8"),
            tools=tools, terminal_tools=("submit_review",), include_history=False, emit_reasoning=False)
        task = dumps({"query": runtime.query, "additional_requirements": list(runtime.instructions.values()),
                      "answer": answer, "sources": runtime.data.sources,
                      "artifacts": runtime.data.artifacts})
        with run_context_scope(context):
            async with asyncio.timeout(seconds):
                outcome = await run(reviewer, spec, task, handles=list(runtime.data.records))
        if submitted is not None:
            result = {"status": "completed", **submitted.model_dump(mode="json"),
                      "review_id": review_id, "data_refs": outcome["data_refs"]}
        else:
            attempted = any(item["name"] == "submit_review" for item in reviewer.registry.attempts)
            code = "review_invalid_submission" if attempted else (
                "review_turn_limit" if outcome["stopped"] == "max_turns" else "review_not_submitted")
            result = {"status": "unavailable", "error_code": code, "review_id": review_id}
    except asyncio.CancelledError:
        result = {"status": "unavailable", "error_code": "review_cancelled", "review_id": review_id}
        raise
    except RunCancelledError as exc:
        result = {"status": "unavailable", "error_code": "review_cancelled", "review_id": review_id}
        raise asyncio.CancelledError() from exc
    except TimeoutError:
        result = {"status": "unavailable", "error_code": "review_timeout", "review_id": review_id}
    except ModelProtocolError as exc:
        code = "review_timeout" if exc.code == "model_timeout" else "review_model_error"
        result = {"status": "unavailable", "error_code": code, "review_id": review_id}
    except Exception:
        result = {"status": "unavailable", "error_code": "review_failed", "review_id": review_id}
    finally:
        if reviewer is not None:
            # 核查超时不能反向设置与父运行共享的取消信号。
            reviewer.context.status = "completed" if result["status"] == "completed" else "failed"
            await reviewer.close()
        result.update(answer_sha256=hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                      supersedes_review_id=runtime.reviews[-1]["review_id"] if runtime.reviews else None)
        await runtime.emit("review.finished", {**result, "role": "reviewer", "agent_label": "核查员"}, agent_id=review_id)
    return result
