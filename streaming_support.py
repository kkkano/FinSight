#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FinSight 流式支持模块
实现实时流式输出和用户友好的进度显示
兼容 LangChain 1.0+ 和 LangGraph 架构
集成 LangSmith 可观测性追踪
"""

import time
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# LangSmith 集成（可选）
try:
    from langsmith_integration import (
        is_enabled as langsmith_enabled,
        start_run,
        log_event,
        finish_run,
        RunContext
    )
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    langsmith_enabled = lambda: False

# ============================================
# 流式回调处理器
# ============================================

class FinancialStreamingCallbackHandler(BaseCallbackHandler):
    """金融分析专用的流式回调处理器 - 兼容 LangGraph + LangSmith"""

    def __init__(self, show_progress: bool = True, show_details: bool = True):
        self.show_progress = show_progress
        self.show_details = show_details
        self.start_time = None
        
        # 统计信息
        self.tool_calls = 0
        self.step_count = 0
        self.current_ticker = None
        
        # 防止重复显示
        self._header_shown = False
        self._last_tool = None
        
        # LangSmith 追踪
        self._langsmith_run: Optional[Any] = None
        self._current_query: str = ""

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Chain 开始时的回调"""
        # 只显示一次开始信息
        if self._header_shown:
            return
            
        self.start_time = datetime.now()
        self._header_shown = True
        
        # 提取查询内容
        query = ""
        if "messages" in inputs and inputs["messages"]:
            first_msg = inputs["messages"][0]
            if hasattr(first_msg, 'content'):
                query = first_msg.content
        elif "input" in inputs:
            query = inputs["input"]
        
        self._current_query = query
        
        # LangSmith: 开始追踪
        if LANGSMITH_AVAILABLE and langsmith_enabled():
            try:
                self._langsmith_run = start_run(
                    name=f"FinSight: {query[:50]}",
                    query=query,
                    metadata={"start_time": self.start_time.isoformat()}
                )
            except Exception:
                pass  # 静默失败
        
        if self.show_progress:
            print(f"\n{'='*70}")
            print(f"📈 FinSight 流式分析 - LangChain 1.0+")
            print(f"{'='*70}")
            print(f"🎯 查询: {query[:100]}...")
            print(f"📅 开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'─'*70}\n")

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> Any:
        """工具开始执行时的回调"""
        tool_name = serialized.get("name", "unknown_tool")
        
        # 防止重复显示同一工具
        tool_key = (tool_name, str(input_str)[:100])
        if self._last_tool == tool_key:
            return
        
        self.tool_calls += 1
        self._last_tool = tool_key
        
        # LangSmith: 记录工具开始
        if LANGSMITH_AVAILABLE and self._langsmith_run:
            try:
                log_event(self._langsmith_run, "tool_start", {
                    "tool": tool_name,
                    "input": str(input_str)[:200]
                })
            except Exception:
                pass
        
        if self.show_details:
            print(f"\n[Step {self.tool_calls}] {tool_name}")
            if input_str and len(input_str) < 200:
                print(f"   Input: {input_str}")

    def on_tool_end(self, output: str, **kwargs) -> Any:
        """工具执行完成时的回调"""
        # LangSmith: 记录工具结束
        if LANGSMITH_AVAILABLE and self._langsmith_run:
            try:
                output_str = str(output) if not isinstance(output, str) else output
                log_event(self._langsmith_run, "tool_end", {
                    "output": output_str[:200]
                })
            except Exception:
                pass
        
        if self.show_details:
            # 安全处理输出 - output 可能是 ToolMessage 对象
            try:
                output_str = str(output) if not isinstance(output, str) else output
                output_preview = output_str[:150] + "..." if len(output_str) > 150 else output_str
                print(f"   Result: {output_preview}\n")
            except Exception as e:
                print(f"   Result: <output processing error>\n")

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Chain 完成时的回调"""
        # LangSmith: 完成追踪
        if LANGSMITH_AVAILABLE and self._langsmith_run:
            try:
                duration = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
                finish_run(
                    self._langsmith_run,
                    status="success",
                    outputs={
                        "tool_calls": self.tool_calls,
                        "duration": duration,
                        "query": self._current_query
                    }
                )
                self._langsmith_run = None
            except Exception:
                pass
        
        if self.show_progress and self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()
            print(f"\n{'='*70}")
            print(f"✅ 分析完成!")
            print(f"⏱️  总耗时: {duration:.2f}秒")
            print(f"🔧 工具调用: {self.tool_calls}次")
            print(f"{'='*70}\n")

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> Any:
        """LLM 开始生成时的回调"""
        self.step_count += 1
        if self.show_details:
            print(f"🤔 AI 思考中... (第 {self.step_count} 轮)")

    def on_llm_end(self, response, **kwargs) -> Any:
        """LLM 完成生成时的回调"""
        if self.show_details:
            print(f"✓ 完成思考")

    def on_chain_error(self, error: Exception, **kwargs) -> None:
        """Chain 错误时的回调"""
        # LangSmith: 记录错误
        if LANGSMITH_AVAILABLE and self._langsmith_run:
            try:
                finish_run(
                    self._langsmith_run,
                    status="error",
                    error=str(error)
                )
                self._langsmith_run = None
            except Exception:
                pass
        
        print(f"\n❌ 错误: {str(error)}")


# ============================================
# 流式输出器
# ============================================

class AsyncFinancialStreamer:
    """金融分析流式输出器 - 兼容同步和异步"""

    def __init__(self, show_progress: bool = True, show_details: bool = True):
        self.show_progress = show_progress
        self.show_details = show_details

    def stream_analysis(self, agent, query: str) -> Dict[str, Any]:
        """
        执行流式金融分析（同步版本）
        
        Args:
            agent: LangChainFinancialAgent 实例
            query: 分析查询
            
        Returns:
            分析结果字典
        """
        try:
            # 创建流式回调处理器
            callback = FinancialStreamingCallbackHandler(
                show_progress=self.show_progress,
                show_details=self.show_details
            )
            
            # 临时替换 agent 的 callback
            original_callback = agent.callback
            agent.callback = callback
            
            # 执行分析
            result = agent.analyze(query)
            
            # 恢复原始 callback
            agent.callback = original_callback
            
            return result
            
        except Exception as e:
            print(f"\n❌ 流式分析失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "output": f"分析失败: {str(e)}"
            }

    def sync_stream_analysis(self, agent, query: str) -> str:
        """
        同步版本的流式分析（返回字符串）
        
        Args:
            agent: Agent 实例
            query: 分析查询
            
        Returns:
            分析结果字符串
        """
        result = self.stream_analysis(agent, query)
        return result.get("output", str(result))


# ============================================
# 进度指示器
# ============================================

class ProgressIndicator:
    """简单的进度条显示组件"""

    def __init__(self, total_steps: int = 10, width: int = 50):
        self.total_steps = total_steps
        self.current_step = 0
        self.width = width
        self.start_time = None

    def start(self, message: str = "开始分析"):
        """开始进度跟踪"""
        self.start_time = time.time()
        print(f"🚀 {message}")
        print("─" * 60)

    def update(self, step_name: str):
        """更新进度"""
        self.current_step += 1
        progress = min(self.current_step / self.total_steps, 1.0)
        
        # 创建进度条
        filled = int(self.width * progress)
        bar = "█" * filled + "░" * (self.width - filled)
        
        # 计算时间
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        print(f"\r[{bar}] {progress*100:5.1f}% | {step_name[:30]:<30}", end="", flush=True)

    def finish(self, success: bool = True):
        """完成进度跟踪"""
        elapsed = time.time() - self.start_time if self.start_time else 0
        status = "✅ 成功" if success else "❌ 失败"
        print(f"\n{status} | 总耗时: {elapsed:.2f}秒\n")


# ============================================
# 分析仪表板
# ============================================

class FinancialDashboard:
    """金融分析实时仪表板"""

    def __init__(self):
        self.metrics = {
            "total_analyses": 0,
            "success_count": 0,
            "error_count": 0,
            "total_duration": 0.0,
            "tool_usage": {}
        }
        self.session_history = []

    def record_analysis(self, query: str, success: bool, duration: float, tool_calls: int):
        """记录分析会话"""
        self.metrics["total_analyses"] += 1
        
        if success:
            self.metrics["success_count"] += 1
        else:
            self.metrics["error_count"] += 1
        
        self.metrics["total_duration"] += duration
        
        session = {
            "query": query,
            "success": success,
            "duration": duration,
            "tool_calls": tool_calls,
            "timestamp": datetime.now()
        }
        self.session_history.append(session)

    def display_dashboard(self):
        """显示仪表板"""
        print(f"\n{'='*60}")
        print("📊 FinSight 分析仪表板")
        print(f"{'='*60}")
        
        total = self.metrics["total_analyses"]
        if total > 0:
            success_rate = (self.metrics["success_count"] / total) * 100
            avg_duration = self.metrics["total_duration"] / total
            
            print(f"📈 总分析次数: {total}")
            print(f"✅ 成功分析: {self.metrics['success_count']} ({success_rate:.1f}%)")
            print(f"❌ 失败分析: {self.metrics['error_count']}")
            print(f"⏱️  平均耗时: {avg_duration:.2f}秒")
            
            if self.session_history:
                print(f"\n📋 最近分析:")
                for i, session in enumerate(self.session_history[-5:], 1):
                    status = "✓" if session["success"] else "✗"
                    print(f"   {i}. [{status}] {session['query'][:40]:<40} {session['duration']:.1f}s")
        else:
            print("暂无分析记录")
        
        print(f"{'='*60}\n")

    def get_metrics(self) -> Dict[str, Any]:
        """获取指标统计"""
        total = self.metrics["total_analyses"]
        return {
            "total": total,
            "success": self.metrics["success_count"],
            "error": self.metrics["error_count"],
            "success_rate": (self.metrics["success_count"] / total * 100) if total > 0 else 0,
            "avg_duration": (self.metrics["total_duration"] / total) if total > 0 else 0
        }


# ============================================
# 导出接口
# ============================================

__all__ = [
    "FinancialStreamingCallbackHandler",
    "AsyncFinancialStreamer",
    "ProgressIndicator",
    "FinancialDashboard"
]
