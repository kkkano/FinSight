"""只按模型协议和预算推进的循环；不识别问法，不补调用，不改正文。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import time
import uuid

from .context import dumps, tokens
from .data import RunData
from .limits import LeaseLimiter, TokenReservations
from .model import BudgetedModel, ModelProtocolError
from .profiles import AGENT_PROFILES
from .registry import financial_tools
from .compactor import Compactor
from .registry import ToolRegistry


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str = "root"
    role: str = "research_lead"
    max_turns: int = 12
    depth: int = 0
    model: object = None
    system_prompt: str | None = None
    tools: dict | None = None
    terminal_tools: tuple = ()
    include_history: bool = True
    emit_reasoning: bool = True




class AgentRuntime:
    def __init__(self, *, context, session_id, query, model, emit, history=None, ui_context=None,
                 tools=None, limiter=None, role_models=None):
        self.context, self.session_id, self.query, self.model = context, session_id, query, model
        self._emit, self.history, self.ui_context = emit, history or [], ui_context or {}
        self.data = RunData(context.owner, session_id, context.run_id, query)
        self.limiter = limiter or LeaseLimiter()
        self.budget = TokenReservations(maximum=int(os.getenv("FINSIGHT_AGENT_TOKEN_BUDGET", "160000")))
        self.base_tools = tools if tools is not None else financial_tools()
        self.role_models = role_models or {}
        self._knowledge = None
        self.actions, self.instructions, self.applied_instructions = {}, {}, set()
        self.accepting_instructions = True
        self.report_title, self.observed_tickers, self.children = None, [], set()
        self._closed, self.tool_count, self.reasoning_chars = False, 0, 0
        self._answer_parts, self._stream_text, self.stages, self._agent_roles = [], "", {}, {}
        self.transcripts, self.compactors = {}, {}
        self.reviews, self.report_revision = [], None
        self.model_duration_seconds = {}
        self.registry = self.executor = ToolRegistry(self)

    @property
    def root_content(self):
        text, previous = "", "length"
        for content, finish in [*self._answer_parts, (self._stream_text, None)]:
            if content:
                text += ("\n\n" if text and previous != "length" else "") + content
                previous = finish
        return text

    async def emit(self, kind, payload, agent_id="root"):
        if not self._closed:
            role = self._agent_roles.get(agent_id, "research_lead")
            profile = AGENT_PROFILES.get(role)
            await self._emit(kind, {"role": role, "agent_label": profile.name_zh if profile else "主研究员", **payload}, agent_id)

    def instruct(self, instruction, instruction_id):
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 8000:
            raise ValueError("invalid_instruction")
        if instruction_id in self.instructions and self.instructions[instruction_id] != instruction:
            raise ValueError("instruction_id_conflict")
        if instruction_id not in self.instructions and not self.accepting_instructions:
            raise ValueError("run_not_accepting_instructions")
        self.instructions[instruction_id] = instruction
        return {"instruction_id": instruction_id, "status": "accepted"}

    def drain(self, agent_id):
        if agent_id != "root":
            return []
        fresh = [(key, text) for key, text in self.instructions.items() if key not in self.applied_instructions]
        self.applied_instructions.update(key for key, _ in fresh)
        return [{"role": "user", "content": text} for _, text in fresh]

    async def run_agent(self, agent_id="root", role="research_lead", task=None, refs=None, depth=0, max_turns=None):
        self._agent_roles[agent_id] = role
        spec = AgentSpec(agent_id, role, max_turns or int(os.getenv("FINSIGHT_AGENT_MAX_TURNS", "12")),
                         depth, self.role_models.get(role))
        return await run(self, spec, task if task is not None else self.query, refs)

    async def close(self, **_kwargs):
        self._closed = True
        for child in list(self.children):
            child.cancel()
        if self.children:
            await asyncio.gather(*self.children, return_exceptions=True)
        await self.registry.close()


async def run(rt, spec, task, handles=None, transcript=None):
    model = BudgetedModel(rt, spec)
    compactor = rt.compactors.get(spec.agent_id) if transcript is not None else None
    if compactor is None:
        compactor = Compactor(rt.data, model, rt.context)
    compactor.model, compactor.context = model, rt.context
    rt.compactors[spec.agent_id] = compactor
    system = spec.system_prompt or (Path(__file__).resolve().parent / "prompts/system.md").read_text(encoding="utf-8")
    system = system.replace("{skills_index}", rt.registry.skills_index())
    profile = AGENT_PROFILES.get(spec.role)
    if profile and not spec.system_prompt:
        system += "\n\n" + profile.mandate_zh
    ui = {key: rt.ui_context[key] for key in ("view", "active_symbol", "tickers", "tickers_override", "selection", "selections",
          "strict_selection", "output_mode", "skill_ids", "selected_skills", "selected_agents", "review_revision") if key in rt.ui_context}
    content = task
    if spec.agent_id == "root" and rt.ui_context.get("images"):
        content = [{"type": "text", "text": task}] + [{"type": "image_url", "image_url": {"url": item["data_url"]}}
                                                       for item in rt.ui_context["images"]]
    messages = [{"role": "system", "content": system}, *(rt.history if spec.include_history else []),
        {"role": "user", "content": dumps({"current_date": datetime.now(timezone.utc).isoformat(),
            "ui_context": ui, "available_data": rt.registry.context_index(handles),
            "selected_skill_guidance": rt.registry.selected_skill_context()})},
        {"role": "user", "content": content}, *rt.drain(spec.agent_id)]
    if transcript is not None:
        messages = transcript
        messages.append({"role": "user", "content": task})
    rt.transcripts[spec.agent_id] = messages
    answer, initial_handles = [], set(rt.data.records)
    tools = spec.tools if spec.tools is not None else rt.registry.available(spec.agent_id, spec.role, spec.depth)
    for turn in range(spec.max_turns):
        rt.context.guard()
        response_margin = max(20, min(90, 2 * rt.model_duration_seconds.get(spec.agent_id, 0)))
        last = turn == spec.max_turns - 1 or rt.context.remaining_seconds < response_margin
        schemas = [tool.openai() for name, tool in tools.items() if not last or name in spec.terminal_tools]
        if last and not spec.terminal_tools:
            messages.append({"role": "user", "content": "这是本次运行最后一轮，不再提供工具。请基于已有资料完成回答，说明尚未取得的资料。表格使用普通 Markdown，不要生成工具调用或在正文模拟工具调用。"})
        fitted = await compactor.fit(messages, schemas, model.config.context_window, model.config.max_output)
        calls, text, reasoning, finish = {}, "", "", None
        block = spec.agent_id + "_text_" + uuid.uuid4().hex
        rt.stages[spec.agent_id] = "model_response"
        async for chunk in model.stream(fitted, schemas):
            if chunk.get("runtime_retry"):
                await rt.emit("activity.updated", {"activity_id": spec.agent_id + "_model", **chunk["runtime_retry"]}, spec.agent_id)
            for choice in chunk.get("choices", []):
                delta = choice.get("delta") or {}
                finish = choice.get("finish_reason") or finish
                piece = delta.get("content") or ""
                if not isinstance(piece, str):
                    raise ModelProtocolError("model_invalid_content")
                text += piece
                if spec.agent_id == "root" and piece:
                    rt._stream_text = text
                    await rt.emit("content.delta", {"block_id": block, "delta": piece})
                raw = delta.get("reasoning_content") or ""
                reasoning += raw
                visible = raw[:max(0, 20000 - rt.reasoning_chars)]
                if visible and spec.emit_reasoning:
                    rt.reasoning_chars += len(visible)
                    await rt.emit("reasoning.delta", {"block_id": block + "_reasoning", "delta": visible,
                        "kind": "provider_raw", "provider": model.config.endpoint_name}, spec.agent_id)
                for call in delta.get("tool_calls") or []:
                    item = calls.setdefault(call.get("index", 0), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if call.get("id"):
                        item["id"] = call["id"]
                    for field in ("name", "arguments"):
                        item["function"][field] += (call.get("function") or {}).get(field) or ""
        if calls and not schemas:
            raise ModelProtocolError("model_unrequested_tool_call")
        reply = {"role": "assistant", "content": text}
        if reasoning:
            reply["reasoning_content"] = reasoning
        if calls:
            reply["tool_calls"] = list(calls.values())
        messages.append(reply)
        if spec.agent_id == "root":
            if not calls:
                rt._answer_parts.append((text, finish))
            rt._stream_text = ""
            await rt.emit("content.block_finished", {"block_id": block, "content_phase": "progress" if calls else "answer",
                "finish_reason": finish, "completion_status": "partial" if finish == "length" else "complete"})
        if finish == "length" and not calls:
            answer.append(text)
            messages.append({"role": "user", "content": "上一段输出被长度限制截断，请从断点继续，不要重复已写内容。"})
            messages.extend(rt.drain(spec.agent_id))
            continue
        if not calls:
            if spec.terminal_tools:
                messages.append({"role": "user", "content": dumps({"required_submission_tools": spec.terminal_tools,
                    "instruction": "此子运行必须通过提供的提交工具返回结构化结论，正文不会视为有效提交。"})})
                continue
            pending = rt.drain(spec.agent_id)
            if pending:
                messages.extend(pending)
                answer.append(text)
                continue
            return {"agent_id": spec.agent_id, "role": spec.role, "summary": "".join([*answer, text]),
                    "data_refs": [ref for ref in rt.data.records if ref not in initial_handles], "stopped": "completed"}
        rt.stages[spec.agent_id] = "tool_execution"
        results = await asyncio.gather(*(rt.registry.execute(call, spec.agent_id, spec.role, spec.depth,
                    permitted=tools) for call in calls.values()))
        for call, result in zip(calls.values(), results):
            compactor.bind(call["id"], rt.registry.metadata(result)["handles"])
            messages.append({"role": "tool", "tool_call_id": call["id"],
                "content": rt.registry.model_text(result, min(8000, int(model.config.context_window * .06)))})
        if any(call["function"]["name"] in spec.terminal_tools and result.status == "ok" for call, result in zip(calls.values(), results)):
            return {"agent_id": spec.agent_id, "role": spec.role, "summary": text,
                    "data_refs": [ref for ref in rt.data.records if ref not in initial_handles], "stopped": "completed"}
        messages.extend(rt.drain(spec.agent_id))
        if turn >= spec.max_turns - 3 or rt.context.remaining_seconds < 30:
            messages.append({"role": "user", "content": f"还剩 {spec.max_turns - turn - 1} 轮 / 约 {int(rt.context.remaining_seconds)} 秒，请开始收尾。"})
    return {"agent_id": spec.agent_id, "role": spec.role, "summary": "".join(answer),
            "data_refs": [ref for ref in rt.data.records if ref not in initial_handles], "stopped": "max_turns"}
