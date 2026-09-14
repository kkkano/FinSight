# -*- coding: utf-8 -*-
"""
统一 Supervisor 架构提案
========================

核心理念：
1. 不区分 CHAT/REPORT，统一由 Supervisor 处理
2. LLM 自动选择需要的 Agent
3. 信息不足时智能追问
4. 根据复杂度决定综合方式
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import asyncio


# ========== 数据结构 ==========

class QueryComplexity(Enum):
    """查询复杂度"""
    SIMPLE = "simple"      # 单一信息查询（价格、新闻）
    MODERATE = "moderate"  # 多维度查询（价格+新闻+情绪）
    COMPLEX = "complex"    # 深度分析（完整报告）


@dataclass
class QueryAnalysis:
    """查询分析结果"""
    is_complete: bool           # 信息是否完整
    missing_info: List[str]     # 缺失的信息
    clarify_question: str       # 追问问题
    complexity: QueryComplexity # 查询复杂度
    suggested_agents: List[str] # 建议的 Agent
    tickers: List[str]          # 识别到的股票


@dataclass
class AgentResult:
    """Agent 执行结果"""
    agent_name: str
    success: bool
    data: Dict[str, Any]
    summary: str
    confidence: float


# ========== 统一 Supervisor ==========

class UnifiedSupervisor:
    """
    统一的 Agent 编排器

    特点：
    1. 单一入口处理所有对话
    2. 智能选择需要的 Agent
    3. 信息不足时追问
    4. 根据复杂度决定综合方式
    """

    AGENT_CAPABILITIES = {
        "price": {
            "description": "实时股价、涨跌幅、成交量",
            "keywords": ["价格", "股价", "多少钱", "涨", "跌", "price"],
            "requires_ticker": True,
        },
        "news": {
            "description": "最新新闻、公告、事件",
            "keywords": ["新闻", "消息", "公告", "事件", "news"],
            "requires_ticker": True,
        },
        "technical": {
            "description": "技术指标、K线形态、趋势分析",
            "keywords": ["技术", "K线", "均线", "MACD", "RSI", "technical"],
            "requires_ticker": True,
        },
        "fundamental": {
            "description": "财务数据、估值、基本面",
            "keywords": ["财报", "营收", "利润", "估值", "PE", "fundamental"],
            "requires_ticker": True,
        },
        "sentiment": {
            "description": "市场情绪、恐慌贪婪指数",
            "keywords": ["情绪", "恐慌", "贪婪", "sentiment", "fear", "greed"],
            "requires_ticker": False,
        },
        "macro": {
            "description": "宏观经济、政策、利率",
            "keywords": ["宏观", "经济", "利率", "CPI", "GDP", "FOMC"],
            "requires_ticker": False,
        },
    }

    def __init__(self, llm, agents: Dict[str, Any], cache=None):
        self.llm = llm
        self.agents = agents
        self.cache = cache

    async def process(self, query: str, context: Dict = None) -> Dict[str, Any]:
        """
        统一处理入口

        流程：
        1. 分析查询 → 判断信息完整性 + 复杂度 + 需要的Agent
        2. 信息不足 → 追问
        3. 执行 Agent
        4. 综合结果
        """
        context = context or {}

        # Step 1: 分析查询
        analysis = await self._analyze_query(query, context)

        # Step 2: 信息不足则追问
        if not analysis.is_complete:
            return {
                "success": True,
                "type": "clarify",
                "response": analysis.clarify_question,
                "missing_info": analysis.missing_info,
            }

        # Step 3: 执行选中的 Agent
        agent_results = await self._execute_agents(
            analysis.suggested_agents,
            query,
            analysis.tickers,
        )

        # Step 4: 综合结果
        response = await self._synthesize_results(
            query,
            agent_results,
            analysis.complexity,
        )

        return response

    async def _analyze_query(self, query: str, context: Dict) -> QueryAnalysis:
        """
        分析用户查询

        使用 LLM 判断：
        1. 需要哪些 Agent
        2. 信息是否完整
        3. 查询复杂度
        """
        # 先用规则快速提取 ticker
        from backend.config.ticker_mapping import extract_tickers
        extracted = extract_tickers(query)
        tickers = extracted.get("tickers", [])

        # LLM 分析
        prompt = f"""分析用户的金融查询，返回 JSON：

