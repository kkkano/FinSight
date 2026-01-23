#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式响应支持
用于展示 Agent 的思考过程
"""

from typing import AsyncGenerator, Dict, Any, Optional, Callable, List
from fastapi.responses import StreamingResponse
import json
from datetime import datetime


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
        async for raw in report_agent.analyze_stream(query):
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
    import asyncio
    """Stream supervisor analysis events as SSE lines and attach a report on done."""
    import logging
    from backend.orchestration.trace import normalize_trace
    logger = logging.getLogger(__name__)
    
    consensus_text = ""
    consensus_emitted = False

    try:
        async for raw in supervisor.analyze_stream(query, ticker):
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
                        import asyncio
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
    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"


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

