# -*- coding: utf-8 -*-
"""
SmartRouter - 智能路由器
让 LLM 自主选择使用什么工具/Agent，而不是写死规则
"""

from typing import Dict, Any, Optional, List, Tuple
from enum import Enum


class ToolChoice(Enum):
    """工具选择"""
    PRICE = "price"           # 价格查询
    NEWS = "news"             # 新闻查询
    SENTIMENT = "sentiment"   # 市场情绪
    COMPOSITION = "composition"  # 成分/占比
    COMPARISON = "comparison"    # 对比分析
    FINANCIAL = "financial"      # 财报数据
    REPORT = "report"            # 深度报告
    SEARCH = "search"            # 通用搜索
    GREETING = "greeting"        # 问候
    CLARIFY = "clarify"          # 需要澄清


# 工具描述 - 告诉 LLM 每个工具是干什么的
TOOL_DESCRIPTIONS = """
你是一个金融助手的路由器。根据用户的问题，选择最合适的工具。

可用工具：
1. price - 获取股票/指数实时价格
   适用：问价格、股价、多少钱、涨跌

2. news - 获取公司/市场新闻
   适用：问新闻、快讯、消息、最近发生什么

3. sentiment - 获取市场情绪指数
   适用：问恐惧贪婪、市场情绪、风险偏好

4. composition - 查询指数成分/持仓占比
   适用：问成分股、占比、权重、持仓比例

5. comparison - 对比多个标的
   适用：对比、比较、A vs B

6. financial - 获取财报数据
   适用：问财报、营收、利润、EPS

7. report - 生成深度分析报告（耗时较长）
   适用：明确要求"详细分析"、"投资报告"、"值得买吗"

8. search - 通用搜索（兜底）
   适用：其他金融相关问题

9. greeting - 问候回复
   适用：你好、介绍自己

10. clarify - 需要澄清
    适用：问题不清楚、缺少关键信息、非金融问题

重要规则：
- 简单查询（价格、新闻、占比）优先用轻量工具，不要用 report
- 只有用户明确要求"详细分析"、"投资报告"时才用 report
- 如果问题包含具体股票代码，优先处理而不是要求澄清
"""


class SmartRouter:
    """
    智能路由器 - 让 LLM 自主选择工具
    """

    def __init__(self, llm=None):
        self.llm = llm

    def route(self, query: str, tickers: List[str] = None, context: str = "") -> Tuple[ToolChoice, Dict[str, Any]]:
        """
        智能路由：让 LLM 决定用什么工具

        Args:
            query: 用户查询
            tickers: 已识别的股票代码
            context: 对话上下文

        Returns:
            (ToolChoice, metadata)
        """
        if not self.llm:
            # 没有 LLM 时回退到简单规则
            return self._fallback_route(query, tickers)

        # 构建 prompt
        prompt = f"""{TOOL_DESCRIPTIONS}

用户问题: {query}
已识别的股票代码: {tickers or '无'}
对话上下文: {context or '无'}

请选择最合适的工具（只回复工具名称，如 price/news/report 等）："""

        try:
            from langchain_core.messages import HumanMessage
            response = self.llm.invoke([HumanMessage(content=prompt)])
            choice_str = response.content.strip().lower()

            # 解析 LLM 的选择
            choice = self._parse_choice(choice_str)
            print(f"[SmartRouter] LLM 选择: {query[:30]}... -> {choice.value}")

            return choice, {"tickers": tickers, "raw_query": query}

        except Exception as e:
            print(f"[SmartRouter] LLM 路由失败: {e}")
            return self._fallback_route(query, tickers)

    def _parse_choice(self, choice_str: str) -> ToolChoice:
        """解析 LLM 的选择"""
        choice_map = {
            "price": ToolChoice.PRICE,
            "news": ToolChoice.NEWS,
            "sentiment": ToolChoice.SENTIMENT,
            "composition": ToolChoice.COMPOSITION,
            "comparison": ToolChoice.COMPARISON,
            "financial": ToolChoice.FINANCIAL,
            "report": ToolChoice.REPORT,
            "search": ToolChoice.SEARCH,
            "greeting": ToolChoice.GREETING,
            "clarify": ToolChoice.CLARIFY,
        }

        # 尝试匹配
        for key, value in choice_map.items():
            if key in choice_str:
                return value

        return ToolChoice.SEARCH  # 默认兜底

    def _fallback_route(self, query: str, tickers: List[str] = None) -> Tuple[ToolChoice, Dict[str, Any]]:
        """简单规则回退（无 LLM 时使用）"""
        query_lower = query.lower()

        # 问候
        if any(kw in query_lower for kw in ['你好', 'hello', 'hi', '你是谁']):
            return ToolChoice.GREETING, {"tickers": tickers}

        # 有 ticker 时的简单判断
        if tickers:
            if any(kw in query_lower for kw in ['价格', '股价', '多少钱']):
                return ToolChoice.PRICE, {"tickers": tickers}
            if any(kw in query_lower for kw in ['新闻', '快讯', '消息']):
                return ToolChoice.NEWS, {"tickers": tickers}
            if any(kw in query_lower for kw in ['占比', '成分', '权重']):
                return ToolChoice.COMPOSITION, {"tickers": tickers}
            if any(kw in query_lower for kw in ['详细分析', '投资报告', '值得买']):
                return ToolChoice.REPORT, {"tickers": tickers}

        return ToolChoice.SEARCH, {"tickers": tickers}