用户查询: {query}
已识别股票: {tickers}
对话上下文: {context.get('summary', '无')}

返回格式:
{{
    "needs_agents": ["price", "news", ...],  // 需要的Agent
    "is_complete": true/false,  // 信息是否完整
    "missing_info": ["ticker", ...],  // 缺失的信息
    "complexity": "simple/moderate/complex",  // 复杂度
    "clarify_question": "..."  // 如果需要追问的问题
}}

可用Agent: {list(self.AGENT_CAPABILITIES.keys())}

规则:
- 如果需要股票相关Agent但没有股票代码，is_complete=false
- simple: 只需1-2个Agent的简单查询
- moderate: 需要3-4个Agent的多维度查询
- complex: 需要深度分析的完整报告

只返回JSON，不要其他内容。
"""

        try:
            response = await self._call_llm(prompt)
            result = self._parse_json(response)

            return QueryAnalysis(
                is_complete=result.get("is_complete", False),
                missing_info=result.get("missing_info", []),
                clarify_question=result.get("clarify_question", "请提供更多信息。"),
                complexity=QueryComplexity(result.get("complexity", "simple")),
                suggested_agents=result.get("needs_agents", ["price"]),
                tickers=tickers,
            )
        except Exception as e:
            # 降级：用规则判断
            return self._rule_based_analysis(query, tickers)

    def _rule_based_analysis(self, query: str, tickers: List[str]) -> QueryAnalysis:
        """规则兜底分析"""
        query_lower = query.lower()
        suggested_agents = []

        # 匹配 Agent
        for agent_name, config in self.AGENT_CAPABILITIES.items():
            if any(kw in query_lower for kw in config["keywords"]):
                suggested_agents.append(agent_name)

        # 默认至少查价格
        if not suggested_agents:
            suggested_agents = ["price", "news"]

        # 检查是否需要 ticker
        needs_ticker = any(
            self.AGENT_CAPABILITIES[a].get("requires_ticker", False)
            for a in suggested_agents
        )

        is_complete = not needs_ticker or bool(tickers)

        # 判断复杂度
        if len(suggested_agents) <= 2:
            complexity = QueryComplexity.SIMPLE
        elif len(suggested_agents) <= 4:
            complexity = QueryComplexity.MODERATE
        else:
            complexity = QueryComplexity.COMPLEX

        # 分析关键词判断是否深度分析
        deep_keywords = ["分析", "报告", "研究", "详细", "深度", "analyze", "report"]
        if any(kw in query_lower for kw in deep_keywords):
            complexity = QueryComplexity.COMPLEX
            suggested_agents = ["price", "news", "technical", "fundamental"]

        return QueryAnalysis(
            is_complete=is_complete,
            missing_info=["ticker"] if not is_complete else [],
            clarify_question="请提供股票代码（如 AAPL）或公司名称。",
            complexity=complexity,
            suggested_agents=suggested_agents,
            tickers=tickers,
        )

    async def _execute_agents(
        self,
        agent_names: List[str],
        query: str,
        tickers: List[str],
    ) -> List[AgentResult]:
        """并行执行多个 Agent"""
        tasks = []

        for name in agent_names:
            agent = self.agents.get(name)
            if agent:
                tasks.append(self._run_agent(name, agent, query, tickers))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return [r for r in results if isinstance(r, AgentResult)]

    async def _run_agent(
        self,
        name: str,
        agent: Any,
        query: str,
        tickers: List[str],
    ) -> AgentResult:
        """执行单个 Agent"""
        try:
            ticker = tickers[0] if tickers else None

            if hasattr(agent, "analyze"):
                result = await agent.analyze(query, ticker)
            elif hasattr(agent, "execute"):
                result = await agent.execute(query, ticker)
            else:
                result = {"error": "Agent has no analyze/execute method"}

            return AgentResult(
                agent_name=name,
                success=True,
                data=result,
                summary=result.get("summary", ""),
                confidence=result.get("confidence", 0.8),
            )
        except Exception as e:
            return AgentResult(
                agent_name=name,
                success=False,
                data={"error": str(e)},
                summary=f"Agent {name} failed: {e}",
                confidence=0.0,
            )

    async def _synthesize_results(
        self,
        query: str,
        results: List[AgentResult],
        complexity: QueryComplexity,
    ) -> Dict[str, Any]:
        """综合 Agent 结果"""

        if complexity == QueryComplexity.SIMPLE:
            # 简单查询：直接拼接
            return self._simple_synthesis(query, results)

        elif complexity == QueryComplexity.MODERATE:
            # 中等复杂度：LLM 简单综合
            return await self._moderate_synthesis(query, results)

        else:
            # 复杂查询：Forum 深度综合
            return await self._complex_synthesis(query, results)

    def _simple_synthesis(self, query: str, results: List[AgentResult]) -> Dict:
        """简单综合 - 直接拼接"""
        summaries = [r.summary for r in results if r.success and r.summary]

        return {
            "success": True,
            "type": "chat",
            "response": "\n\n".join(summaries) if summaries else "未找到相关信息。",
            "agent_outputs": {r.agent_name: r.data for r in results},
        }

    async def _moderate_synthesis(self, query: str, results: List[AgentResult]) -> Dict:
        """中等综合 - LLM 整合"""
        agent_data = {r.agent_name: r.data for r in results if r.success}

        prompt = f"""根据以下数据回答用户问题：

