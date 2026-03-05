#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式响应支持
用于展示 Agent 的思考过程，集成全局追踪事件
"""

from typing import AsyncGenerator, Dict, Any, Optional, Callable, List, AsyncIterator
from fastapi.responses import StreamingResponse
import json
import asyncio
import logging
from datetime import datetime

from backend.orchestration.trace_emitter import get_trace_emitter, TraceEvent

logger = logging.getLogger(__name__)
HEARTBEAT_INTERVAL_SECONDS = 15.0
# 必须是 data: 事件（非 SSE 注释），Cloudflare Tunnel HTTP/2 只转发实际数据帧
HEARTBEAT_FRAME = f"data: {json.dumps({'type': 'heartbeat'})}\n\n"


def _trace_event_to_sse(event: TraceEvent) -> str:
    """将 TraceEvent 转换为 SSE 格式字符串"""
    return f"data: {json.dumps(event.to_sse_dict(), ensure_ascii=False)}\n\n"


async def _drain_trace_queue(queue: asyncio.Queue, timeout: float = 0.01) -> List[TraceEvent]:
    """非阻塞地获取队列中所有待处理的 trace 事件"""
    events: List[TraceEvent] = []
    try:
        while True:
            event = queue.get_nowait()
            events.append(event)
    except asyncio.QueueEmpty:
        pass
    return events


class ThinkingStream:
    """思考过程流式输出"""
    
    @staticmethod
    async def stream_thinking(
        agent,
        query: str,
        include_tools: bool = True,
        include_reasoning: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        流式输出 Agent 的思考过程
        
        Args:
            agent: ConversationAgent 实例
            query: 用户查询
            include_tools: 是否包含工具调用信息
            include_reasoning: 是否包含推理过程
            
        Yields:
            JSON 格式的思考过程片段
        """
        try:
            # 1. 意图识别阶段
            yield json.dumps({
                "type": "thinking",
                "stage": "intent_classification",
                "message": "正在分析您的查询意图...",
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False) + "\n"
            
            # 解析指代
            resolved_query = agent.context.resolve_reference(query)
            
            # 路由
            intent, metadata, handler = agent.router.route(resolved_query, agent.context)
            
            yield json.dumps({
                "type": "thinking",
                "stage": "intent_classification",
                "result": {
                    "intent": intent.value,
                    "tickers": metadata.get('tickers', []),
                    "company_names": metadata.get('company_names', [])
                },
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False) + "\n"
            
            # 2. 数据收集阶段
            if metadata.get('tickers'):
                ticker = metadata['tickers'][0]
                yield json.dumps({
                    "type": "thinking",
                    "stage": "data_collection",
                    "message": f"正在获取 {ticker} 的数据...",
                    "timestamp": datetime.now().isoformat()
                }, ensure_ascii=False) + "\n"
            
            # 3. 处理阶段
            yield json.dumps({
                "type": "thinking",
                "stage": "processing",
                "message": f"正在生成{intent.value}响应...",
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False) + "\n"
            
            # 调用处理器（这里可以添加工具调用的监控）
            if handler:
                result = handler(resolved_query, metadata)
            else:
                result = agent._default_handler(resolved_query, metadata)
            
            # 4. 完成阶段
            yield json.dumps({
                "type": "thinking",
                "stage": "complete",
                "message": "处理完成",
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False) + "\n"
            
            # 5. 返回最终结果
            yield json.dumps({
                "type": "result",
                "data": result,
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False) + "\n"
            
        except Exception as e:
            yield json.dumps({
                "type": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False) + "\n"


async def stream_report_sse(
    report_agent: Any,
    query: str,
    report_builder: Optional[Callable[[str], Any]] = None,
) -> AsyncGenerator[str, None]:
    """Stream report tokens as SSE lines and optionally attach a report on done."""
    content_parts: List[str] = []
    done_received = False

    try:
        stream_iter: AsyncIterator[Any] = report_agent.analyze_stream(query).__aiter__()
        while True:
            try:
                raw = await asyncio.wait_for(
                    stream_iter.__anext__(),
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                yield HEARTBEAT_FRAME
                continue
            except StopAsyncIteration:
                break
            if raw is None:
                continue
            payload = str(raw).strip()
            if not payload:
                continue

            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"type": "token", "content": payload}

            event_type = data.get("type")
            if event_type == "token":
                token = data.get("content", "")
                if token:
                    content_parts.append(token)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            elif event_type == "done":
                done_received = True
            else:
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        done_payload: Dict[str, Any] = {"type": "done"}
        if report_builder:
            full_content = "".join(content_parts)
            if full_content:
                try:
                    done_payload["report"] = report_builder(full_content)
                except Exception as exc:
                    done_payload["report_error"] = str(exc)
        if done_received or content_parts:
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"


async def stream_supervisor_sse(
    supervisor: Any,
    query: str,
    ticker: str,
    report_builder: Optional[Callable[[str], Any]] = None,
) -> AsyncGenerator[str, None]:
    """
    Stream supervisor analysis events as SSE lines and attach a report on done.
    同时集成全局 TraceEmitter 事件，提供详细的后端操作追踪。
    """
    from backend.orchestration.trace import normalize_trace

    consensus_text = ""
    consensus_emitted = False

    # 创建 trace 事件队列并连接到全局 TraceEmitter
    trace_queue: asyncio.Queue = asyncio.Queue()
    trace_emitter = get_trace_emitter()
    trace_emitter.set_async_queue(trace_queue)

    try:
        stream_iter: AsyncIterator[Any] = supervisor.analyze_stream(query, ticker).__aiter__()
        while True:
            try:
                raw = await asyncio.wait_for(
                    stream_iter.__anext__(),
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                trace_events = await _drain_trace_queue(trace_queue)
                for te in trace_events:
                    yield _trace_event_to_sse(te)
                yield HEARTBEAT_FRAME
                continue
            except StopAsyncIteration:
                break
            # 先处理所有待处理的 trace 事件
            trace_events = await _drain_trace_queue(trace_queue)
            for te in trace_events:
                yield _trace_event_to_sse(te)

            if raw is None:
                continue
            payload = str(raw).strip()
            if not payload:
                continue

            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"type": "token", "content": payload}

            event_type = data.get("type")
            if event_type == "token":
                token = data.get("content", "")
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            elif event_type == "forum_done":
                consensus_text = data.get("consensus", "") or consensus_text
                if consensus_text and not consensus_emitted:
                    consensus_emitted = True
                    # 分块流式发送 consensus_text，添加异步延迟增强流式效果
                    chunk_size = 50
                    for i in range(0, len(consensus_text), chunk_size):
                        chunk = consensus_text[i:i + chunk_size]
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                        # 添加小延迟，让前端有时间渲染每个 chunk
                        await asyncio.sleep(0.02)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            elif event_type == "done":
                output = data.get("output") or {}
                if not consensus_text:
                    consensus_text = output.get("consensus", "")

                logger.info(f"[stream_supervisor_sse] done event - consensus_text length: {len(consensus_text)}, report_builder: {report_builder is not None}")

                done_payload: Dict[str, Any] = {"type": "done"}
                if output:
                    done_payload["output"] = output
                # 传递 agent_outputs, plan, plan_trace 以便前端/main.py 使用
                if data.get("agent_outputs"):
                    normalized_outputs: Dict[str, Any] = {}
                    for name, output in data["agent_outputs"].items():
                        if isinstance(output, dict):
                            trace = output.get("trace")
                            if trace:
                                output["trace"] = normalize_trace(
                                    trace,
                                    agent_name=output.get("agent_name") or name
                                )
                        normalized_outputs[name] = output
                    done_payload["agent_outputs"] = normalized_outputs
                if data.get("plan"):
                    done_payload["plan"] = data["plan"]
                if data.get("plan_trace"):
                    done_payload["plan_trace"] = normalize_trace(
                        data["plan_trace"],
                        agent_name="plan"
                    )
                if report_builder and consensus_text:
                    try:
                        done_payload["report"] = report_builder(consensus_text)
                        logger.info(f"[stream_supervisor_sse] report built successfully, keys: {list(done_payload['report'].keys()) if isinstance(done_payload['report'], dict) else 'not dict'}")
                    except Exception as exc:
                        logger.error(f"[stream_supervisor_sse] report_builder failed: {exc}")
                        done_payload["report_error"] = str(exc)
                elif not consensus_text:
                    logger.warning(f"[stream_supervisor_sse] consensus_text is empty, cannot build report")

                yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        # 最后再处理一次剩余的 trace 事件
        final_trace_events = await _drain_trace_queue(trace_queue)
        for te in final_trace_events:
            yield _trace_event_to_sse(te)

    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
    finally:
        # 清理队列连接
        trace_emitter.clear_async_queue()


def create_thinking_callback(stream_generator):
    """创建思考过程回调函数"""
    def on_tool_start(tool_name: str, tool_input: str):
        """工具调用开始"""
        stream_generator.send(json.dumps({
            "type": "tool_call",
            "stage": "start",
            "tool": tool_name,
            "input": tool_input,
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False) + "\n")
    
    def on_tool_end(tool_name: str, tool_output: str):
        """工具调用结束"""
        stream_generator.send(json.dumps({
            "type": "tool_call",
            "stage": "end",
            "tool": tool_name,
            "output": tool_output[:200] if len(tool_output) > 200 else tool_output,  # 截断长输出
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False) + "\n")
    
    def on_llm_start(prompt: str):
        """LLM 调用开始"""
        stream_generator.send(json.dumps({
            "type": "llm_call",
            "stage": "start",
            "message": "正在调用 AI 模型...",
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False) + "\n")
    
    def on_llm_end(response: str):
        """LLM 调用结束"""
        stream_generator.send(json.dumps({
            "type": "llm_call",
            "stage": "end",
            "message": "AI 模型响应完成",
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False) + "\n")
    
    return {
        "on_tool_start": on_tool_start,
        "on_tool_end": on_tool_end,
        "on_llm_start": on_llm_start,
        "on_llm_end": on_llm_end
    }

