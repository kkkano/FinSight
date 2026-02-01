# -*- coding: utf-8 -*-
"""
SupervisorAgent - Supervisor Pattern
Mature multi-Agent architecture: AgentIntent Classification → Supervisor Coordination → Worker Agents → Forum Synthesis
"""

import logging
import asyncio
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass

from backend.orchestration.intent_classifier import IntentClassifier, AgentIntent, ClassificationResult
from backend.orchestration.budget import BudgetManager, BudgetedTools, BudgetExceededError
from backend.orchestration.forum import ForumHost
from backend.orchestration.trace_emitter import get_trace_emitter
from backend.agents.base_agent import AgentOutput

logger = logging.getLogger(__name__)


@dataclass
class SupervisorResult:
    """Supervisor execution result"""
    success: bool
    intent: AgentIntent
    response: str
    agent_outputs: Dict[str, Any] = None
    forum_output: Any = None
    classification: ClassificationResult = None
    errors: List[str] = None
    budget: Optional[Dict[str, Any]] = None


# Greeting response templates (Chinese output for users)
GREETING_RESPONSES = {
    "default": "您好！我是 FinSight AI 金融助手，可帮您查询股票价格、分析新闻、生成投资报告等。",
    "help": "我可以帮您：\n• 查询股票实时价格（如：AAPL 价格）\n• 获取公司新闻（如：特斯拉新闻）\n• 分析市场情绪\n• 生成深度分析报告（如：详细分析 AAPL）\n• 对比多个股票（如：对比 AAPL 和 MSFT）",
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
        # Keep a reference to the original tools module so we can re-wrap
        # with a fresh budget on every request.
        if isinstance(tools_module, BudgetedTools):
            self._raw_tools_module = tools_module._tools
        else:
            self._raw_tools_module = tools_module

        # 防护：确保 cache 和 circuit_breaker 不为 None
        if cache is None:
            from backend.orchestration.cache import DataCache
            cache = DataCache()
        self.cache = cache

        if circuit_breaker is None:
            from backend.services.circuit_breaker import CircuitBreaker
            circuit_breaker = CircuitBreaker()
        self.circuit_breaker = circuit_breaker

        # AgentIntent classifier
        self.classifier = IntentClassifier(llm)

        # Forum host
        self.forum = ForumHost(llm)

        # Budget per request (set during process/process_stream)
        self._budget: Optional[BudgetManager] = None

        # Worker Agents (lazy initialization)
        self._agents = None

    @staticmethod
    def _is_news_analysis_requested(query: str, context_summary: str = None) -> bool:
        """True when the user is asking for analysis/impact instead of a plain news list."""
        text = f"{context_summary or ''}\n{query or ''}".lower()
        keywords = [
            # 中文
            "分析", "影响", "解读", "评估", "怎么看", "意味着", "利好", "利空", "风险", "机会", "展望",
            # 英文
            "analyze", "analysis", "impact", "effect", "implication", "assess", "outlook", "forecast",
        ]
        return any(k in text for k in keywords)

    @staticmethod
    def _news_analysis_failure_response(reason: str, ticker: Optional[str], has_selection: bool) -> str:
        t = ticker or "该标的"
        sel_hint = "已检测到你引用了具体新闻。" if has_selection else ""
        return (
            "### ⚠️ 无法完成新闻影响分析\n"
            f"- **原因**: {reason}\n"
            f"- **上下文**: {sel_hint}\n"
            "\n"
            "### ✅ 下一步建议\n"
            f"1. 直接说清分析目标：`分析 {t} 这条新闻对短期股价和中长期基本面的影响`\n"
            "2. 如果是引用新闻：请在 Dashboard 点击“问这条”，确保带上 Selection Context\n"
            "3. 或粘贴新闻链接/正文关键段落（避免只发 ticker）\n"
            "4. 如果问题仍复现：把开发者控制台里的 `llm_start/llm_end` 事件发我，我可以继续定位\n"
        )

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

    def _set_budget(self, budget: Optional[BudgetManager]) -> None:
        self._budget = budget

    def _consume_round(self, label: str) -> None:
        if not self._budget:
            return
        self._budget.consume_round(label)

    def _select_agents_for_query(self, query: str) -> List[str]:
        """Select relevant agents based on query signals."""
        query_lower = query.lower()
        selected: List[str] = []

        if any(kw in query_lower for kw in ["新闻", "快讯", "消息", "news", "headline", "舆情"]):
            selected.append("news")
        if any(kw in query_lower for kw in ["技术", "走势", "形态", "macd", "rsi", "kdj", "technical", "indicator"]):
            selected.append("technical")
        if any(kw in query_lower for kw in ["财报", "营收", "利润", "估值", "市盈率", "pe", "eps", "roe", "fundamental", "valuation"]):
            selected.append("fundamental")
        if any(kw in query_lower for kw in ["宏观", "cpi", "gdp", "利率", "通胀", "macro", "fomc"]):
            selected.append("macro")
        if any(kw in query_lower for kw in ["价格", "股价", "行情", "price", "quote", "表现"]):
            selected.append("price")

        if not selected:
            selected = ["price", "fundamental", "technical", "news"]

        # Ensure unique order preservation
        seen = set()
        ordered = []
        for name in selected:
            if name not in seen:
                ordered.append(name)
                seen.add(name)
        return ordered

    def _collect_evidence_pool(self, agent_outputs: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pool: List[Dict[str, Any]] = []
        if not isinstance(agent_outputs, dict):
            return pool
        seen = set()
        for agent_name, output in agent_outputs.items():
            if isinstance(output, dict):
                evidence_list = output.get("evidence") or []
            else:
                evidence_list = getattr(output, "evidence", []) or []
            for ev in evidence_list:
                if isinstance(ev, dict):
                    title = ev.get("title") or ev.get("headline") or ev.get("source") or agent_name
                    snippet = ev.get("snippet") or ev.get("text") or ev.get("content") or ""
                    url = ev.get("url") or ""
                    source = ev.get("source") or agent_name
                    timestamp = ev.get("timestamp") or ev.get("published_at") or ev.get("datetime")
                    confidence = ev.get("confidence")
                else:
                    title = getattr(ev, "title", None) or getattr(ev, "source", None) or agent_name
                    snippet = getattr(ev, "text", None) or ""
                    url = getattr(ev, "url", "") or ""
                    source = getattr(ev, "source", None) or agent_name
                    timestamp = getattr(ev, "timestamp", None)
                    confidence = getattr(ev, "confidence", None)
                if isinstance(snippet, str):
                    snippet = snippet.strip()
                else:
                    snippet = str(snippet)
                if snippet and len(snippet) > 240:
                    snippet = snippet[:240] + "..."
                key = f"{url}|{title}|{snippet[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                pool.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": source,
                    "published_date": timestamp,
                    "confidence": confidence,
                    "agent": agent_name,
                })
        return pool

    def _result(self, *args, **kwargs) -> SupervisorResult:
        result = SupervisorResult(*args, **kwargs)
        if self._budget:
            result.budget = self._budget.snapshot()
        return result

    async def process(self, query: str, tickers: List[str] = None, user_profile: Any = None, context_summary: str = None, context_ticker: str = None, on_event: Callable = None) -> SupervisorResult:
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

        budget = BudgetManager.from_env()
        self._set_budget(budget)
        # Always refresh BudgetedTools per request so budgets don't leak across calls.
        if self._raw_tools_module:
            self.tools_module = BudgetedTools(self._raw_tools_module, budget)
        self._agents = None

        # 1. AgentIntent classification (带上下文)
        classification = self.classifier.classify(query, tickers, context_summary=context_summary)
        logger.info(f"[Supervisor] AgentIntent: {classification.intent.value} (method: {classification.method}, confidence: {classification.confidence})")

        # ── Selection Context 强制意图（优先级最高）────────────────────
        # Dashboard 里用户明确选择了新闻/报告，则按选择类型直接路由，避免误判。
        if context_summary and "[System Context]" in context_summary:
            if ("用户正在询问以下新闻" in context_summary) or ("引用新闻" in context_summary):
                classification.intent = AgentIntent.NEWS
                classification.method = f"{classification.method}+selection_override"
                classification.reasoning = (classification.reasoning or "") + " | selection_context=news"
            elif ("用户正在询问以下报告" in context_summary) or ("引用报告" in context_summary):
                classification.intent = AgentIntent.REPORT
                classification.method = f"{classification.method}+selection_override"
                classification.reasoning = (classification.reasoning or "") + " | selection_context=report"

        # 2. Route based on intent
        intent = classification.intent

        # Simple intents - rule-based direct handling (cost-free)
        if intent == AgentIntent.GREETING:
            return self._handle_greeting(query, classification)

        if intent == AgentIntent.OFF_TOPIC:
            return self._result(
                success=True,
                intent=intent,
                response="抱歉，我是金融助手，只能回答金融相关的问题。",
                classification=classification
            )
        if intent == AgentIntent.CLARIFY:
            tickers_list = classification.tickers if isinstance(classification.tickers, list) else list(classification.tickers) if classification.tickers else []
            ticker = tickers_list[0] if tickers_list else None
            logger.info("[Supervisor] Clarify intent downgraded to SEARCH; SchemaRouter handles clarifications.")
            return await self._handle_search(query, ticker, classification, context_summary)

        # Intents requiring Agent calls
        tickers_list = classification.tickers if isinstance(classification.tickers, list) else list(classification.tickers) if classification.tickers else []
        ticker = tickers_list[0] if tickers_list else None

        # Lightweight intents - single tool/agent
        # 所有 handler 都传递 context_summary，让它们可以根据上下文优化响应
        if intent == AgentIntent.PRICE:
            return await self._handle_price(query, ticker, classification, context_summary)

        # NEWS 意图：子意图分类 - 区分"查询新闻"和"分析新闻"
        if intent == AgentIntent.NEWS:
            news_subintent = self._classify_news_subintent(query, context_summary)
            if news_subintent == "analyze":
                # 分析类请求：走 NewsAgent + Forum 深度分析
                return await self._handle_news_analysis(query, ticker, classification, context_summary)
            else:
                # 查询类请求：返回原始新闻列表（带链接）
                return await self._handle_news(query, ticker, classification, context_summary)

        if intent == AgentIntent.SENTIMENT:
            return await self._handle_sentiment(query, ticker, classification, context_summary)

        if intent == AgentIntent.TECHNICAL:
            return await self._handle_single_agent("technical", query, ticker, classification, context_summary)

        if intent == AgentIntent.FUNDAMENTAL:
            return await self._handle_single_agent("fundamental", query, ticker, classification, context_summary)

        if intent == AgentIntent.MACRO:
            return await self._handle_single_agent("macro", query, ticker, classification, context_summary)

        # Complex intents - multi-Agent collaboration
        if intent == AgentIntent.REPORT:
            return await self._handle_report(query, ticker, user_profile, classification, context_summary, on_event=on_event)

        if intent == AgentIntent.COMPARISON:
            return await self._handle_comparison(query, tickers_list, classification, context_summary)

        # Fallback - search
        return await self._handle_search(query, ticker, classification, context_summary)

    def _handle_greeting(self, query: str, classification: ClassificationResult) -> SupervisorResult:
        """Handle greeting - rule-based direct response, free"""
        query_lower = query.lower()
        if any(kw in query_lower for kw in ["help", "support", "what can you do", "who are you", "帮助", "你是谁", "你能做什么"]):
            response = GREETING_RESPONSES["help"]
        else:
            response = GREETING_RESPONSES["default"]

        return self._result(
            success=True,
            intent=AgentIntent.GREETING,
            response=response,
            classification=classification
        )

    async def _handle_price(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle price query - lightweight tool, with context awareness"""
        if not ticker:
            return await self._handle_search(query, None, classification, context_summary)

        trace_emitter = get_trace_emitter()

        try:
            self._consume_round("tool:price")
            # 发射工具调用开始事件
            trace_emitter.emit_tool_start("get_stock_price", {"ticker": ticker})
            tool_start_time = time.perf_counter()

            # Direct tool call, no Agent
            price_data = self.tools_module.get_stock_price(ticker)

            # 发射工具调用结束事件
            tool_duration_ms = int((time.perf_counter() - tool_start_time) * 1000)
            trace_emitter.emit_tool_end(
                "get_stock_price",
                success=not (isinstance(price_data, dict) and price_data.get("error")),
                duration_ms=tool_duration_ms,
                result_preview=str(price_data)[:100] if price_data else None
            )

            if isinstance(price_data, dict) and price_data.get("error"):
                return self._result(
                    success=False,
                    intent=AgentIntent.PRICE,
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
                    prompt = f"""<role>金融数据分析师</role>
<task>结合上下文解读股票价格</task>

<data>
价格: {base_response}
上下文: {context_summary}
问题: {query}
</data>

<rules>
- 禁止开场白（不要说"好的"、"当然"、"我来"等）
- 直接输出分析内容
- 1-2句话，简洁专业
- 上下文无关时仅返回价格数据
</rules>"""
                    # 发射 LLM 调用开始事件
                    llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
                    trace_emitter.emit_llm_start(model=llm_model, prompt_preview=prompt[:150])
                    llm_start_time = time.perf_counter()

                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])

                    # 发射 LLM 调用结束事件
                    llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    trace_emitter.emit_llm_end(
                        model=llm_model,
                        duration_ms=llm_duration_ms,
                        success=True,
                        output_preview=response_text[:100] if response_text else None
                    )

                    return self._result(
                        success=True,
                        intent=AgentIntent.PRICE,
                        response=response_text,
                        classification=classification
                    )
                except Exception as e:
                    logger.info(f"[Supervisor] Price context enhancement failed: {e}")

            return self._result(
                success=True,
                intent=AgentIntent.PRICE,
                response=base_response,
                classification=classification
            )
        except BudgetExceededError as e:
            return self._result(
                success=False,
                intent=AgentIntent.PRICE,
                response=f"budget exceeded: {e}",
                classification=classification,
                errors=[str(e)]
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=AgentIntent.PRICE,
                response=f"获取价格时出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    def _classify_news_subintent(self, query: str, context_summary: str = None) -> str:
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
        query_lower = (query or "").lower()

        # 如果存在 Selection Context（用户引用具体新闻），且上下文/问题带有分析意图，优先走 analyze
        if context_summary and "[System Context]" in context_summary:
            if ("用户正在询问以下新闻" in context_summary) or ("引用新闻" in context_summary):
                ctx_lower = context_summary.lower()
                if any(k in ctx_lower for k in ["分析", "影响", "解读", "评估", "怎么看", "analyze", "impact", "assess"]):
                    return "analyze"

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
        trace_emitter = get_trace_emitter()

        try:
            # ── Selection Context 优先处理 ──────────────────────────────
            # 如果用户选中了特定新闻，统一走 _handle_news_analysis（保证分析链路只有一套实现与输出结构）
            if context_summary and "[System Context]" in context_summary:
                if "用户正在询问以下新闻" in context_summary or "引用新闻" in context_summary:
                    logger.info("[Supervisor] Selection Context detected in _handle_news - delegating to _handle_news_analysis")
                    return await self._handle_news_analysis(query, ticker, classification, context_summary)

            # Prefer NewsAgent for reliability when ticker is available
            if ticker:
                news_agent = self.agents.get("news")
                if news_agent:
                    try:
                        self._consume_round("agent:news")
                        # 发射 Agent 开始事件
                        trace_emitter.emit_agent_start("NewsAgent", query=query, ticker=ticker)
                        agent_start_time = time.perf_counter()

                        output = await news_agent.research(query, ticker)

                        # 发射 Agent 完成事件
                        agent_duration_ms = int((time.perf_counter() - agent_start_time) * 1000)
                        trace_emitter.emit_agent_done(
                            "NewsAgent",
                            duration_ms=agent_duration_ms,
                            success=bool(output and output.summary)
                        )

                        if output and output.summary:
                            summary_text = output.summary
                            summary_lower = summary_text.lower()
                            missing_ticker = ticker and ticker.upper() not in summary_text.upper()
                            missing_news_word = ("??" not in summary_text) and ("news" not in summary_lower)
                            if missing_ticker or missing_news_word:
                                logger.info("[Supervisor] NewsAgent summary missing expected keywords, fallback to raw news list")
                            else:
                                return self._result(
                                    success=True,
                                    intent=AgentIntent.NEWS,
                                    response=summary_text,
                                    agent_outputs={"news": output},
                                    classification=classification
                                )
                    except Exception as e:
                        logger.info(f"[Supervisor] NewsAgent failed: {e}")

            self._consume_round("tool:news")
            # 发射工具调用开始事件
            tool_name = "get_company_news" if ticker else "search"
            trace_emitter.emit_tool_start(tool_name, {"ticker": ticker} if ticker else {"query": query})
            tool_start_time = time.perf_counter()

            if ticker:
                news_data = self.tools_module.get_company_news(ticker)
            else:
                news_data = self.tools_module.search(query)

            # 发射工具调用结束事件
            tool_duration_ms = int((time.perf_counter() - tool_start_time) * 1000)
            trace_emitter.emit_tool_end(
                tool_name,
                success=not (isinstance(news_data, dict) and news_data.get("error")),
                duration_ms=tool_duration_ms,
                result_preview=str(news_data)[:100] if news_data else None
            )

            if isinstance(news_data, dict) and news_data.get("error"):
                return self._result(
                    success=True,
                    intent=AgentIntent.NEWS,
                    response=f"获取新闻失败：{news_data.get('error')}",
                    classification=classification
                )

            # 格式化原始新闻数据
            if isinstance(news_data, list):
                formatter = getattr(self.tools_module, "format_news_items", None) if self.tools_module else None
                if formatter:
                    title = f"{ticker} \u65b0\u95fb" if ticker else "\u6700\u65b0\u65b0\u95fb"
                    base_response = formatter(news_data, title=title)
                else:
                    base_response = "\n".join(
                        f"- {(item.get('headline') or item.get('title') or 'No title')}"
                        for item in news_data
                        if isinstance(item, dict)
                    )
            else:
                base_response = str(news_data) if news_data else "暂无相关新闻"

            if isinstance(base_response, str) and ("Connection error" in base_response or "Search error" in base_response):
                base_response = "新闻源连接失败，请稍后重试。"

            # 如果有上下文，在原始新闻后补充简短分析
            if context_summary and news_data:
                try:
                    from langchain_core.messages import HumanMessage
                    prompt = f"""<role>金融新闻分析师</role>
<task>分析新闻与对话上下文的关联性</task>

<news>{base_response[:1500]}</news>
<context>{context_summary}</context>

<output_format>
💡 **上下文关联**: [1-2句关联分析]
</output_format>

<rules>
- 禁止开场白，直接输出格式内容
- 不重复新闻内容
- 仅分析关联性
</rules>"""
                    # 发射 LLM 调用开始事件
                    llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
                    trace_emitter.emit_llm_start(model=llm_model, prompt_preview=prompt[:150])
                    llm_start_time = time.perf_counter()

                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])

                    # 发射 LLM 调用结束事件
                    llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
                    context_analysis = response.content if hasattr(response, 'content') else str(response)
                    trace_emitter.emit_llm_end(
                        model=llm_model,
                        duration_ms=llm_duration_ms,
                        success=True,
                        output_preview=context_analysis[:100] if context_analysis else None
                    )

                    # 先显示新闻，再显示上下文分析
                    base_response = f"{base_response}\n\n{context_analysis}"
                except Exception as e:
                    logger.info(f"[Supervisor] News context enhancement failed: {e}")
                    if self._is_news_analysis_requested(query, context_summary):
                        return self._result(
                            success=False,
                            intent=AgentIntent.NEWS,
                            response=self._news_analysis_failure_response(
                                reason=str(e),
                                ticker=ticker,
                                has_selection=(
                                    bool(context_summary)
                                    and "[System Context]" in context_summary
                                    and ("用户正在询问以下新闻" in context_summary or "引用新闻" in context_summary)
                                ),
                            ),
                            classification=classification,
                            errors=[str(e)],
                        )

            return self._result(
                success=True,
                intent=AgentIntent.NEWS,
                response=base_response,
                classification=classification
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=AgentIntent.NEWS,
                response="新闻源连接失败，请稍后重试。",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_general_news(self, query: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """
        Handle general news query without ticker (e.g., "今天有什么财经新闻")
        使用通用搜索获取新闻，并结合上下文分析
        """
        return await self._handle_news(query, None, classification, context_summary)

    async def _handle_news_analysis(self, query: str, ticker: Optional[str], classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
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
        trace_emitter = get_trace_emitter()

        try:
            self._consume_round("tool:news_analysis")
            from langchain_core.messages import HumanMessage

            # ── Selection Context 优先处理 ──────────────────────────────
            # 如果用户选中了特定新闻，直接深度分析该新闻，不去获取新闻列表
            if context_summary and "[System Context]" in context_summary:
                if "用户正在询问以下新闻" in context_summary or "引用新闻" in context_summary:
                    logger.info("[Supervisor] Selection Context detected in news_analysis - analyzing selected news directly")
                    try:
                        analysis_prompt = f"""<role>资深金融新闻分析师</role>
<task>深度分析用户引用的新闻及其市场影响</task>

{context_summary}

<user_query>{query}</user_query>

<output_structure>
### 📰 新闻摘要
[2-3句核心事件总结]

### 📊 市场影响
- **短期**: [即时影响预判]
- **中长期**: [持续性影响]

### 🎯 投资启示
- [对投资者的意义]
- [后续关注点]

### ⚠️ 风险提示
- [隐含风险因素]
- [不确定性警示]
</output_structure>

<rules>
- 禁止开场白（不要说"好的"、"我来分析"等）
- 直接按结构输出分析
- 基于新闻内容进行专业深度分析
- 结合{ticker or '相关标的'}的基本面给出见解
- 观点具体，避免空泛表述
- 保持客观中立，不构成投资建议
</rules>"""

                        # 发射 LLM 调用开始事件
                        llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
                        trace_emitter.emit_llm_start(model=llm_model, prompt_preview=analysis_prompt[:150])
                        llm_start_time = time.perf_counter()

                        response = await self.llm.ainvoke([HumanMessage(content=analysis_prompt)])

                        # 发射 LLM 调用结束事件
                        llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
                        analysis_result = response.content if hasattr(response, 'content') else str(response)
                        trace_emitter.emit_llm_end(
                            model=llm_model,
                            duration_ms=llm_duration_ms,
                            success=True,
                            output_preview=analysis_result[:100] if analysis_result else None
                        )

                        return self._result(
                            success=True,
                            intent=AgentIntent.NEWS,
                            response=analysis_result,
                            classification=classification
                        )
                    except Exception as e:
                        logger.error(f"[Supervisor] Selection context news analysis (deep) failed: {e}")
                        # 降级到普通新闻分析流程

            # 1. 先获取原始新闻数据
            # 发射工具调用开始事件
            tool_name = "get_company_news" if ticker else "search"
            trace_emitter.emit_tool_start(tool_name, {"ticker": ticker} if ticker else {"query": query})
            tool_start_time = time.perf_counter()

            if ticker:
                news_data = self.tools_module.get_company_news(ticker)
            else:
                news_data = self.tools_module.search(query)

            # 发射工具调用结束事件
            tool_duration_ms = int((time.perf_counter() - tool_start_time) * 1000)
            trace_emitter.emit_tool_end(
                tool_name,
                success=not (isinstance(news_data, dict) and news_data.get("error")),
                duration_ms=tool_duration_ms,
                result_preview=str(news_data)[:100] if news_data else None
            )

            if isinstance(news_data, dict) and news_data.get("error"):
                return self._result(
                    success=True,
                    intent=AgentIntent.NEWS,
                    response=f"获取新闻失败：{news_data.get('error')}",
                    classification=classification
                )

            news_text = str(news_data) if news_data else ""

            if not news_text or news_text == "暂无相关新闻":
                return self._result(
                    success=True,
                    intent=AgentIntent.NEWS,
                    response="暂无相关新闻可供分析",
                    classification=classification
                )

            # 2. 使用 LLM 进行深度新闻分析
            analysis_prompt = f"""<role>资深金融新闻分析师</role>
<task>深度分析新闻影响</task>

<news>{news_text[:3000]}</news>
<query>{query}</query>
{f"<context>{context_summary}</context>" if context_summary else ""}

<output_structure>
### 📰 新闻摘要
[2-3句核心事件总结]

### 📊 市场影响
- **短期**: [即时影响预判]
- **中长期**: [持续性影响]

### 🎯 投资启示
- [对投资者的意义]
- [后续关注点]

### ⚠️ 风险提示
- [隐含风险因素]
- [不确定性警示]
</output_structure>

<rules>
- 禁止开场白（不要说"好的"、"我来分析"等）
- 直接按结构输出分析
- 观点具体，避免空泛表述
- 数据支撑，专业客观
</rules>"""

            # 发射 LLM 调用开始事件
            llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
            trace_emitter.emit_llm_start(model=llm_model, prompt_preview=analysis_prompt[:150])
            llm_start_time = time.perf_counter()

            response = await self.llm.ainvoke([HumanMessage(content=analysis_prompt)])

            # 发射 LLM 调用结束事件
            llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
            analysis_content = response.content if hasattr(response, 'content') else str(response)
            trace_emitter.emit_llm_end(
                model=llm_model,
                duration_ms=llm_duration_ms,
                success=True,
                output_preview=analysis_content[:100] if analysis_content else None
            )

            # 3. 组合原始新闻 + 分析结果
            final_response = f"""## 📰 相关新闻

{news_text}

---

## 🔍 深度分析

{analysis_content}"""

            return self._result(
                success=True,
                intent=AgentIntent.NEWS,
                response=final_response,
                classification=classification
            )

        except Exception as e:
            logger.info(f"[Supervisor] News analysis failed: {e}")
            return self._result(
                success=False,
                intent=AgentIntent.NEWS,
                response=self._news_analysis_failure_response(
                    reason=str(e),
                    ticker=ticker,
                    has_selection=(
                        bool(context_summary)
                        and "[System Context]" in context_summary
                        and ("用户正在询问以下新闻" in context_summary or "引用新闻" in context_summary)
                    ),
                ),
                classification=classification,
                errors=[str(e)],
            )

    async def _handle_sentiment(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """
        Handle market sentiment query
        如果有上下文（之前讨论的股票/新闻），结合上下文来分析情绪
        """
        trace_emitter = get_trace_emitter()

        try:
            # 1. 获取基础市场情绪数据
            self._consume_round("tool:sentiment")
            # 发射工具调用开始事件
            trace_emitter.emit_tool_start("get_market_sentiment", {"query": query, "ticker": ticker})
            tool_start_time = time.perf_counter()

            sentiment_data = self.tools_module.get_market_sentiment()

            # 发射工具调用结束事件
            tool_duration_ms = int((time.perf_counter() - tool_start_time) * 1000)
            trace_emitter.emit_tool_end(
                "get_market_sentiment",
                success=sentiment_data is not None,
                duration_ms=tool_duration_ms,
                result_preview=str(sentiment_data)[:100] if sentiment_data else None
            )

            base_sentiment = str(sentiment_data) if sentiment_data else "暂无市场情绪数据"

            # 2. 如果没有上下文，直接返回基础情绪
            if not context_summary and not ticker:
                return self._result(
                    success=True,
                    intent=AgentIntent.SENTIMENT,
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
                        self._consume_round("agent:news")
                        # 发射 Agent 开始事件
                        trace_emitter.emit_agent_start("NewsAgent", query=f"{ticker} news sentiment", ticker=ticker)
                        agent_start_time = time.perf_counter()

                        news_output = await news_agent.research(f"{ticker} news sentiment", ticker)

                        # 发射 Agent 完成事件
                        agent_duration_ms = int((time.perf_counter() - agent_start_time) * 1000)
                        trace_emitter.emit_agent_done(
                            "NewsAgent",
                            duration_ms=agent_duration_ms,
                            success=bool(news_output and news_output.summary)
                        )

                        if news_output and news_output.summary:
                            news_content = f"\n\n【{ticker} 相关新闻】\n{news_output.summary}"
                except Exception as e:
                    logger.info(f"[Supervisor] News fetch for sentiment failed: {e}")

            # 4. 构建 Prompt 让 LLM 综合分析
            prompt = f"""<role>市场情绪分析师</role>
<task>综合分析市场情绪</task>

<sentiment_data>{base_sentiment}</sentiment_data>
{f"<news>{news_content}</news>" if news_content else ""}
<context>{context_summary or '无'}</context>
<query>{query}</query>

<rules>
- 禁止开场白，直接输出分析
- 2-3句话，简洁专业
- 优先分析上下文中提到的股票/行业
- 明确情绪倾向（看涨/看跌/中性）
</rules>"""

            from langchain_core.messages import HumanMessage
            # 发射 LLM 调用开始事件
            llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
            trace_emitter.emit_llm_start(model=llm_model, prompt_preview=prompt[:150])
            llm_start_time = time.perf_counter()

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])

            # 发射 LLM 调用结束事件
            llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
            analysis = response.content if hasattr(response, 'content') else str(response)
            trace_emitter.emit_llm_end(
                model=llm_model,
                duration_ms=llm_duration_ms,
                success=True,
                output_preview=analysis[:100] if analysis else None
            )

            return self._result(
                success=True,
                intent=AgentIntent.SENTIMENT,
                response=analysis,
                classification=classification
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=AgentIntent.SENTIMENT,
                response=f"获取市场情绪时出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_single_agent(self, agent_name: str, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle single Agent query with context awareness"""
        trace_emitter = get_trace_emitter()

        if not ticker:
            if agent_name == "macro":
                ticker = ""
            else:
                return await self._handle_search(query, None, classification, context_summary)

        try:
            agent = self.agents.get(agent_name)
            if not agent:
                return self._result(
                    success=False,
                    intent=classification.intent,
                    response=f"Agent {agent_name} 不可用",
                    classification=classification
                )

            # Enhance query with context if available
            enhanced_query = query
            if context_summary:
                enhanced_query = f"{query}\n\n【参考上下文】\n{context_summary}"

            self._consume_round(f"agent:{agent_name}")
            # 发射 Agent 开始事件
            trace_emitter.emit_agent_start(f"{agent_name.capitalize()}Agent", query=enhanced_query, ticker=ticker)
            agent_start_time = time.perf_counter()

            output = await agent.research(enhanced_query, ticker)

            # 发射 Agent 完成事件
            agent_duration_ms = int((time.perf_counter() - agent_start_time) * 1000)
            trace_emitter.emit_agent_done(
                f"{agent_name.capitalize()}Agent",
                duration_ms=agent_duration_ms,
                success=bool(output and output.summary)
            )

            base_response = output.summary if output else "分析完成，但无结果"

            # If context exists and agent returns result, optionally enhance with LLM
            if context_summary and output and output.summary:
                try:
                    from langchain_core.messages import HumanMessage
                    prompt = f"""<role>{agent_name}分析专家</role>
<task>结合上下文优化分析回复</task>

<analysis>{output.summary[:1500]}</analysis>
<context>{context_summary}</context>
<query>{query}</query>

<rules>
- 禁止开场白（不要说"好的"、"根据分析"等）
- 直接输出优化后的分析内容
- 融入上下文相关话题
- 保持专业简洁
</rules>"""
                    # 发射 LLM 调用开始事件
                    llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
                    trace_emitter.emit_llm_start(model=llm_model, prompt_preview=prompt[:150])
                    llm_start_time = time.perf_counter()

                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])

                    # 发射 LLM 调用结束事件
                    llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
                    base_response = response.content if hasattr(response, 'content') else str(response)
                    trace_emitter.emit_llm_end(
                        model=llm_model,
                        duration_ms=llm_duration_ms,
                        success=True,
                        output_preview=base_response[:100] if base_response else None
                    )
                except Exception as e:
                    logger.info(f"[Supervisor] {agent_name} context enhancement failed: {e}")

            return self._result(
                success=True,
                intent=classification.intent,
                response=base_response,
                agent_outputs={agent_name: output},
                classification=classification
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=classification.intent,
                response=f"{agent_name} 分析出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_report(self, query: str, ticker: str, user_profile: Any, classification: ClassificationResult, context_summary: str = None, on_event: Callable = None) -> SupervisorResult:
        """Handle deep report - multi-Agent collaboration with context awareness"""
        if not ticker:
            return await self._handle_search(query, None, classification, context_summary)

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
                    logger.info(f"[Supervisor] 忽略不相关上下文 (context tickers: {context_tickers}, current: {ticker})")
                    relevant_context = None
                else:
                    relevant_context = context_summary

            # Enhance query with context only if relevant
            enhanced_query = query
            if relevant_context:
                enhanced_query = f"{query}\n\n【参考上下文】\n{relevant_context}"

            # Plan-driven execution with retries/dependencies
            from backend.orchestration.plan import PlanBuilder, PlanExecutor

            agent_names = list(self.agents.keys())
            plan = PlanBuilder.build_report_plan(enhanced_query, ticker, agent_names)
            executor = PlanExecutor(self.agents, self.forum, budget=self._budget)
            execution = await executor.execute(
                plan,
                enhanced_query,
                ticker,
                user_profile=user_profile,
                context_summary=relevant_context,
                on_event=on_event,
            )

            valid_outputs = execution.get("agent_outputs", {})
            errors = execution.get("errors", [])
            forum_result = execution.get("forum_output")

            if forum_result is None:
                # Forum 失败时构造兜底综合报告，避免前端缺失整合报告/证据池
                try:
                    from backend.orchestration.forum import ForumOutput
                    context_parts = {}
                    for name, output in valid_outputs.items():
                        key = str(name).lower().replace("agent", "")
                        if output and hasattr(output, "summary"):
                            summary_info = f"摘要: {output.summary}\n置信度: {getattr(output, 'confidence', 0.6):.0%}"
                            ev_list = getattr(output, "evidence", []) or []
                            if ev_list:
                                summary_info += f"\n证据数量: {len(ev_list)}"
                        else:
                            summary_info = "无数据"
                        context_parts[key] = summary_info

                    for key in ["price", "news", "technical", "fundamental", "deep_search", "macro"]:
                        context_parts.setdefault(key, "无数据")

                    if hasattr(self.forum, "_fallback_synthesis"):
                        fallback_consensus = self.forum._fallback_synthesis(context_parts)
                    else:
                        summaries = []
                        for name, output in valid_outputs.items():
                            if output and hasattr(output, "summary") and output.summary:
                                summaries.append(f"**{name}**: {str(output.summary)[:400]}")
                        fallback_consensus = "\n\n".join(summaries) if summaries else "综合分析暂时不可用。"

                    conf_values = [getattr(out, "confidence", 0.6) for out in valid_outputs.values() if out]
                    avg_conf = sum(conf_values) / len(conf_values) if conf_values else 0.6

                    forum_result = ForumOutput(
                        consensus=fallback_consensus,
                        disagreement="",
                        confidence=avg_conf,
                        recommendation="HOLD",
                        risks=["综合分析暂时不可用", "已使用简化合成"]
                    )
                    errors = list(errors) if errors else []
                    errors.append("forum: fallback_synthesis_used")
                    logger.warning("[Supervisor] forum_output is None, using fallback synthesis")
                except Exception as exc:
                    logger.warning(f"[Supervisor] fallback synthesis failed: {exc}")

            return self._result(
                success=True,
                intent=AgentIntent.REPORT,
                response=forum_result.consensus if forum_result else "报告生成完成",
                agent_outputs=valid_outputs,
                forum_output=forum_result,
                classification=classification,
                errors=errors if errors else None
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=AgentIntent.REPORT,
                response=f"生成报告时出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_comparison(self, query: str, tickers: List[str], classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Handle comparison analysis with context awareness"""
        if len(tickers) < 2:
            return await self._handle_search(query, None, classification, context_summary)

        trace_emitter = get_trace_emitter()

        try:
            self._consume_round("tool:comparison")
            # 发射工具调用开始事件
            trace_emitter.emit_tool_start("get_performance_comparison", {"tickers": tickers})
            tool_start_time = time.perf_counter()

            comparison_data = self.tools_module.get_performance_comparison(tickers)

            # 发射工具调用结束事件
            tool_duration_ms = int((time.perf_counter() - tool_start_time) * 1000)
            trace_emitter.emit_tool_end(
                "get_performance_comparison",
                success=comparison_data is not None,
                duration_ms=tool_duration_ms,
                result_preview=str(comparison_data)[:100] if comparison_data else None
            )

            base_response = str(comparison_data) if comparison_data else "对比完成，但无数据"

            selected_agents = self._select_agents_for_query(query)
            agent_outputs: Dict[str, Any] = {}
            errors: List[str] = []

            async def run_agent(agent_name: str, ticker: str):
                agent = self.agents.get(agent_name)
                if not agent:
                    return agent_name, ticker, None, f"Agent {agent_name} 不可用"
                enhanced_query = query
                if context_summary:
                    enhanced_query = f"{query}\n\n【参考上下文】\n{context_summary}"
                try:
                    self._consume_round(f"agent:{agent_name}")
                    # 发射 Agent 开始事件
                    trace_emitter.emit_agent_start(f"{agent_name.capitalize()}Agent", query=enhanced_query[:100], ticker=ticker)
                    agent_start_time = time.perf_counter()

                    output = await agent.research(enhanced_query, ticker)

                    # 发射 Agent 完成事件
                    agent_duration_ms = int((time.perf_counter() - agent_start_time) * 1000)
                    trace_emitter.emit_agent_done(
                        f"{agent_name.capitalize()}Agent",
                        duration_ms=agent_duration_ms,
                        success=bool(output and getattr(output, 'summary', None))
                    )

                    return agent_name, ticker, output, None
                except Exception as exc:
                    # 发射 Agent 错误事件
                    trace_emitter.emit_agent_done(
                        f"{agent_name.capitalize()}Agent",
                        duration_ms=0,
                        success=False
                    )
                    return agent_name, ticker, None, str(exc)

            tasks = []
            for ticker in tickers:
                for agent_name in selected_agents:
                    tasks.append(run_agent(agent_name, ticker))
            if tasks:
                results = await asyncio.gather(*tasks)
                for agent_name, ticker, output, err in results:
                    key = f"{agent_name}_{ticker}"
                    if output:
                        agent_outputs[key] = output
                    if err:
                        errors.append(f"{key}: {err}")

            # If context exists, enhance with LLM
            if self.llm and (comparison_data or agent_outputs):
                try:
                    from langchain_core.messages import HumanMessage
                    summaries = []
                    for ticker in tickers:
                        ticker_summaries = []
                        for agent_name in selected_agents:
                            key = f"{agent_name}_{ticker}"
                            output = agent_outputs.get(key)
                            if output and getattr(output, "summary", None):
                                ticker_summaries.append(f"{agent_name}: {str(output.summary)[:400]}")
                        if ticker_summaries:
                            summaries.append(f"{ticker}:\n- " + "\n- ".join(ticker_summaries))
                    summaries_text = "\n\n".join(summaries) if summaries else "无额外 Agent 分析摘要"

                    prompt = f"""<role>股票对比分析师</role>
<task>解读股票对比结果</task>

<comparison>{base_response[:2000]}</comparison>
<agent_summaries>{summaries_text[:2500]}</agent_summaries>
<context>{context_summary or '无'}</context>
<query>{query}</query>

<rules>
- 禁止开场白，直接输出对比解读
- 3-5句话总结核心差异
- 融入上下文（投资偏好、历史讨论）
- 给出明确的对比结论
- 如某维度无数据，明确说明
</rules>"""
                    # 发射 LLM 调用开始事件
                    llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
                    trace_emitter.emit_llm_start(model=llm_model, prompt_preview=prompt[:150])
                    llm_start_time = time.perf_counter()

                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])

                    # 发射 LLM 调用结束事件
                    llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    trace_emitter.emit_llm_end(
                        model=llm_model,
                        duration_ms=llm_duration_ms,
                        success=True,
                        output_preview=response_text[:100] if response_text else None
                    )
                    missing = [t for t in tickers if t and t.upper() not in response_text.upper()]
                    if missing:
                        response_text = f"{base_response}\n\n{response_text}"
                    return self._result(
                        success=True,
                        intent=AgentIntent.COMPARISON,
                        response=response_text,
                        agent_outputs=agent_outputs or None,
                        classification=classification,
                        errors=errors if errors else None
                    )
                except Exception as e:
                    logger.info(f"[Supervisor] Comparison context enhancement failed: {e}")

            return self._result(
                success=True,
                intent=AgentIntent.COMPARISON,
                response=base_response,
                agent_outputs=agent_outputs or None,
                classification=classification,
                errors=errors if errors else None
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=AgentIntent.COMPARISON,
                response=f"对比分析出错: {e}",
                classification=classification,
                errors=[str(e)]
            )

    async def _handle_search(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """Fallback search with context awareness"""
        trace_emitter = get_trace_emitter()

        try:
            self._consume_round("tool:search")
            # 发射工具调用开始事件
            trace_emitter.emit_tool_start("search", {"query": query})
            tool_start_time = time.perf_counter()

            search_result = self.tools_module.search(query)

            # 发射工具调用结束事件
            tool_duration_ms = int((time.perf_counter() - tool_start_time) * 1000)
            trace_emitter.emit_tool_end(
                "search",
                success=search_result is not None,
                duration_ms=tool_duration_ms,
                result_preview=str(search_result)[:100] if search_result else None
            )

            # Use LLM to synthesize search results with context
            from langchain_core.messages import HumanMessage

            prompt = f"""<role>金融信息检索专家</role>
<task>综合搜索结果回答问题</task>

<query>{query}</query>
<search_results>{search_result}</search_results>
{f"<context>{context_summary}</context>" if context_summary else ""}

<rules>
- 禁止开场白，直接回答问题
- 2-4句话，简洁准确
- 基于搜索结果，不编造信息
- 中文回复
{f"- 结合上下文话题" if context_summary else ""}
</rules>"""

            # 发射 LLM 调用开始事件
            llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
            trace_emitter.emit_llm_start(model=llm_model, prompt_preview=prompt[:150])
            llm_start_time = time.perf_counter()

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])

            # 发射 LLM 调用结束事件
            llm_duration_ms = int((time.perf_counter() - llm_start_time) * 1000)
            response_text = response.content if hasattr(response, 'content') else str(response)
            trace_emitter.emit_llm_end(
                model=llm_model,
                duration_ms=llm_duration_ms,
                success=True,
                output_preview=response_text[:100] if response_text else None
            )

            return self._result(
                success=True,
                intent=AgentIntent.SEARCH,
                response=response_text,
                classification=classification
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=AgentIntent.SEARCH,
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

            # 截断策略：
            # - System Context（由 main.py 构建）：完整保留，因为它是精心设计的上下文
            # - 用户/助手消息：截断到 150 字符，避免对话历史过长
            if role == "system":
                # System 消息完整保留（包含 Selection Context 等关键信息）
                preview = content
            else:
                # 普通消息截断到 150 字符
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
                    logger.info(f"[Supervisor] URL fetch failed: {url}, error: {e}")

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
            logger.info(f"[Supervisor] URL summarize failed: {e}")

        return None

    async def process_stream(
        self,
        query: str,
        tickers: List[str] = None,
        user_profile: Any = None,
        conversation_context: List[Dict] = None,
        agent_gate: Optional[Dict[str, Any]] = None,
    ):
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
        budget = BudgetManager.from_env()
        self._set_budget(budget)
        if self.tools_module and not isinstance(self.tools_module, BudgetedTools):
            self.tools_module = BudgetedTools(self.tools_module, budget)
        self._agents = None

        thinking_steps = []  # 收集思考步骤
        trace_emitter = get_trace_emitter()
        stream_start_time = time.perf_counter()

        # 连接 TraceEmitter 的 async_queue，使所有 emit_* 事件流入此队列
        trace_queue = asyncio.Queue()
        trace_emitter.set_async_queue(trace_queue)

        # 发射 Supervisor 开始事件
        trace_emitter.emit_supervisor_start(query=query, tickers=tickers)

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

            if agent_gate:
                step_gate = {
                    "stage": "agent_gate",
                    "message": "评估是否需要调用多Agent",
                    "result": agent_gate,
                    "timestamp": datetime.now().isoformat()
                }
                thinking_steps.append(step_gate)
                yield json.dumps({"type": "thinking", **step_gate}, ensure_ascii=False)

            # 3. 执行对应处理器
            step3 = {
                "stage": "processing",
                "message": "正在处理请求...",
                "timestamp": datetime.now().isoformat()
            }
            thinking_steps.append(step3)
            yield json.dumps({"type": "thinking", **step3}, ensure_ascii=False)

            # 使用 asyncio.Queue 实现流式事件监听
            event_queue = asyncio.Queue()
            
            def event_listener(event):
                try:
                    event_queue.put_nowait(event)
                except Exception:
                    pass

            # 异步执行 process，同时监听事件
            process_task = asyncio.create_task(
                self.process(query, tickers, user_profile, context_summary=context_summary, context_ticker=context_ticker, on_event=event_listener)
            )
            
            # 循环等待任务完成，同时处理事件
            while not process_task.done():
                try:
                    # 等待事件，0.05秒超时检查任务状态
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.05)
                    
                    # 将内部事件转换为前端 thinking 格式
                    evt_type = event.get("event")
                    agent_name = event.get("agent", "System")
                    step_id = event.get("step_id", "unknown")
                    timestamp = event.get("timestamp")
                    
                    msg = None
                    if evt_type == "step_start":
                        msg = f"正在执行: {agent_name or step_id}..."
                    elif evt_type == "step_done":
                        msg = f"完成: {agent_name or step_id}"
                    elif evt_type == "step_error":
                        msg = f"出错: {agent_name or step_id} ({event.get('details', {}).get('error')})"
                    elif evt_type == "step_retry":
                         msg = f"重试: {agent_name or step_id} (次数: {event.get('details', {}).get('attempt')})"
                    elif evt_type == "agent_action":
                        msg = event.get('details', {}).get('message')
                    elif evt_type == "agent_execution":
                        details = event.get('details', {})
                        sub_type = details.get('type')
                        if sub_type == 'search_result':
                             msg = f"{agent_name}: 搜索到 {details.get('result_count')} 条结果"
                        elif sub_type == 'reflection_gap':
                             msg = f"{agent_name}: 发现信息缺失，补充搜索..."
                        elif sub_type == 'convergence_final':
                             # Too detailed, skip
                             pass

                    if msg:
                        t_step = {
                            "stage": f"{step_id}_{evt_type}",
                            "message": msg,
                            "timestamp": timestamp
                        }
                        thinking_steps.append(t_step)
                        yield json.dumps({"type": "thinking", **t_step}, ensure_ascii=False)
                        
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.error(f"[process_stream] Event loop error: {e}")

                # 每轮都排空 trace_queue，将 TraceEmitter 事件转为 SSE
                try:
                    while True:
                        trace_evt = trace_queue.get_nowait()
                        yield json.dumps(trace_evt.to_sse_dict(), ensure_ascii=False)
                except asyncio.QueueEmpty:
                    pass

            # 主循环结束后再排空一次，捕获最后残留的 trace 事件
            try:
                while True:
                    trace_evt = trace_queue.get_nowait()
                    yield json.dumps(trace_evt.to_sse_dict(), ensure_ascii=False)
            except asyncio.QueueEmpty:
                pass

            # 获取结果
            result = await process_task

            # 4. 发送响应内容（作为 token 流式输出）
            if result.response:
                response_text = result.response
                chunk_size = 12  # 优化分块大小，平衡流式效果和性能
                for i in range(0, len(response_text), chunk_size):
                    chunk = response_text[i:i + chunk_size]
                    yield json.dumps({
                        "type": "token",
                        "content": chunk
                    }, ensure_ascii=False)
                    # 添加小延迟，让前端有时间渲染每个 chunk
                    await asyncio.sleep(0.015)

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

            # 构建 report 数据（如果是 REPORT 意图）
            report_data = None
            if result.intent == AgentIntent.REPORT:
                if result.forum_output:
                    # 从 forum_output 构建完整的 ReportIR 格式
                    report_data = self._build_report_ir(result, first_ticker, classification)
                elif result.response and first_ticker:
                    # forum_output 为空但有响应文本，生成简化报告
                    logger.warning(f"[process_stream] forum_output is None, building fallback report from response")
                    report_data = self._build_fallback_report(result, first_ticker, classification)

            # 构建 agent_traces 用于前端展示详细的 Agent 思考流程
            agent_traces = {}
            if result.agent_outputs:
                for agent_name, agent_output in result.agent_outputs.items():
                    trace = getattr(agent_output, 'trace', None)
                    if trace:
                        agent_traces[agent_name] = trace
                    # 添加 Agent 执行步骤到 thinking_steps
                    agent_step = {
                        "stage": f"agent_{agent_name}",
                        "message": f"{agent_name} 分析完成",
                        "timestamp": datetime.now().isoformat(),
                        "result": {
                            "agent": agent_name,
                            "confidence": getattr(agent_output, 'confidence', 0),
                            "summary": (getattr(agent_output, 'summary', '') or '')[:200],
                            "trace": trace or []
                        }
                    }
                    thinking_steps.insert(-1, agent_step)  # 插入到 complete 步骤之前
                if agent_traces:
                    base_agents = []
                    for name in agent_traces.keys():
                        base = str(name).split("_")[0]
                        if base not in base_agents:
                            base_agents.append(base)
                    select_step = {
                        "stage": "agent_selected",
                        "message": "已选择专家Agent",
                        "timestamp": datetime.now().isoformat(),
                        "result": {"agents": base_agents, "agent_keys": list(agent_traces.keys())}
                    }
                    thinking_steps.insert(-1, select_step)

            # 发射 Supervisor 完成事件
            total_duration_ms = int((time.perf_counter() - stream_start_time) * 1000)
            trace_emitter.emit_supervisor_done(
                query=query,
                intent=result.intent.value if result.intent else None,
                success=result.success,
                duration_ms=total_duration_ms
            )

            yield json.dumps({
                "type": "done",
                "success": result.success,
                "intent": result.intent.value,
                "current_focus": first_ticker,
                "response": str(result.response) if result.response is not None else "",
                "thinking": thinking_steps,  # 前端期望在 done 事件中收到 thinking 数组
                "agent_traces": agent_traces,  # 新增：完整的 Agent trace
                "errors": result.errors,
                "budget": result.budget,
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
        finally:
            # 清理 TraceEmitter async_queue，防止跨请求泄漏
            trace_emitter.clear_async_queue()

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
        from backend.orchestration.data_context import DataContextCollector
        from backend.report.disclaimer import build_disclaimer_section, DISCLAIMER_TEXT
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
        agent_sections = {
            "price": {"title": "价格分析", "agent": "PriceAgent"},
            "news": {"title": "新闻分析", "agent": "NewsAgent"},
            "technical": {"title": "技术分析", "agent": "TechnicalAgent"},
            "fundamental": {"title": "基本面分析", "agent": "FundamentalAgent"},
            "macro": {"title": "宏观分析", "agent": "MacroAgent"},
            "deep_search": {"title": "深度搜索", "agent": "DeepSearchAgent"},
        }

        def _agent_error(agent_key: str) -> Optional[str]:
            for err in errors_list:
                if isinstance(err, str) and err.startswith(f"{agent_key}:"):
                    return err.split(":", 1)[1].strip() if ":" in err else err
            return None

        context_collector = DataContextCollector()
        for agent_name, agent_output in agent_outputs.items():
            context_collector.add(
                str(agent_name),
                as_of=getattr(agent_output, 'as_of', None),
                currency=getattr(agent_output, 'currency', None),
                adjustment=getattr(agent_output, 'adjustment', None),
                ticker=ticker,
            )
        data_context = context_collector.summarize().to_dict()

        # 构建 sections - 优先从 Forum 完整分析解析
        sections = []
        section_order = 1

        # 优先使用 forum_output.consensus（原始 Forum 输出），而非可能被修改的 result.response
        forum_text = getattr(forum_output, 'consensus', None) or result.response
        forum_sections = self._parse_forum_sections(forum_text) if forum_text else []

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
            for agent_key, section_info in agent_sections.items():
                section_title = section_info["title"]
                agent_display_name = section_info["agent"]

                # 检查是否有这个 agent 的错误
                agent_error = _agent_error(agent_key)

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
        disclaimer_section = build_disclaimer_section(section_order)
        sections.append(disclaimer_section)
        section_order += 1

        agent_status = {}
        for agent_key in ["price", "news", "technical", "fundamental", "macro", "deep_search"]:
            if agent_key in agent_outputs and agent_outputs[agent_key]:
                agent_output = agent_outputs[agent_key]
                confidence = getattr(agent_output, 'confidence', 0.5)
                agent_status[agent_key] = {"status": "success", "confidence": confidence}
            else:
                # 检查是否有错误
                agent_error = _agent_error(agent_key)
                if agent_error:
                    agent_status[agent_key] = {"status": "error", "error": agent_error}

        agent_summaries = []
        for agent_key, section_info in agent_sections.items():
            agent_output = agent_outputs.get(agent_key)
            agent_error = _agent_error(agent_key)
            if agent_output:
                status = "success"
            elif agent_error:
                status = "error"
            else:
                status = "not_run"
            summary = None
            if agent_output and getattr(agent_output, "summary", None):
                summary = safe_str(agent_output.summary)
            elif status == "not_run":
                summary = "未运行（本轮未触发或无匹配意图）"
            agent_summaries.append({
                "agent": agent_key,
                "agent_name": section_info["agent"],
                "title": section_info["title"],
                "summary": summary,
                "confidence": float(getattr(agent_output, "confidence", 0.0)) if agent_output else 0.0,
                "data_sources": getattr(agent_output, "data_sources", []) if agent_output else [],
                "status": status,
                "error": bool(agent_error),
                "error_message": agent_error,
            })

        # 构建 citations
        def _calc_freshness_hours(published_date: str) -> float:
            if not published_date:
                return 24.0
            try:
                pub_dt = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
                now = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
                delta = now - pub_dt
                return max(0.0, delta.total_seconds() / 3600)
            except Exception:
                return 24.0

        citations = []
        citation_id = 1

        # Debug: 记录每个 Agent 的 evidence 数量
        for agent_name, agent_output in agent_outputs.items():
            evidence_list = getattr(agent_output, 'evidence', None)
            logger.info(f"[_build_report_ir] {agent_name}: evidence_list type={type(evidence_list)}, length={len(evidence_list) if evidence_list else 0}")
            if evidence_list:
                # 增加每个 Agent 的 evidence 数量限制到 5 条
                for evidence in evidence_list[:5]:
                    # 更健壮的属性提取
                    if isinstance(evidence, dict):
                        title = evidence.get('title') or evidence.get('source', f"{agent_name} 来源")
                        url = evidence.get('url', '') or "#"
                        text = evidence.get('text', '')
                        timestamp = evidence.get('timestamp')
                        confidence = evidence.get('confidence', 0.7)
                    else:
                        title = getattr(evidence, 'title', None) or getattr(evidence, 'source', f"{agent_name} 来源")
                        url = getattr(evidence, 'url', '') or "#"
                        text = getattr(evidence, 'text', '')
                        timestamp = getattr(evidence, 'timestamp', None)
                        confidence = getattr(evidence, "confidence", 0.7)

                    published_date = safe_str(timestamp)
                    try:
                        confidence = float(confidence)
                    except (TypeError, ValueError):
                        confidence = 0.7
                    confidence = max(0.0, min(1.0, confidence))
                    freshness_hours = _calc_freshness_hours(published_date)

                    # 确保 title 和 text 不为空
                    if not title or title == "#":
                        title = f"{agent_name} Evidence {citation_id}"
                    if not text:
                        text = "No description available"

                    citation = {
                        "source_id": f"src_{citation_id}",
                        "title": safe_str(title),
                        "url": safe_str(url),
                        "snippet": safe_str(text)[:200] if text else "",
                        "published_date": published_date,
                        "confidence": confidence,
                        "freshness_hours": freshness_hours,
                    }
                    citations.append(citation)
                    logger.info(f"[_build_report_ir] Added citation {citation_id} from {agent_name}: {citation['title'][:50]}")
                    citation_id += 1

        # Debug log
        logger.info(f"[_build_report_ir] Built {len(citations)} citations from {len(agent_outputs)} agents")

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
            "title": f"{ticker} 分析报告" if ticker else "深度分析报告",
            "summary": summary,
            "sentiment": sentiment,
            "confidence_score": float(getattr(forum_output, 'confidence', 0.7)) if forum_output else 0.7,
            "generated_at": datetime.now().isoformat(),
            # 保存 Forum 的完整原始文本（整合报告）
            "synthesis_report": forum_text if forum_text else None,
            "sections": sections,
            "citations": citations,
            "risks": risks,
            "recommendation": safe_str(getattr(forum_output, 'recommendation', 'HOLD')) if forum_output else "HOLD",
            "agent_status": agent_status,
            "errors": errors_list if errors_list else None,
            "meta": {
                "data_context": data_context,
                "disclaimer": DISCLAIMER_TEXT,
                "agent_summaries": agent_summaries,
            },
        }

        return report_ir

    def _parse_forum_sections(self, forum_text: str) -> list:
        """
        解析 Forum 的 8 节分析文本为结构化章节
        支持多种标题格式：### 1. / ## 1. / **1.** 等
        """
        import re

        if not forum_text:
            return []

        sections = []

        # 尝试多种标题模式
        patterns = [
            r'###\s*(\d+)\.\s*([^\n]+)\n([\s\S]*?)(?=###\s*\d+\.|$)',  # ### 1. 标题
            r'##\s*(\d+)\.\s*([^\n]+)\n([\s\S]*?)(?=##\s*\d+\.|$)',    # ## 1. 标题
            r'\*\*(\d+)\.\s*([^\*]+)\*\*\s*\n([\s\S]*?)(?=\*\*\d+\.|$)',  # **1. 标题**
        ]

        for pattern in patterns:
            matches = re.findall(pattern, forum_text)
            if matches:
                for match in matches:
                    order, title, content = match
                    # 清理标题中的 emoji 和多余空格
                    clean_title = re.sub(r'[📊📈💰🌍⚠️🎯📐📅🔍💡📉🏢]\s*', '', title).strip()
                    clean_content = content.strip()

                    if clean_title and clean_content:
                        sections.append({
                            "title": clean_title,
                            "content": clean_content
                        })
                break  # 找到匹配的模式后停止

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

    def _build_fallback_report(self, result: SupervisorResult, ticker: str, classification: ClassificationResult) -> dict:
        """
        构建后备报告（当 forum_output 为空时）
        
        Args:
            result: SupervisorResult
            ticker: 股票代码
            classification: 意图分类结果
            
        Returns:
            dict: 简化的 ReportIR 格式报告
        """
        from datetime import datetime
        import uuid
        
        response_text = str(result.response) if result.response else "报告生成中..."
        
        # 从 agent_outputs 构建 sections
        sections = []
        section_order = 1
        agent_outputs = result.agent_outputs or {}
        agent_sections = {
            "price": {"title": "价格分析", "agent": "PriceAgent"},
            "news": {"title": "新闻分析", "agent": "NewsAgent"},
            "technical": {"title": "技术分析", "agent": "TechnicalAgent"},
            "fundamental": {"title": "基本面分析", "agent": "FundamentalAgent"},
            "macro": {"title": "宏观分析", "agent": "MacroAgent"},
            "deep_search": {"title": "深度搜索", "agent": "DeepSearchAgent"},
        }

        def _agent_error(agent_key: str) -> Optional[str]:
            for err in result.errors or []:
                if isinstance(err, str) and err.startswith(f"{agent_key}:"):
                    return err.split(":", 1)[1].strip() if ":" in err else err
            return None
        
        for agent_name, agent_output in agent_outputs.items():
            if hasattr(agent_output, 'summary') and agent_output.summary:
                sections.append({
                    "title": f"{agent_name.capitalize()} 分析",
                    "order": section_order,
                    "agent_name": agent_name,
                    "confidence": getattr(agent_output, 'confidence', 0.5),
                    "contents": [{
                        "type": "text",
                        "content": str(agent_output.summary)[:1000]
                    }]
                })
                section_order += 1
        
        # 如果没有 agent 输出，使用 response 作为内容
        if not sections and response_text:
            sections.append({
                "title": "分析摘要",
                "order": 1,
                "agent_name": "Supervisor",
                "confidence": 0.7,
                "contents": [{
                    "type": "text",
                    "content": response_text
                }]
            })

        agent_summaries = []
        for agent_key, section_info in agent_sections.items():
            agent_output = agent_outputs.get(agent_key)
            agent_error = _agent_error(agent_key)
            if agent_output:
                status = "success"
            elif agent_error:
                status = "error"
            else:
                status = "not_run"
            summary = None
            if agent_output and getattr(agent_output, 'summary', None):
                summary = str(agent_output.summary)
            elif status == "not_run":
                summary = "未运行（本轮未触发或无匹配意图）"
            agent_summaries.append({
                "agent": agent_key,
                "agent_name": section_info["agent"],
                "title": section_info["title"],
                "summary": summary,
                "confidence": float(getattr(agent_output, "confidence", 0.0)) if agent_output else 0.0,
                "data_sources": getattr(agent_output, "data_sources", []) if agent_output else [],
                "status": status,
                "error": bool(agent_error),
                "error_message": agent_error,
            })
        
        # 构建 citations（证据池）
        citations = []
        citation_id = 1
        for agent_name, agent_output in agent_outputs.items():
            evidence_list = getattr(agent_output, 'evidence', None) if agent_output else None
            if not evidence_list:
                continue
            for evidence in evidence_list[:5]:
                if isinstance(evidence, dict):
                    title = evidence.get('title') or evidence.get('source', f"{agent_name} 来源")
                    url = evidence.get('url', '') or "#"
                    text = evidence.get('text', '')
                    timestamp = evidence.get('timestamp')
                    confidence = evidence.get('confidence', 0.7)
                else:
                    title = getattr(evidence, 'title', None) or getattr(evidence, 'source', f"{agent_name} 来源")
                    url = getattr(evidence, 'url', '') or "#"
                    text = getattr(evidence, 'text', '')
                    timestamp = getattr(evidence, 'timestamp', None)
                    confidence = getattr(evidence, 'confidence', 0.7)

                if not title:
                    title = f"{agent_name} Evidence {citation_id}"
                citation = {
                    "source_id": f"src_{citation_id}",
                    "title": str(title),
                    "url": str(url),
                    "snippet": str(text)[:200] if text else "",
                    "published_date": str(timestamp) if timestamp else "",
                    "confidence": float(confidence) if confidence is not None else 0.7,
                    "freshness_hours": 24.0,
                }
                citations.append(citation)
                citation_id += 1

        # 构建 agent_status
        agent_status = {}
        for agent_name in ["price", "news", "technical", "fundamental", "macro", "deep_search"]:
            if agent_name in agent_outputs:
                agent_output = agent_outputs[agent_name]
                agent_status[agent_name] = {
                    "status": "success",
                    "confidence": getattr(agent_output, 'confidence', 0.5)
                }
            else:
                agent_error = _agent_error(agent_name)
                if agent_error:
                    agent_status[agent_name] = {"status": "error", "error": agent_error}
        
        return {
            "report_id": f"fallback_{uuid.uuid4().hex[:8]}",
            "ticker": ticker or "UNKNOWN",
            "company_name": ticker or "未知公司",
            "title": f"{ticker} 分析报告" if ticker else "分析报告",
            "summary": response_text[:500] if response_text else "分析完成",
            "sentiment": "neutral",
            "confidence_score": 0.6,
            "generated_at": datetime.now().isoformat(),
            "synthesis_report": response_text,
            "sections": sections,
            "citations": citations,
            "risks": ["数据可能不完整"],
            "recommendation": "HOLD",
            "agent_status": agent_status,
            "meta": {
                "is_fallback": True,
                "errors": result.errors,
                "agent_summaries": agent_summaries
            }
        }