用户问题: {query}

收集到的数据:
{agent_data}

请综合以上信息，给出简洁专业的回答。
"""
        response = await self._call_llm(prompt)

        return {
            "success": True,
            "type": "chat",
            "response": response,
            "agent_outputs": agent_data,
        }

    async def _complex_synthesis(self, query: str, results: List[AgentResult]) -> Dict:
        """复杂综合 - Forum 深度分析"""
        # 这里调用现有的 ForumHost
        from backend.orchestration.forum import ForumHost

        forum = ForumHost(self.llm)

        agent_outputs = {r.agent_name: r.data for r in results if r.success}

        report = await forum.synthesize(
            query=query,
            agent_outputs=agent_outputs,
        )

        return {
            "success": True,
            "type": "report",
            "response": report.get("summary", ""),
            "report": report,
            "agent_outputs": agent_outputs,
        }

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        from langchain_core.messages import HumanMessage
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return response.content

    def _parse_json(self, text: str) -> Dict:
        """解析 JSON"""
        import json
        import re

        # 清理 markdown 代码块
        cleaned = re.sub(r"```json\s*", "", text)
        cleaned = re.sub(r"```\s*", "", cleaned)

        # 提取 JSON
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return {}


# ========== 使用示例 ==========

"""
# main.py 中的使用

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    supervisor = UnifiedSupervisor(
        llm=current_llm,
        agents={
            "price": price_agent,
            "news": news_agent,
            "technical": technical_agent,
            "fundamental": fundamental_agent,
            "sentiment": sentiment_agent,
            "macro": macro_agent,
        },
        cache=cache,
    )

    result = await supervisor.process(
        query=request.query,
        context={"summary": context.get_summary()},
    )

    # 流式输出
    async def generate():
        if result["type"] == "clarify":
            yield f"data: {json.dumps({'type': 'clarify', 'content': result['response']})}\n\n"
        else:
            # 正常响应
            yield f"data: {json.dumps({'type': 'token', 'content': result['response']})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'report': result.get('report')})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
"""
