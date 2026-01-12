# -*- coding: utf-8 -*-
"""
SupervisorAgent - Supervisor Pattern
Mature multi-Agent architecture: Intent Classification → Supervisor Coordination → Worker Agents → Forum Synthesis
"""

import asyncio
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from backend.orchestration.intent_classifier import IntentClassifier, Intent, ClassificationResult
from backend.orchestration.forum import ForumHost
from backend.agents.base_agent import AgentOutput


@dataclass
class SupervisorResult:
    """Supervisor execution result"""
    success: bool
    intent: Intent
    response: str
    agent_outputs: Dict[str, Any] = None
    forum_output: Any = None
    classification: ClassificationResult = None
    errors: List[str] = None


# Greeting response templates (Chinese output for users)
GREETING_RESPONSES = {
    "default": "您好！我是 FinSight AI 金融助手。我可以帮您查询股票价格、分析新闻、生成投资报告等。请问有什么可以帮您的？",
    "help": "我可以帮您：\n• 查询股票实时价格（如：AAPL 价格）\n• 获取公司新闻（如：特斯拉新闻）\n• 分析市场情绪\n• 生成深度分析报告（如：详细分析苹果）\n• 对比多个股票（如：对比 AAPL 和 MSFT）",
}


class SupervisorAgent:
    """
    Supervisor Agent - Industry-standard multi-Agent architecture

    Flow:
    1. IntentClassifier classifies intent (rule-first, LLM fallback)
    2. Route based on intent
    3. Call corresponding Worker Agent(s)
    4. Forum synthesizes results (complex queries)
    """

    def __init__(self, llm, tools_module, cache, circuit_breaker=None):
        self.llm = llm
        self.tools_module = tools_module

        # 防护：确保 cache 和 circuit_breaker 不为 None
        if cache is None:
            from backend.orchestration.cache import DataCache
            cache = DataCache()
        self.cache = cache

        if circuit_breaker is None:
            from backend.services.circuit_breaker import CircuitBreaker
            circuit_breaker = CircuitBreaker()
        self.circuit_breaker = circuit_breaker

        # Intent classifier
        self.classifier = IntentClassifier(llm)

        # Forum host
        self.forum = ForumHost(llm)

        # Worker Agents (lazy initialization)
        self._agents = None

    @property
    def agents(self):
        """Lazy initialize Agents"""
        if self._agents is None:
            from backend.agents.price_agent import PriceAgent
            from backend.agents.news_agent import NewsAgent
            from backend.agents.deep_search_agent import DeepSearchAgent
            from backend.agents.macro_agent import MacroAgent
            from backend.agents.technical_agent import TechnicalAgent
            from backend.agents.fundamental_agent import FundamentalAgent

            self._agents = {
                "price": PriceAgent(self.llm, self.cache, self.tools_module, self.circuit_breaker),
                "news": NewsAgent(self.llm, self.cache, self.tools_module, self.circuit_breaker),
                "deep_search": DeepSearchAgent(self.llm, self.cache, self.tools_module, self.circuit_breaker),
                "macro": MacroAgent(self.llm, self.cache, self.tools_module, self.circuit_breaker),
                "technical": TechnicalAgent(self.llm, self.cache, self.tools_module, self.circuit_breaker),
                "fundamental": FundamentalAgent(self.llm, self.cache, self.tools_module, self.circuit_breaker),
            }
        return self._agents

    async def process(self, query: str, tickers: List[str] = None, user_profile: Any = None, context_summary: str = None, context_ticker: str = None) -> SupervisorResult:
        """
        Process user query

        Args:
            query: User query
            tickers: Detected stock tickers
            user_profile: User profile
            context_summary: 对话上下文摘要
            context_ticker: 上下文中提取的股票代码

        Returns:
            SupervisorResult
        """
        # 如果上下文中有 ticker 但当前没有，使用上下文的
        if context_ticker and not tickers:
            tickers = [context_ticker]

        # 1. Intent classification (带上下文)
        classification = self.classifier.classify(query, tickers, context_summary=context_summary)
        print(f"[Supervisor] Intent: {classification.intent.value} (method: {classification.method}, confidence: {classification.confidence})")

        # 2. Route based on intent
        intent = classification.intent

        # Simple intents - rule-based direct handling (cost-free)
        if intent == Intent.GREETING:
            return self._handle_greeting(query, classification)

        if intent == Intent.OFF_TOPIC:
            return SupervisorResult(
                success=True,
                intent=intent,
                response="抱歉，我是金融助手，只能回答金融相关的问题。请问有什么股票或市场方面的问题吗？",
                classification=classification
            )

        if intent == Intent.CLARIFY:
            return SupervisorResult(
                success=True,
                intent=intent,
                response="请问您想了解哪只股票？可以告诉我股票代码或公司名称。",
                classification=classification
            )

        # Intents requiring Agent calls
        tickers_list = classification.tickers if isinstance(classification.tickers, list) else list(classification.tickers) if classification.tickers else []
        ticker = tickers_list[0] if tickers_list else None

        # Lightweight intents - single tool/agent
        # 所有 handler 都传递 context_summary，让它们可以根据上下文优化响应
        if intent == Intent.PRICE:
            return await self._handle_price(query, ticker, classification, context_summary)

        # NEWS 意图：子意图分类 - 区分"查询新闻"和"分析新闻"
        if intent == Intent.NEWS:
            news_subintent = self._classify_news_subintent(query)
            if news_subintent == "analyze":
                # 分析类请求：走 NewsAgent + Forum 深度分析
                return await self._handle_news_analysis(query, ticker, classification, context_summary)
            else:
                # 查询类请求：返回原始新闻列表（带链接）
                return await self._handle_news(query, ticker, classification, context_summary)

        if intent == Intent.SENTIMENT:
            return await self._handle_sentiment(query, ticker, classification, context_summary)

        if intent == Intent.TECHNICAL:
            return await self._handle_single_agent("technical", query, ticker, classification, context_summary)

        if intent == Intent.FUNDAMENTAL:
            return await self._handle_single_agent("fundamental", query, ticker, classification, context_summary)

        if intent == Intent.MACRO:
            return await self._handle_single_agent("macro", query, ticker, classification, context_summary)

        # Complex intents - multi-Agent collaboration
        if intent == Intent.REPORT:
            return await self._handle_report(query, ticker, user_profile, classification, context_summary)

        if intent == Intent.COMPARISON:
            return await self._handle_comparison(query, tickers_list, classification, context_summary)

        # Fallback - search
        return await self._handle_search(query, ticker, classification, context_summary)

    def _handle_greeting(self, query: str, classification: ClassificationResult) -> SupervisorResult:
        """Handle greeting - rule-based direct response, free"""
        query_lower = query.lower()
        if any(kw in query_lower for kw in ['帮助', 'help', '能做什么', '你是谁']):
            response = GREETING_RESPONSES["help"]
        else:
            response = GREETING_RESPONSES["default"]

        return SupervisorResult(
            success=True,
            intent=Intent.GREETING,
            response=response,
            classification=classification
        )

    async def _handle_price(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle price query - lightweight tool, with context awareness"""
        if not ticker:
            return SupervisorResult(
                success=False,
                intent=Intent.PRICE,
                response="请提供股票代码，例如：AAPL 价格",
                classification=classification
            )

        try:
            # Direct tool call, no Agent
            price_data = self.tools_module.get_stock_price(ticker)

            if isinstance(price_data, dict) and price_data.get("error"):
                return SupervisorResult(
                    success=False,
                    intent=Intent.PRICE,
                    response=f"获取 {ticker} 价格失败：{price_data.get('error')}",
                    classification=classification
                )

            # Format response
            if isinstance(price_data, dict):
                price = price_data.get("price", "N/A")
                change = price_data.get("change_percent", 0)
                change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"
                base_response = f"**{ticker}** 当前价格: ${price} ({change_str})"
            else:
                base_response = f"**{ticker}** 价格数据: {price_data}"

            # If there's context, enhance response with LLM
            if context_summary:
                try:
                    from langchain_core.messages import HumanMessage
                    prompt = f"""用户询问股票价格，请结合上下文给出简洁回复。

【价格数据】
{base_response}

【对话上下文】
{context_summary}

【用户问题】
{query}

请用1-2句话回复，结合上下文（如之前讨论的话题）给出相关解读。如果上下文不相关，就直接返回价格信息。"""
                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                    return SupervisorResult(
                        success=True,
                        intent=Intent.PRICE,
                        response=response.content if hasattr(response, 'content') else str(response),
                        classification=classification
                    )
                except Exception as e:
                    print(f"[Supervisor] Price context enhancement failed: {e}")

            return SupervisorResult(
                success=True,
                intent=Intent.PRICE,
                response=base_response,
                classification=classification
            )
        except Exception as e:
            return SupervisorResult(
                success=False,
                intent=Intent.PRICE,
                response=f"获取价格时出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    def _classify_news_subintent(self, query: str) -> str:
        """
        NEWS 意图的子分类：区分"查询新闻"和"分析新闻"

        业界最佳实践：Sub-intent Classification
        - 分析类：用户想要对新闻进行解读、分析影响
        - 查询类：用户只是想看最新新闻列表

        Args:
            query: 用户查询

        Returns:
            str: "analyze" 或 "fetch"
        """
        query_lower = query.lower()

        # 分析类关键词（中英文）
        analyze_keywords = [
            # 中文分析词
            "分析", "影响", "解读", "意味", "评估", "看法", "观点",
            "走势", "预测", "解析", "深度", "详细", "怎么看", "会怎样",
            "带来", "导致", "造成", "引发", "说明", "反映", "表明",
            "利好", "利空", "机会", "风险", "趋势", "前景", "展望",
            # 英文分析词
            "analyze", "analysis", "impact", "effect", "implication",
            "interpret", "predict", "forecast", "outlook", "assess"
        ]

        # 检查是否包含分析类关键词
        for keyword in analyze_keywords:
            if keyword in query_lower:
                return "analyze"

        # 默认返回查询类
        return "fetch"

    async def _handle_news(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle news query - 显示原始新闻，有上下文时补充分析"""
        try:
            if ticker:
                news_data = self.tools_module.get_company_news(ticker)
            else:
                news_data = self.tools_module.search(query)

            if isinstance(news_data, dict) and news_data.get("error"):
                return SupervisorResult(
                    success=False,
                    intent=Intent.NEWS,
                    response=f"获取新闻失败：{news_data.get('error')}",
                    classification=classification
                )

            # 格式化原始新闻数据
            base_response = str(news_data) if news_data else "暂无相关新闻"

            # 如果有上下文，在原始新闻后补充简短分析
            if context_summary and news_data:
                try:
                    from langchain_core.messages import HumanMessage
                    prompt = f"""基于以下新闻和对话上下文，用1-2句话补充说明新闻与上下文话题的关联性。

【新闻数据】
{base_response[:1500]}

【对话上下文】
{context_summary}

请只输出简短的关联分析（不要重复新闻内容），格式：\n\n💡 **上下文关联**: [分析内容]"""
                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                    context_analysis = response.content if hasattr(response, 'content') else str(response)
                    # 先显示新闻，再显示上下文分析
                    base_response = f"{base_response}\n\n{context_analysis}"
                except Exception as e:
                    print(f"[Supervisor] News context enhancement failed: {e}")

            return SupervisorResult(
                success=True,
                intent=Intent.NEWS,
                response=base_response,
                classification=classification
            )
        except Exception as e:
            return SupervisorResult(
                success=False,
                intent=Intent.NEWS,
                response=f"获取新闻时出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_general_news(self, query: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """
        Handle general news query without ticker (e.g., "今天有什么财经新闻")
        使用通用搜索获取新闻，并结合上下文分析
        """
        return await self._handle_news(query, None, classification, context_summary)

    async def _handle_news_analysis(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """
        处理新闻分析请求 - 深度分析新闻影响

        当用户请求"分析新闻影响"、"新闻解读"等时调用此方法。
        使用 NewsAgent 的反思循环 + Forum 综合分析。

        Args:
            query: 用户查询
            ticker: 股票代码
            classification: 意图分类结果
            context_summary: 上下文摘要

        Returns:
            SupervisorResult: 包含深度新闻分析的结果
        """
        try:
            from langchain_core.messages import HumanMessage

            # 1. 先获取原始新闻数据
            if ticker:
                news_data = self.tools_module.get_company_news(ticker)
            else:
                news_data = self.tools_module.search(query)

            if isinstance(news_data, dict) and news_data.get("error"):
                return SupervisorResult(
                    success=False,
                    intent=Intent.NEWS,
                    response=f"获取新闻失败：{news_data.get('error')}",
                    classification=classification
                )

            news_text = str(news_data) if news_data else ""

            if not news_text or news_text == "暂无相关新闻":
                return SupervisorResult(
                    success=True,
                    intent=Intent.NEWS,
                    response="暂无相关新闻可供分析",
                    classification=classification
                )

            # 2. 使用 LLM 进行深度新闻分析
            analysis_prompt = f"""你是专业的金融新闻分析师，请对以下新闻进行深度分析。

## 新闻数据
{news_text[:3000]}

## 用户问题
{query}

{"## 对话上下文" + chr(10) + context_summary if context_summary else ""}

## 分析要求
请从以下维度进行专业分析：

### 📰 新闻摘要
简要总结主要新闻事件（2-3句话）

### 📊 市场影响分析
- **短期影响**：对股价/市场的即时影响预判
- **中长期影响**：潜在的持续性影响

### 🎯 投资启示
- 这些新闻对投资者意味着什么？
- 需要关注的后续发展

### ⚠️ 风险提示
- 新闻中隐含的风险因素
- 需要警惕的不确定性

请提供专业、客观、有洞察力的分析，避免空泛的表述。"""

            response = await self.llm.ainvoke([HumanMessage(content=analysis_prompt)])
            analysis_content = response.content if hasattr(response, 'content') else str(response)

            # 3. 组合原始新闻 + 分析结果
            final_response = f"""## 📰 相关新闻

{news_text}

---

## 🔍 深度分析

{analysis_content}"""

            return SupervisorResult(
                success=True,
                intent=Intent.NEWS,
                response=final_response,
                classification=classification
            )

        except Exception as e:
            print(f"[Supervisor] News analysis failed: {e}")
            # Fallback: 返回原始新闻
            return await self._handle_news(query, ticker, classification, context_summary)

    async def _handle_sentiment(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """
        Handle market sentiment query
        如果有上下文（之前讨论的股票/新闻），结合上下文来分析情绪
        """
        try:
            # 1. 获取基础市场情绪数据
            sentiment_data = self.tools_module.get_market_sentiment()
            base_sentiment = str(sentiment_data) if sentiment_data else "暂无市场情绪数据"

            # 2. 如果没有上下文，直接返回基础情绪
            if not context_summary and not ticker:
                return SupervisorResult(
                    success=True,
                    intent=Intent.SENTIMENT,
                    response=base_sentiment,
                    classification=classification
                )

            # 3. 如果有上下文或 ticker，使用 LLM 结合分析
            # 获取相关新闻（如果有 ticker）
            news_content = ""
            if ticker:
                try:
                    news_agent = self.agents.get("news")
                    if news_agent:
                        news_output = await news_agent.research(f"{ticker} news sentiment", ticker)
                        if news_output and news_output.summary:
                            news_content = f"\n\n【{ticker} 相关新闻】\n{news_output.summary}"
                except Exception as e:
                    print(f"[Supervisor] News fetch for sentiment failed: {e}")

            # 4. 构建 Prompt 让 LLM 综合分析
            prompt = f"""请根据以下信息分析市场情绪：

【基础市场情绪】
{base_sentiment}
{news_content}

【对话上下文】
{context_summary or '无'}

【用户问题】
{query}

请综合以上信息，用2-3句话分析当前市场情绪，特别关注上下文中提到的股票或话题。
如果上下文中有具体股票（如 TSLA、EV 等），请针对该股票/行业进行情绪分析。"""

            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            analysis = response.content if hasattr(response, 'content') else str(response)

            return SupervisorResult(
                success=True,
                intent=Intent.SENTIMENT,
                response=analysis,
                classification=classification
            )
        except Exception as e:
            return SupervisorResult(
                success=False,
                intent=Intent.SENTIMENT,
                response=f"获取市场情绪时出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_single_agent(self, agent_name: str, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle single Agent query with context awareness"""
        if not ticker:
            return SupervisorResult(
                success=False,
                intent=classification.intent,
                response=f"请提供股票代码进行{agent_name}分析",
                classification=classification
            )

        try:
            agent = self.agents.get(agent_name)
            if not agent:
                return SupervisorResult(
                    success=False,
                    intent=classification.intent,
                    response=f"Agent {agent_name} 不可用",
                    classification=classification
                )

            # Enhance query with context if available
            enhanced_query = query
            if context_summary:
                enhanced_query = f"{query}\n\n【参考上下文】\n{context_summary}"

            output = await agent.research(enhanced_query, ticker)
            base_response = output.summary if output else "分析完成，但无结果"

            # If context exists and agent returns result, optionally enhance with LLM
            if context_summary and output and output.summary:
                try:
                    from langchain_core.messages import HumanMessage
                    prompt = f"""用户询问{agent_name}分析，请结合上下文优化回复。

【分析结果】
{output.summary[:1500]}

【对话上下文】
{context_summary}

【用户问题】
{query}

请基于分析结果回复，如果上下文中有相关话题，将其融入回答。保持专业简洁。"""
                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                    base_response = response.content if hasattr(response, 'content') else str(response)
                except Exception as e:
                    print(f"[Supervisor] {agent_name} context enhancement failed: {e}")

            return SupervisorResult(
                success=True,
                intent=classification.intent,
                response=base_response,
                agent_outputs={agent_name: output},
                classification=classification
            )
        except Exception as e:
            return SupervisorResult(
                success=False,
                intent=classification.intent,
                response=f"{agent_name} 分析出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_report(self, query: str, ticker: str, user_profile: Any, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle deep report - multi-Agent collaboration with context awareness"""
        if not ticker:
            return SupervisorResult(
                success=False,
                intent=Intent.REPORT,
                response="请提供股票代码进行深度分析，例如：详细分析 AAPL",
                classification=classification
            )

        try:
            # 智能判断上下文相关性：如果上下文中的 ticker 与当前不同，忽略上下文
            relevant_context = None
            if context_summary:
                import re
                # 从上下文中提取可能的 ticker
                context_tickers = re.findall(r'\b([A-Z]{2,5})\b', context_summary)
                stopwords = {'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS', 'PE', 'EPS', 'GDP', 'CPI', 'API', 'OK', 'THE', 'FOR', 'AND', 'NOT'}
                context_tickers = [t for t in context_tickers if t not in stopwords]

                # 判断上下文是否与当前 ticker 相关
                if context_tickers and ticker.upper() not in [t.upper() for t in context_tickers]:
                    # 上下文中有其他 ticker，但没有当前 ticker - 忽略上下文
                    print(f"[Supervisor] 忽略不相关上下文 (context tickers: {context_tickers}, current: {ticker})")
                    relevant_context = None
                else:
                    relevant_context = context_summary

            # Enhance query with context only if relevant
            enhanced_query = query
            if relevant_context:
                enhanced_query = f"{query}\n\n【参考上下文】\n{relevant_context}"

            # Parallel call multiple Agents
            agent_names = ["price", "news", "technical", "fundamental"]
            tasks = [self.agents[name].research(enhanced_query, ticker) for name in agent_names]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect results
            valid_outputs = {}
            errors = []
            for name, result in zip(agent_names, results):
                if isinstance(result, Exception):
                    errors.append(f"{name}: {result}")
                    print(f"[Supervisor] Agent {name} failed: {result}")
                else:
                    valid_outputs[name] = result

            # Forum synthesis - pass relevant_context for better synthesis
            forum_result = await self.forum.synthesize(
                valid_outputs,
                user_profile=user_profile,
                context_summary=relevant_context  # 只传相关上下文
            )

            return SupervisorResult(
                success=True,
                intent=Intent.REPORT,
                response=forum_result.consensus if forum_result else "报告生成完成",
                agent_outputs=valid_outputs,
                forum_output=forum_result,
                classification=classification,
                errors=errors if errors else None
            )
        except Exception as e:
            return SupervisorResult(
                success=False,
                intent=Intent.REPORT,
                response=f"生成报告时出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_comparison(self, query: str, tickers: List[str], classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle comparison analysis with context awareness"""
        if len(tickers) < 2:
            return SupervisorResult(
                success=False,
                intent=Intent.COMPARISON,
                response="请提供至少两个股票代码进行对比，例如：对比 AAPL 和 MSFT",
                classification=classification
            )

        try:
            comparison_data = self.tools_module.get_performance_comparison(tickers)
            base_response = str(comparison_data) if comparison_data else "对比完成，但无数据"

            # If context exists, enhance with LLM
            if context_summary and comparison_data:
                try:
                    from langchain_core.messages import HumanMessage
                    prompt = f"""用户进行股票对比分析，请结合上下文给出解读。

【对比数据】
{base_response[:2000]}

【对话上下文】
{context_summary}

【用户问题】
{query}

请用2-3句话总结对比结果，如果上下文中有相关话题（如投资偏好、之前讨论的股票），将其融入分析。"""
                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                    return SupervisorResult(
                        success=True,
                        intent=Intent.COMPARISON,
                        response=response.content if hasattr(response, 'content') else str(response),
                        classification=classification
                    )
                except Exception as e:
                    print(f"[Supervisor] Comparison context enhancement failed: {e}")

            return SupervisorResult(
                success=True,
                intent=Intent.COMPARISON,
                response=base_response,
                classification=classification
            )
        except Exception as e:
            return SupervisorResult(
                success=False,
                intent=Intent.COMPARISON,
                response=f"对比分析出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_search(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Fallback search with context awareness"""
        try:
            search_result = self.tools_module.search(query)

            # Use LLM to synthesize search results with context
            from langchain_core.messages import HumanMessage

            context_section = ""
            if context_summary:
                context_section = f"""
【对话上下文】
{context_summary}

请结合上下文中的话题回答问题。"""

            prompt = f"""用户问题: {query}

搜索结果:
{search_result}
{context_section}

请基于搜索结果给出简洁的回答（2-4句话），使用中文回复。"""

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])

            return SupervisorResult(
                success=True,
                intent=Intent.SEARCH,
                response=response.content if hasattr(response, 'content') else str(response),
                classification=classification
            )
        except Exception as e:
            return SupervisorResult(
                success=False,
                intent=Intent.SEARCH,
                response=f"搜索出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    def _extract_context_info(self, conversation_context: List[Dict]) -> tuple:
        """
        从对话历史中提取上下文信息
        如果发现链接，会尝试抓取并总结内容

        Returns:
            (context_summary, context_ticker): 上下文摘要和当前关注的股票
        """
        import re

        if not conversation_context:
            return None, None

        # 提取最近对话中的股票代码
        ticker_pattern = r'\b([A-Z]{1,5})\b'
        url_pattern = r'https?://[^\s\)\]<>\"\']+'
        found_tickers = []
        found_urls = []

        # 构建上下文摘要
        context_parts = []
        for msg in conversation_context[-4:]:  # 最近 4 条消息
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not content:
                continue

            # 提取股票代码
            matches = re.findall(ticker_pattern, content)
            # 过滤常见非股票词
            stopwords = {'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS', 'PE', 'EPS', 'GDP', 'CPI', 'API', 'OK', 'CNN', 'HTTP', 'HTTPS', 'WWW', 'COM', 'ORG', 'NET'}
            for m in matches:
                if m not in stopwords and len(m) >= 2:
                    found_tickers.append(m)

            # 提取 URL
            urls = re.findall(url_pattern, content)
            found_urls.extend(urls)

            # 截断长内容
            preview = content[:150] + "..." if len(content) > 150 else content
            context_parts.append(f"{role}: {preview}")

        # 如果有 URL，尝试抓取并总结（最多 2 个）
        url_summaries = []
        if found_urls and self.tools_module:
            for url in found_urls[:2]:  # 最多处理 2 个链接
                try:
                    summary = self._fetch_and_summarize_url(url)
                    if summary:
                        url_summaries.append(f"[链接内容摘要] {summary}")
                except Exception as e:
                    print(f"[Supervisor] URL fetch failed: {url}, error: {e}")

        # 合并上下文
        if url_summaries:
            context_parts.extend(url_summaries)

        context_summary = "\n".join(context_parts) if context_parts else None
        context_ticker = found_tickers[-1] if found_tickers else None  # 取最近提到的

        return context_summary, context_ticker

    def _fetch_and_summarize_url(self, url: str) -> str:
        """
        抓取 URL 内容并生成摘要
        """
        try:
            # 使用 tools_module 中的搜索功能来获取内容
            search_func = getattr(self.tools_module, 'fetch_url_content', None)
            if search_func:
                content = search_func(url)
                if content and len(content) > 100:
                    # 使用 LLM 生成摘要
                    from langchain_core.messages import HumanMessage
                    prompt = f"请用2-3句话总结以下内容的要点：\n\n{content[:2000]}"
                    response = self.llm.invoke([HumanMessage(content=prompt)])
                    return response.content[:300] if hasattr(response, 'content') else str(response)[:300]

            # 如果没有专门的 fetch 函数，尝试用搜索
            search = getattr(self.tools_module, 'search', None)
            if search:
                result = search(f"site:{url}")
                if result:
                    return str(result)[:300]
        except Exception as e:
            print(f"[Supervisor] URL summarize failed: {e}")

        return None

    async def process_stream(self, query: str, tickers: List[str] = None, user_profile: Any = None, conversation_context: List[Dict] = None):
        """
        Streaming process - real-time progress reporting
        格式与前端 sendMessageStream 期望的格式兼容
        支持多轮对话上下文

        Args:
            query: 用户查询
            tickers: 检测到的股票代码
            user_profile: 用户配置
            conversation_context: 对话历史 [{"role": "user/assistant", "content": "..."}]

        Yields:
            JSON formatted events (type: thinking/token/done/error)
        """
        import json
        from datetime import datetime

        thinking_steps = []  # 收集思考步骤

        try:
            # 0. 如果有对话上下文，尝试从中提取相关信息
            context_summary = None
            context_ticker = None
            if conversation_context:
                context_summary, context_ticker = self._extract_context_info(conversation_context)
                if context_ticker and not tickers:
                    tickers = [context_ticker]

            # 1. 发送意图分类开始事件
            step1 = {
                "stage": "classifying",
                "message": "正在分析问题意图...",
                "timestamp": datetime.now().isoformat()
            }
            thinking_steps.append(step1)
            yield json.dumps({"type": "thinking", **step1}, ensure_ascii=False)

            classification = self.classifier.classify(query, tickers, context_summary=context_summary)

            # 2. 发送意图分类完成事件
            step2 = {
                "stage": "classified",
                "message": f"意图: {classification.intent.value}",
                "result": {
                    "intent": classification.intent.value,
                    "method": classification.method,
                    "confidence": classification.confidence,
                    "reasoning": classification.reasoning
                },
                "timestamp": datetime.now().isoformat()
            }
            thinking_steps.append(step2)
            yield json.dumps({"type": "thinking", **step2}, ensure_ascii=False)

            # 3. 执行对应处理器
            step3 = {
                "stage": "processing",
                "message": "正在处理请求...",
                "timestamp": datetime.now().isoformat()
            }
            thinking_steps.append(step3)
            yield json.dumps({"type": "thinking", **step3}, ensure_ascii=False)

            # 传递上下文信息给 process 方法
            result = await self.process(query, tickers, user_profile, context_summary=context_summary, context_ticker=context_ticker)

            # 4. 发送响应内容（作为 token 流式输出）
            if result.response:
                response_text = result.response
                chunk_size = 20  # 每次发送的字符数
                for i in range(0, len(response_text), chunk_size):
                    chunk = response_text[i:i + chunk_size]
                    yield json.dumps({
                        "type": "token",
                        "content": chunk
                    }, ensure_ascii=False)

            # 5. 发送完成事件
            first_ticker = None
            if classification.tickers:
                if isinstance(classification.tickers, list) and len(classification.tickers) > 0:
                    first_ticker = classification.tickers[0]
                elif isinstance(classification.tickers, dict):
                    first_ticker = list(classification.tickers.values())[0] if classification.tickers else None

            # 添加完成步骤
            step_done = {
                "stage": "complete",
                "message": "处理完成",
                "timestamp": datetime.now().isoformat()
            }
            thinking_steps.append(step_done)

            # 构建 report 数据（如果是 REPORT 意图且有 forum_output）
            report_data = None
            if result.intent == Intent.REPORT and result.forum_output:
                # 从 forum_output 构建 ReportIR 格式
                report_data = self._build_report_ir(result, first_ticker, classification)

            yield json.dumps({
                "type": "done",
                "success": result.success,
                "intent": result.intent.value,
                "current_focus": first_ticker,
                "thinking": thinking_steps,  # 前端期望在 done 事件中收到 thinking 数组
                "errors": result.errors,
                "report": report_data  # Phase 2: 深度研报数据
            }, ensure_ascii=False)

        except Exception as e:
            # 捕获异常，发送 error 事件，确保前端能收到错误信息
            import traceback
            traceback.print_exc()
            yield json.dumps({
                "type": "error",
                "message": f"处理请求时出错: {str(e)}"
            }, ensure_ascii=False)

    def _build_report_ir(self, result: SupervisorResult, ticker: str, classification: ClassificationResult) -> dict:
        """
        将 Supervisor 结果转换为 ReportIR 格式（前端卡片展示）

        重要：优先使用 Forum 的完整 8 节分析作为主要内容

        Args:
            result: SupervisorResult
            ticker: 股票代码
            classification: 意图分类结果

        Returns:
            dict: ReportIR 格式的报告数据
        """
        from datetime import datetime
        import uuid
        import re

        def safe_str(value):
            """安全转换为字符串，处理 Timestamp 等特殊类型"""
            if value is None:
                return None
            if isinstance(value, str):
                return value
            # 处理 pandas Timestamp 或其他时间类型
            if hasattr(value, 'isoformat'):
                return value.isoformat()
            if hasattr(value, 'strftime'):
                return value.strftime('%Y-%m-%d %H:%M:%S')
            return str(value)

        forum_output = result.forum_output
        agent_outputs = result.agent_outputs or {}
        errors_list = result.errors or []

        # 构建 sections - 优先从 Forum 完整分析解析
        sections = []
        section_order = 1

        # 尝试解析 Forum 的 8 节分析
        forum_sections = self._parse_forum_sections(result.response) if result.response else []

        if forum_sections:
            # 使用 Forum 解析出的章节
            for fs in forum_sections:
                sections.append({
                    "title": fs["title"],
                    "order": section_order,
                    "agent_name": "ForumHost",
                    "confidence": getattr(forum_output, 'confidence', 0.7) if forum_output else 0.7,
                    "data_sources": ["multi-agent-synthesis"],
                    "contents": [{
                        "type": "text",
                        "content": fs["content"]
                    }]
                })
                section_order += 1
        else:
            # Fallback: 从各 Agent 输出构建章节
            agent_sections = {
                "price": {"title": "价格分析", "agent": "PriceAgent"},
                "news": {"title": "新闻分析", "agent": "NewsAgent"},
                "technical": {"title": "技术分析", "agent": "TechnicalAgent"},
                "fundamental": {"title": "基本面分析", "agent": "FundamentalAgent"},
                "macro": {"title": "宏观分析", "agent": "MacroAgent"},
                "deep_search": {"title": "深度搜索", "agent": "DeepSearchAgent"}
            }

            for agent_key, section_info in agent_sections.items():
                section_title = section_info["title"]
                agent_display_name = section_info["agent"]

                # 检查是否有这个 agent 的错误
                agent_error = None
                for err in errors_list:
                    if err.startswith(f"{agent_key}:"):
                        agent_error = err.split(":", 1)[1].strip() if ":" in err else err
                        break

                if agent_key in agent_outputs and agent_outputs[agent_key]:
                    agent_output = agent_outputs[agent_key]
                    if hasattr(agent_output, 'summary') and agent_output.summary:
                        confidence = getattr(agent_output, 'confidence', 0.5)
                        data_sources = getattr(agent_output, 'data_sources', [])

                        sections.append({
                            "title": section_title,
                            "order": section_order,
                            "agent_name": agent_display_name,
                            "confidence": confidence,
                            "data_sources": data_sources,
                            "contents": [{
                                "type": "text",
                                "content": safe_str(agent_output.summary)
                            }]
                        })
                        section_order += 1
                elif agent_error:
                    sections.append({
                        "title": section_title,
                        "order": section_order,
                        "agent_name": agent_display_name,
                        "confidence": 0,
                        "error": True,
                        "contents": [{
                            "type": "text",
                            "content": f"⚠️ {agent_display_name} 数据获取失败: {agent_error}"
                        }]
                    })
                    section_order += 1

        # 构建 agent 状态追踪
        agent_status = {}
        for agent_key in ["price", "news", "technical", "fundamental", "macro", "deep_search"]:
            if agent_key in agent_outputs and agent_outputs[agent_key]:
                agent_output = agent_outputs[agent_key]
                confidence = getattr(agent_output, 'confidence', 0.5)
                agent_status[agent_key] = {"status": "success", "confidence": confidence}
            else:
                # 检查是否有错误
                agent_error = None
                for err in errors_list:
                    if err.startswith(f"{agent_key}:"):
                        agent_error = err.split(":", 1)[1].strip() if ":" in err else err
                        break
                if agent_error:
                    agent_status[agent_key] = {"status": "error", "error": agent_error}

        # 构建 citations
        citations = []
        citation_id = 1
        for agent_name, agent_output in agent_outputs.items():
            if hasattr(agent_output, 'evidence') and agent_output.evidence:
                for evidence in agent_output.evidence[:3]:
                    title = getattr(evidence, 'title', None) or getattr(evidence, 'source', f"{agent_name} 来源")
                    url = getattr(evidence, 'url', '') or "#"
                    text = getattr(evidence, 'text', '')
                    timestamp = getattr(evidence, 'timestamp', None)

                    citations.append({
                        "source_id": f"src_{citation_id}",
                        "title": safe_str(title),
                        "url": safe_str(url),
                        "snippet": safe_str(text)[:200] if text else "",
                        "published_date": safe_str(timestamp)
                    })
                    citation_id += 1

        # 确定情绪
        sentiment = "neutral"
        if forum_output:
            rec = getattr(forum_output, 'recommendation', 'HOLD')
            if rec == "BUY":
                sentiment = "bullish"
            elif rec == "SELL":
                sentiment = "bearish"

        # 获取风险列表
        risks = ["市场波动风险", "数据延迟风险"]
        if forum_output and hasattr(forum_output, 'risks') and forum_output.risks:
            risks = [safe_str(r) for r in forum_output.risks]

        # 生成摘要 - 从 Forum 分析中提取执行摘要
        summary = "报告生成完成"
        if result.response:
            # 尝试提取执行摘要部分
            exec_summary = self._extract_executive_summary(result.response)
            if exec_summary:
                summary = exec_summary
            else:
                summary = safe_str(result.response)[:500]

        # 构建 ReportIR
        report_ir = {
            "report_id": f"report_{uuid.uuid4().hex[:8]}",
            "ticker": safe_str(ticker) or "UNKNOWN",
            "company_name": safe_str(ticker) or "未知公司",
            "title": f"{ticker} 深度分析报告" if ticker else "深度分析报告",
            "summary": summary,
            "sentiment": sentiment,
            "confidence_score": float(getattr(forum_output, 'confidence', 0.7)) if forum_output else 0.7,
            "generated_at": datetime.now().isoformat(),
            "sections": sections,
            "citations": citations,
            "risks": risks,
            "recommendation": safe_str(getattr(forum_output, 'recommendation', 'HOLD')) if forum_output else "HOLD",
            "agent_status": agent_status,
            "errors": errors_list if errors_list else None
        }

        return report_ir

    def _parse_forum_sections(self, forum_text: str) -> list:
        """
        解析 Forum 的 8 节分析文本为结构化章节

        Args:
            forum_text: Forum 生成的完整分析文本

        Returns:
            list: 章节列表 [{"title": "...", "content": "..."}]
        """
        import re

        if not forum_text:
            return []

        sections = []

        # 匹配标题模式: ### 1. 📊 执行摘要 或 ### 1. 执行摘要
        section_pattern = r'###\s*(\d+)\.\s*([^\n]+)\n([\s\S]*?)(?=###\s*\d+\.|$)'
        matches = re.findall(section_pattern, forum_text)

        for match in matches:
            order, title, content = match
            # 清理标题中的 emoji 和多余空格
            clean_title = re.sub(r'[📊📈💰🌍⚠️🎯📐📅]\s*', '', title).strip()
            # 清理内容
            clean_content = content.strip()

            if clean_title and clean_content:
                sections.append({
                    "title": clean_title,
                    "content": clean_content
                })

        return sections

    def _extract_executive_summary(self, forum_text: str) -> str:
        """
        从 Forum 分析中提取执行摘要

        Args:
            forum_text: Forum 生成的完整分析文本

        Returns:
            str: 执行摘要文本（最多 500 字符）
        """
        import re

        if not forum_text:
            return ""

        # 尝试匹配执行摘要部分
        patterns = [
            r'###\s*1\.\s*[📊]?\s*执行摘要[^\n]*\n([\s\S]*?)(?=###\s*2\.|$)',
            r'###\s*1\.\s*[📊]?\s*EXECUTIVE SUMMARY[^\n]*\n([\s\S]*?)(?=###\s*2\.|$)',
            r'\*\*投资评级\*\*[：:]\s*([^\n]+)',
            r'\*\*核心观点\*\*[：:]\s*([^\n]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, forum_text, re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                # 截取前 500 字符
                return content[:500] if len(content) > 500 else content

        # 如果没找到特定格式，返回前 500 字符
        return forum_text[:500]
