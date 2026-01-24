# -*- coding: utf-8 -*-
"""
[LEGACY] AgentSupervisor - 旧版 Supervisor 实现
==================================================

⚠️ 历史代码警告 (2026-01-24):
- 此模块为旧版轻量级 Supervisor 实现
- 新版完整实现请使用: backend/orchestration/supervisor_agent.py (SupervisorAgent)
- 此模块仍被 ConversationAgent 使用，暂时保留
- 未来计划: 迁移到 SupervisorAgent 后归档到 _archive/

功能对比:
- AgentSupervisor (本文件): 轻量级，仅支持报告生成
- SupervisorAgent (supervisor_agent.py): 完整实现，支持意图分类、多种处理器、流式输出

依赖此模块的文件:
- backend/conversation/agent.py
- backend/tests/test_context_injection.py
- backend/tests/test_deep_research.py
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput
from backend.agents.price_agent import PriceAgent
from backend.agents.news_agent import NewsAgent
from backend.agents.deep_search_agent import DeepSearchAgent
from backend.agents.macro_agent import MacroAgent
from backend.agents.technical_agent import TechnicalAgent
from backend.agents.fundamental_agent import FundamentalAgent
from backend.orchestration.forum import ForumHost, ForumOutput
from backend.orchestration.plan import PlanBuilder, PlanExecutor
from backend.orchestration.budget import BudgetManager, BudgetedTools, BudgetExceededError

class AgentSupervisor:
    """
    Agent 调度器 (Supervisor)
    负责并行调用各专家 Agent，并将结果汇总给 ForumHost
    """
    def __init__(self, llm, tools_module, cache, circuit_breaker=None):
        self.llm = llm
        self.forum = ForumHost(llm)

        self.tools_module = tools_module
        self.cache = cache
        self.circuit_breaker = circuit_breaker

        # init agents
        self.agents: Dict[str, BaseFinancialAgent] = self._build_agents(self.tools_module)

    def _build_agents(self, tools_module) -> Dict[str, BaseFinancialAgent]:
        return {
            "price": PriceAgent(self.llm, self.cache, tools_module, self.circuit_breaker),
            "news": NewsAgent(self.llm, self.cache, tools_module, self.circuit_breaker),
            "deep_search": DeepSearchAgent(self.llm, self.cache, tools_module, self.circuit_breaker),
            "macro": MacroAgent(self.llm, self.cache, tools_module, self.circuit_breaker),
            "technical": TechnicalAgent(self.llm, self.cache, tools_module, self.circuit_breaker),
            "fundamental": FundamentalAgent(self.llm, self.cache, tools_module, self.circuit_breaker),
        }

    async def analyze(self, query: str, ticker: str, user_profile: Optional[Any] = None) -> Dict[str, Any]:
        """
        执行完整分析流程：
        1. 并行调用 Agent
        2. 收集结果
        3. Forum 综合

        Args:
            query: 用户查询
            ticker: 股票代码
            user_profile: 用户画像 (UserProfile 对象)
        """
        budget = BudgetManager.from_env()
        tools_module = BudgetedTools(self.tools_module, budget) if self.tools_module else self.tools_module
        agents = self._build_agents(tools_module)

        plan = PlanBuilder.build_report_plan(query, ticker, list(agents.keys()))
        executor = PlanExecutor(agents, self.forum, budget=budget)
        execution = await executor.execute(plan, query, ticker, user_profile=user_profile)
        execution["budget"] = budget.snapshot()

        return {
            "forum_output": execution.get("forum_output"),
            "agent_outputs": execution.get("agent_outputs"),
            "errors": execution.get("errors"),
            "plan": execution.get("plan"),
            "trace": execution.get("trace"),
            "budget": execution.get("budget"),
        }

    def get_agent(self, name: str) -> Optional[BaseFinancialAgent]:
        return self.agents.get(name)

    def _serialize_output(self, output: AgentOutput) -> Dict[str, Any]:
        evidence_items = []
        for ev in getattr(output, "evidence", []) or []:
            evidence_items.append({
                "title": getattr(ev, "title", None),
                "text": getattr(ev, "text", ""),
                "source": getattr(ev, "source", ""),
                "url": getattr(ev, "url", None),
                "timestamp": getattr(ev, "timestamp", None),
                "confidence": getattr(ev, "confidence", None),
                "meta": getattr(ev, "meta", {}) or {},
            })
        return {
            "agent_name": getattr(output, "agent_name", ""),
            "summary": getattr(output, "summary", ""),
            "confidence": getattr(output, "confidence", None),
            "data_sources": getattr(output, "data_sources", []) or [],
            "as_of": getattr(output, "as_of", None),
            "fallback_used": getattr(output, "fallback_used", False),
            "risks": getattr(output, "risks", []) or [],
            "evidence": evidence_items,
            "trace": getattr(output, "trace", []) or [],
        }

    async def analyze_stream(self, query: str, ticker: str, user_profile: Optional[Any] = None):
        """
        流式分析接口，实时报告各 Agent 状态
        
        Yields:
            str: JSON 格式的事件数据
        """
        import json
        budget = BudgetManager.from_env()
        tools_module = BudgetedTools(self.tools_module, budget) if self.tools_module else self.tools_module
        agents = self._build_agents(tools_module)

        
        plan = PlanBuilder.build_report_plan(query, ticker, list(agents.keys()))
        plan_trace: List[Dict[str, Any]] = []

        def _record_plan_event(step, event: str, error: Optional[str] = None, duration_ms: Optional[int] = None):
            plan_trace.append({
                "event": event,
                "step_id": step.step_id,
                "step_type": step.step_type,
                "agent_name": step.agent_name,
                "status": step.status,
                "timestamp": datetime.now().isoformat(),
                "duration_ms": duration_ms,
                "error": error,
            })

        # 1. 通知开始
        yield json.dumps({
            "type": "supervisor_start",
            "message": f"开始分析 {ticker}...",
            "agents": list(agents.keys()),
            "plan": plan.to_dict(),
        }, ensure_ascii=False)
        
        # 2. 并行调用各 Agent 的流式接口（如果有），否则调用同步接口
        agent_results = {}
        agent_errors = []

        for step in [s for s in plan.steps if s.step_type == "agent"]:
            name = step.agent_name
            agent = agents.get(name) if name else None
            if agent is None:
                step.status = "failed"
                step.error = f"agent_not_found:{name}"
                _record_plan_event(step, "step_error", error=step.error)
                agent_errors.append(step.error)
                continue

            step.status = "running"
            step.started_at = datetime.now().isoformat()
            _record_plan_event(step, "step_start")

            yield json.dumps({
                "type": "agent_start",
                "agent": name,
                "message": f"{name} Agent 开始分析..."
            }, ensure_ascii=False)

            start_time = time.perf_counter()
            try:
                budget.consume_round(f"agent:{name}")
                # 优先使用流式接口
                if hasattr(agent, 'analyze_stream'):
                    async for chunk in agent.analyze_stream(query, ticker):
                        yield chunk
                    result = await asyncio.wait_for(agent.research(query, ticker), timeout=step.timeout_seconds)
                else:
                    result = await asyncio.wait_for(agent.research(query, ticker), timeout=step.timeout_seconds)
                    yield json.dumps({
                        "type": "agent_done",
                        "agent": name,
                        "status": "success",
                        "summary": result.summary[:100] if result.summary else ""
                    }, ensure_ascii=False)

                agent_results[name] = result
                step.status = "completed"
                step.finished_at = datetime.now().isoformat()
                step.duration_ms = int((time.perf_counter() - start_time) * 1000)
                _record_plan_event(step, "step_done", duration_ms=step.duration_ms)
            except BudgetExceededError as e:
                step.status = "failed"
                step.error = str(e)
                step.finished_at = datetime.now().isoformat()
                step.duration_ms = int((time.perf_counter() - start_time) * 1000)
                _record_plan_event(step, "step_error", error=step.error, duration_ms=step.duration_ms)
                agent_errors.append(f"{name}: {str(e)}")
                yield json.dumps({
                    "type": "agent_error",
                    "agent": name,
                    "message": str(e)
                }, ensure_ascii=False)
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                step.finished_at = datetime.now().isoformat()
                step.duration_ms = int((time.perf_counter() - start_time) * 1000)
                _record_plan_event(step, "step_error", error=step.error, duration_ms=step.duration_ms)
                agent_errors.append(f"{name}: {str(e)}")
                yield json.dumps({
                    "type": "agent_error",
                    "agent": name,
                    "message": str(e)
                }, ensure_ascii=False)
        
        # 3. Forum 综合
        yield json.dumps({
            "type": "forum_start",
            "message": "正在综合各 Agent 观点..."
        }, ensure_ascii=False)
        
        forum_result = None
        try:
            forum_step = next((s for s in plan.steps if s.step_type == "forum"), None)
            if forum_step is not None:
                forum_step.status = "running"
                forum_step.started_at = datetime.now().isoformat()
                _record_plan_event(forum_step, "step_start")
                start_time = time.perf_counter()
                budget.consume_round("forum")
                forum_result = await asyncio.wait_for(
                    self.forum.synthesize(agent_results, user_profile=user_profile),
                    timeout=forum_step.timeout_seconds,
                )
                forum_step.status = "completed"
                forum_step.finished_at = datetime.now().isoformat()
                forum_step.duration_ms = int((time.perf_counter() - start_time) * 1000)
                _record_plan_event(forum_step, "step_done", duration_ms=forum_step.duration_ms)
            else:
                forum_result = await self.forum.synthesize(agent_results, user_profile=user_profile)
        except Exception as e:
            # Forum 失败时创建一个 fallback ForumOutput
            import logging
            logging.getLogger(__name__).warning(f"[Supervisor] Forum synthesis failed: {e}, using fallback")
            from backend.orchestration.forum import ForumOutput
            # 收集 agent summaries 作为 fallback consensus
            summaries = []
            for name, output in agent_results.items():
                if output and hasattr(output, 'summary') and output.summary:
                    summaries.append(f"**{name}**: {output.summary[:200]}")
            fallback_consensus = "\n\n".join(summaries) if summaries else f"分析数据收集完成，但综合分析暂时不可用。错误: {str(e)}"
            forum_result = ForumOutput(
                consensus=fallback_consensus,
                disagreement="",
                confidence=0.5,
                recommendation="HOLD",
                risks=["综合分析暂时不可用", str(e)[:100]]
            )
            agent_errors.append(f"forum: {str(e)}")

        serialized_outputs = {
            name: self._serialize_output(output)
            for name, output in agent_results.items()
        }
        
        yield json.dumps({
            "type": "forum_done",
            "consensus": forum_result.consensus,
            "confidence": forum_result.confidence,
            "recommendation": forum_result.recommendation
        }, ensure_ascii=False)
        
        # 4. 完成
        yield json.dumps({
            "type": "done",
            "output": {
                "consensus": forum_result.consensus,
                "disagreement": forum_result.disagreement,
                "confidence": forum_result.confidence,
                "recommendation": forum_result.recommendation,
                "risks": forum_result.risks,
                "agents_used": list(agent_results.keys()),
                "errors": agent_errors,
                "budget": budget.snapshot()
            },
            "agent_outputs": serialized_outputs,
            "plan": plan.to_dict(),
            "plan_trace": plan_trace,
        }, ensure_ascii=False)
