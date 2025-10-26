#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FinSight 流式支持模块
实现实时流式输出和用户友好的进度显示
"""

import asyncio
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable, Generator
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.messages import BaseMessage
# 导入Agent相关
try:
    from langchain.agents import AgentAction, AgentFinish
except ImportError:
    # 如果导入失败，使用兼容性实现
    from collections import namedtuple

    # 简单的兼容性定义
    AgentAction = namedtuple('AgentAction', ['tool', 'tool_input'])
    AgentFinish = namedtuple('AgentFinish', ['return_values', 'log'])

from langchain_agent import FINANCIAL_TOOLS

# ============================================
# 进度条和可视化组件
# ============================================

class ProgressIndicator:
    """进度条显示组件"""

    def __init__(self, total_steps: int, width: int = 50):
        self.total_steps = total_steps
        self.current_step = 0
        self.width = width
        self.start_time = None

    def start(self):
        """开始进度跟踪"""
        self.start_time = time.time()
        print(f"🚀 开始金融分析 ({self.total_steps}个步骤)")
        print("─" * 60)

    def update(self, step_name: str, progress: Optional[float] = None):
        """更新进度"""
        self.current_step += 1
        if progress is None:
            progress = self.current_step / self.total_steps

        # 创建进度条
        filled = int(self.width * progress)
        bar = "█" * filled + "░" * (self.width - filled)

        # 计算时间
        elapsed = time.time() - self.start_time if self.start_time else 0
        if self.current_step > 0:
            eta = elapsed / self.current_step * (self.total_steps - self.current_step)
            eta_str = f"{int(eta):02d}:{int(eta % 60):02d}"
        else:
            eta_str = "--:--"

        print(f"\r[{bar}] {progress*100:5.1f}% | {self.current_step}/{self.total_steps} | ETA: {eta_str} | {step_name}", end="", flush=True)

    def finish(self, success: bool = True):
        """完成进度跟踪"""
        elapsed = time.time() - self.start_time if self.start_time else 0
        status = "✅ 成功" if success else "❌ 失败"
        print(f"\n\n{status} | 总耗时: {int(elapsed):02d}:{int(elapsed % 60):02d}")

class StepTracker:
    """步骤跟踪器"""

    def __init__(self):
        self.steps = []
        self.start_time = None

    def add_step(self, step_type: str, description: str, details: str = ""):
        """添加步骤"""
        step = {
            "type": step_type,
            "description": description,
            "details": details,
            "timestamp": datetime.now()
        }
        self.steps.append(step)

    def get_summary(self) -> Dict[str, int]:
        """获取步骤摘要统计"""
        summary = {
            "total": len(self.steps),
            "thought": 0,
            "action": 0,
            "observation": 0,
            "error": 0
        }

        for step in self.steps:
            summary[step["type"]] = summary.get(step["type"], 0) + 1

        return summary

# ============================================
# 流式回调处理器
# ============================================

class FinancialStreamingCallbackHandler(BaseCallbackHandler):
    """金融分析专用的流式回调处理器"""

    def __init__(self, show_progress: bool = True, show_details: bool = True):
        self.show_progress = show_progress
        self.show_details = show_details
        self.step_tracker = StepTracker()
        self.progress = None
        self.analysis_ticker = None
        self.start_time = None

        # 统计信息
        self.tool_calls = 0
        self.thought_count = 0
        self.observation_count = 0

    def on_agent_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Agent开始时的回调"""
        self.start_time = datetime.now()
        self.analysis_ticker = self._extract_ticker_from_input(inputs)

        print(f"\n{'='*70}")
        print(f"📈 FinSight AI金融分析 - LangChain 1.0.1")
        print(f"{'='*70}")
        print(f"🎯 分析目标: {self.analysis_ticker if self.analysis_ticker else '金融产品'}")
        print(f"📅 开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📊 可用工具: {len(FINANCIAL_TOOLS)}个")
        print("─" * 70)

        # 初始化进度条
        if self.show_progress:
            self.progress = ProgressIndicator(total_steps=10)
            self.progress.start()

    def on_agent_action(self, action: AgentAction, **kwargs) -> Any:
        """Agent执行动作时的回调"""
        self.tool_calls += 1

        if self.show_details:
            tool_name = action.tool
            tool_input = action.tool_input

            if self.progress:
                self.progress.update(f"使用 {tool_name}")

            # 详细显示工具信息
            print(f"\n🔧 步骤 {self.tool_calls}: 使用工具 {tool_name}")

            if tool_input and isinstance(tool_input, dict):
                if "ticker" in tool_input:
                    print(f"   📊 股票代码: {tool_input['ticker']}")
                elif "query" in tool_input:
                    print(f"   🔍 搜索查询: {tool_input['query'][:50]}...")
                else:
                    print(f"   📝 输入参数: {str(tool_input)[:100]}...")

            # 添加到步骤跟踪
            self.step_tracker.add_step("action", f"调用{tool_name}", str(tool_input)[:100])

    def on_agent_finish(self, finish: AgentFinish, **kwargs) -> Any:
        """Agent完成时的回调"""
        end_time = datetime.now()
        duration = end_time - self.start_time

        if self.progress:
            self.progress.finish(success=True)

        # 显示完成信息
        print(f"\n{'='*70}")
        print("✅ 分析完成!")
        print(f"⏱️  总耗时: {duration.total_seconds():.2f}秒")
        print(f"🔧 工具调用: {self.tool_calls}次")
        print(f"📊 数据点数: {self.observation_count}个")

        # 显示步骤统计
        summary = self.step_tracker.get_summary()
        print(f"📋 步骤统计: 思考{summary['thought']}次, 动作{summary['action']}次, 观察{summary['observation']}次")

        # 生成分析摘要
        if self.show_details:
            print(f"\n📋 分析摘要:")
            print(f"   - 分析标的: {self.analysis_ticker if self.analysis_ticker else '未识别'}")
            print(f"   - 工具使用: {self.tool_calls}次")
            print(f"   - 数据收集: {self.observation_count}个数据点")
            print(f"   - 完成时间: {end_time.strftime('%H:%M:%S')}")

        print(f"{'='*70}")

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> Any:
        """工具开始执行时的回调"""
        tool_name = serialized.get("name", "unknown_tool")

        if self.show_details:
            print(f"   🛠️  正在调用: {tool_name}")
            if input_str and input_str != "{}":
                try:
                    data = json.loads(input_str)
                    if "ticker" in data:
                        print(f"   📊 参数: {data['ticker']}")
                    elif "query" in data:
                        print(f"   🔍 参数: {data['query'][:50]}...")
                except:
                    print(f"   📝 输入: {input_str[:100]}...")

    def on_tool_end(self, output: str, **kwargs) -> Any:
        """工具执行完成时的回调"""
        self.observation_count += 1

        if self.show_details:
            print(f"   ✅ 完成! 获得数据点 #{self.observation_count}")

            # 显示输出摘要
            if len(output) > 200:
                print(f"   📄 结果摘要: {output[:200]}...")
            else:
                print(f"   📄 结果: {output}")

            # 添加到步骤跟踪
            self.step_tracker.add_step("observation", f"获得结果", f"长度{len(output)}字符")

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> Any:
        """LLM开始生成时的回调"""
        self.thought_count += 1
        if self.show_details and self.progress:
            self.progress.update("AI思考中")

    def on_llm_new_token(self, token: str, **kwargs) -> Any:
        """处理新的token（用于实时显示）"""
        # 可以在这里实现token级的实时显示
        pass

    def on_llm_end(self, response: LLMResult, **kwargs) -> Any:
        """LLM完成生成时的回调"""
        if self.show_details and self.progress:
            self.progress.update("生成报告")

        # 添加到步骤跟踪
        self.step_tracker.add_step("thought", "AI分析", f"生成{len(response.generations[0].text) if response.generations else 0}字符")

    def _extract_ticker_from_input(self, inputs: Dict[str, Any]) -> str:
        """从输入中提取股票代码"""
        if "input" in inputs:
            query = inputs["input"]
            import re
            ticker_pattern = r'\b([A-Z]{1,5})\b'
            matches = re.findall(ticker_pattern, query.upper())
            return matches[0] if matches else "未知"
        return "未知"

