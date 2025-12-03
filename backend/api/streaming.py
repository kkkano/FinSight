#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式响应支持
用于展示 Agent 的思考过程
"""

from typing import AsyncGenerator, Dict, Any, Optional
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

