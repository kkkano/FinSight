import asyncio
from typing import Dict, List, Any, Optional
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput
from backend.agents.price_agent import PriceAgent
from backend.agents.news_agent import NewsAgent
from backend.agents.deep_search_agent import DeepSearchAgent
from backend.agents.macro_agent import MacroAgent
from backend.agents.technical_agent import TechnicalAgent
from backend.agents.fundamental_agent import FundamentalAgent
from backend.orchestration.forum import ForumHost, ForumOutput

class AgentSupervisor:
    """
    Agent 调度器 (Supervisor)
    负责并行调用各专家 Agent，并将结果汇总给 ForumHost
    """
    def __init__(self, llm, tools_module, cache, circuit_breaker=None):
        self.llm = llm
        self.forum = ForumHost(llm)

        # 初始化 Agents
        self.agents: Dict[str, BaseFinancialAgent] = {
            "price": PriceAgent(llm, cache, tools_module, circuit_breaker),
            "news": NewsAgent(llm, cache, tools_module, circuit_breaker),
            "deep_search": DeepSearchAgent(llm, cache, tools_module, circuit_breaker),
            "macro": MacroAgent(llm, cache, tools_module, circuit_breaker),
            "technical": TechnicalAgent(llm, cache, tools_module, circuit_breaker),
            "fundamental": FundamentalAgent(llm, cache, tools_module, circuit_breaker),
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
        # 1. 并行调用常驻 Agent
        tasks = []
        agent_names = []

        for name, agent in self.agents.items():
            tasks.append(agent.research(query, ticker))
            agent_names.append(name)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 2. 过滤失败的
        valid_outputs: Dict[str, AgentOutput] = {}
        errors = []

        for name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                errors.append(f"{name} failed: {str(result)}")
                print(f"[Supervisor] {name} Agent 失败: {result}")
            else:
                valid_outputs[name] = result

        # 3. Forum 综合 (注入用户画像)
        forum_result = await self.forum.synthesize(valid_outputs, user_profile=user_profile)

        return {
            "forum_output": forum_result,
            "agent_outputs": valid_outputs,
            "errors": errors
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
        
        # 1. 通知开始
        yield json.dumps({
            "type": "supervisor_start",
            "message": f"开始分析 {ticker}...",
            "agents": list(self.agents.keys())
        }, ensure_ascii=False)
        
        # 2. 并行调用各 Agent 的流式接口（如果有），否则调用同步接口
        agent_results = {}
        agent_errors = []
        
        for name, agent in self.agents.items():
            yield json.dumps({
                "type": "agent_start",
                "agent": name,
                "message": f"{name} Agent 开始分析..."
            }, ensure_ascii=False)
            
            try:
                # 优先使用流式接口
                if hasattr(agent, 'analyze_stream'):
                    async for chunk in agent.analyze_stream(query, ticker):
                        # 转发 Agent 的流式输出
                        yield chunk
                    # 获取最终结果
                    result = await agent.research(query, ticker)
                else:
                    # 回退到同步接口
                    result = await agent.research(query, ticker)
                    yield json.dumps({
                        "type": "agent_done",
                        "agent": name,
                        "status": "success",
                        "summary": result.summary[:100] if result.summary else ""
                    }, ensure_ascii=False)
                
                agent_results[name] = result
                
            except Exception as e:
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
        
        try:
            forum_result = await self.forum.synthesize(agent_results, user_profile=user_profile)
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
                    "errors": agent_errors
                },
                "agent_outputs": serialized_outputs,
            }, ensure_ascii=False)
            
        except Exception as e:
            yield json.dumps({
                "type": "error",
                "message": f"Forum 综合失败: {str(e)}"
            }, ensure_ascii=False)