# ============================================
# 异步流式输出器
# ============================================

class AsyncFinancialStreamer:
    """异步金融分析流式输出器"""

    def __init__(self, show_progress: bool = True, show_details: bool = True):
        self.show_progress = show_progress
        self.show_details = show_details
        self.callback_handler = None

    async def stream_analysis(self, agent, query: str, session_id: Optional[str] = None) -> str:
        """执行流式金融分析"""
        print(f"\n🎯 开始流式分析: {query}")
        print("=" * 70)

        try:
            # 创建回调处理器
            self.callback_handler = FinancialStreamingCallbackHandler(
                show_progress=self.show_progress,
                show_details=self.show_details
            )

            # 执行异步分析
            result = await agent.analyze_async(query, session_id)

            return result

        except Exception as e:
            print(f"\n❌ 流式分析失败: {str(e)}")
            return f"分析失败: {str(e)}"

    def sync_stream_analysis(self, agent, query: str, session_id: Optional[str] = None) -> str:
        """同步版本的流式分析"""
        return asyncio.run(self.stream_analysis(agent, query, session_id))

# ============================================
# 实时分析仪表板
# ============================================

class FinancialDashboard:
    """金融分析实时仪表板"""

    def __init__(self):
        self.current_analysis = None
        self.metrics = {
            "total_analyses": 0,
            "success_count": 0,
            "error_count": 0,
            "avg_duration": 0.0,
            "tool_usage": {}
        }
        self.session_history = []

    def start_analysis(self, query: str, session_id: Optional[str] = None):
        """开始新分析"""
        self.current_analysis = {
            "query": query,
            "session_id": session_id,
            "start_time": datetime.now(),
            "status": "running",
            "steps": [],
            "metrics": {
                "tool_calls": 0,
                "thought_count": 0,
                "observation_count": 0
            }
        }

    def update_step(self, step_type: str, details: str):
        """更新分析步骤"""
        if self.current_analysis:
            step = {
                "type": step_type,
                "details": details,
                "timestamp": datetime.now()
            }
            self.current_analysis["steps"].append(step)

            # 更新指标
            if step_type == "action":
                self.current_analysis["metrics"]["tool_calls"] += 1
                tool_name = details.split()[1] if "使用" in details else "unknown"
                self.metrics["tool_usage"][tool_name] = self.metrics["tool_usage"].get(tool_name, 0) + 1
            elif step_type == "thought":
                self.current_analysis["metrics"]["thought_count"] += 1
            elif step_type == "observation":
                self.current_analysis["metrics"]["observation_count"] += 1

    def finish_analysis(self, result: str, success: bool = True):
        """完成分析"""
        if self.current_analysis:
            duration = (datetime.now() - self.current_analysis["start_time"]).total_seconds()

            self.current_analysis["status"] = "completed" if success else "failed"
            self.current_analysis["end_time"] = datetime.now()
            self.current_analysis["duration"] = duration
            self.current_analysis["result"] = result

            # 更新总体指标
            self.metrics["total_analyses"] += 1
            if success:
                self.metrics["success_count"] += 1
            else:
                self.metrics["error_count"] += 1

            # 更新平均耗时
            total_duration = sum(
                sess.get("duration", 0)
                for sess in self.session_history + [self.current_analysis]
            )
            self.metrics["avg_duration"] = total_duration / len(self.session_history + [self.current_analysis])

            # 添加到历史记录
            self.session_history.append(self.current_analysis)
            self.current_analysis = None

    def get_current_status(self) -> Dict[str, Any]:
        """获取当前分析状态"""
        if self.current_analysis:
            return {
                "status": self.current_analysis["status"],
                "progress": len(self.current_analysis["steps"]),
                "metrics": self.current_analysis["metrics"]
            }
        return {"status": "idle"}

    def display_dashboard(self):
        """显示仪表板"""
        print(f"\n{'='*60}")
        print("📊 FinSight 分析仪表板")
        print(f"{'='*60}")

        # 总体统计
        print(f"📈 总分析次数: {self.metrics['total_analyses']}")
        print(f"✅ 成功分析: {self.metrics['success_count']}")
        print(f"❌ 失败分析: {self.metrics['error_count']}")
        print(f"⏱️  平均耗时: {self.metrics['avg_duration']:.2f}秒")

        # 工具使用统计
        if self.metrics["tool_usage"]:
            print(f"\n🔧 工具使用统计:")
            for tool, count in sorted(self.metrics["tool_usage"].items(), key=lambda x: x[1], reverse=True):
                print(f"   {tool}: {count}次")

        # 当前状态
        current_status = self.get_current_status()
        print(f"\n🔄 当前状态: {current_status['status']}")
        if current_status["status"] != "idle":
            print(f"   进度: {current_status['progress']}步")
            metrics = current_status.get("metrics", {})
            print(f"   工具调用: {metrics.get('tool_calls', 0)}")

        print(f"{'='*60}")

# ============================================
# 导出接口
# ============================================

__all__ = [
    "FinancialStreamingCallbackHandler",
    "AsyncFinancialStreamer",
    "ProgressIndicator",
    "StepTracker",
    "FinancialDashboard"
]