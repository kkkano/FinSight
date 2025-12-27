import asyncio
from typing import Dict, List, Any, Optional
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput
from backend.agents.price_agent import PriceAgent
from backend.agents.news_agent import NewsAgent
from backend.agents.deep_search_agent import DeepSearchAgent
from backend.agents.macro_agent import MacroAgent
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
            # 未来添加 technical, fundamental 等
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
