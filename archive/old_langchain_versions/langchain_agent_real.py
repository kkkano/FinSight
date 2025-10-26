#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真正的LangChain Agent实现
使用LangChain 1.0.2的标准AgentExecutor
"""

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from typing import List, Dict, Any, Optional
from datetime import datetime
import sys

# 导入工具
from tools import (
    get_stock_price, get_company_news, get_company_info,
    search, get_market_sentiment, get_economic_events,
    get_performance_comparison, analyze_historical_drawdowns,
    get_current_datetime
)

# ============================================
# 工具转换为LangChain格式
# ============================================

from langchain.tools import StructuredTool

def create_langchain_tools():
    """将现有Python函数包装成LangChain工具"""

    tools = [
        StructuredTool.from_function(
            func=get_current_datetime,
            name="get_current_datetime",
            description="获取当前日期和时间。无需任何参数。",
        ),
        StructuredTool.from_function(
            func=search,
            name="search",
            description="使用DuckDuckGo搜索网络信息。输入：query字符串",
        ),
        StructuredTool.from_function(
            func=get_stock_price,
            name="get_stock_price",
            description="获取股票实时价格。输入：ticker股票代码（如'AAPL'、'^IXIC'）",
        ),
        StructuredTool.from_function(
            func=get_company_info,
            name="get_company_info",
            description="获取公司基本信息。输入：ticker股票代码",
        ),
        StructuredTool.from_function(
            func=get_company_news,
            name="get_company_news",
            description="获取公司或指数最新新闻。输入：ticker代码",
        ),
        StructuredTool.from_function(
            func=get_market_sentiment,
            name="get_market_sentiment",
            description="获取市场情绪指标（CNN恐惧贪婪指数）。无需参数。",
        ),
        StructuredTool.from_function(
            func=get_economic_events,
            name="get_economic_events",
            description="获取即将到来的重要经济事件。无需参数。",
        ),
        StructuredTool.from_function(
            func=get_performance_comparison,
            name="get_performance_comparison",
            description="比较多个股票的表现。输入：tickers字典，格式{'名称':'代码'}",
        ),
        StructuredTool.from_function(
            func=analyze_historical_drawdowns,
            name="analyze_historical_drawdowns",
            description="分析历史最大回撤。输入：ticker代码",
        ),
    ]

    return tools

# ============================================
# ReAct提示词模板
# ============================================

REACT_PROMPT_TEMPLATE = """你是一位专业的首席投资官(CIO)，负责生成全面、可操作的投资报告。

今天的日期是：{current_date}

你可以使用以下工具：
{tools}

工具使用格式：
```
Thought: 我需要做什么
Action: 工具名称
Action Input: 工具输入参数
Observation: 工具返回结果
... (重复Thought/Action/Observation循环)
Thought: 我现在知道最终答案了
Final Answer: 详细的投资分析报告
```

关键要求：
1. **数据收集阶段**：必须调用4-6个工具收集真实数据
2. **报告撰写阶段**：基于收集的数据写800+字报告
3. **必须包含**：执行摘要、市场定位、宏观环境、风险评估、投资策略、价格目标

用户问题：{input}

开始分析：
{agent_scratchpad}
"""

# ============================================
# Agent类
# ============================================

class LangChainFinancialAgent:
    """真正的LangChain Financial Agent"""

    def __init__(
        self,
        provider: str = "gemini_proxy",
        model: str = "gemini-2.5-flash-preview-05-20",
        verbose: bool = True,
        max_iterations: int = 20
    ):
        """初始化Agent"""

        self.provider = provider
        self.model = model
        self.verbose = verbose

        # 创建LLM
        self.llm = self._create_llm()

        # 创建工具
        self.tools = create_langchain_tools()

        # 创建提示词
        self.prompt = PromptTemplate.from_template(REACT_PROMPT_TEMPLATE)

        # 创建Agent
        self.agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt
        )

        # 创建执行器
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=verbose,
            max_iterations=max_iterations,
            handle_parsing_errors=True,
            return_intermediate_steps=True
        )

        print(f"✅ 真正的LangChain Agent初始化成功")
        print(f"   提供商: {provider}")
        print(f"   模型: {model}")
        print(f"   工具数: {len(self.tools)}")
        print(f"   框架: LangChain 1.0.2")

    def _create_llm(self):
        """创建LLM实例"""
        from config import LLM_CONFIGS

        config = LLM_CONFIGS.get(self.provider, {})
        api_key = config.get("api_key")
        api_base = config.get("api_base")

        if not api_key:
            raise ValueError(f"未找到{self.provider}的API密钥")

        # 注意：LangChain 1.0.x 使用 ChatOpenAI
        llm = ChatOpenAI(
            model=self.model,
            api_key=api_key,
            base_url=api_base,  # LangChain 1.0.x 使用 base_url
            temperature=0.0,
            max_tokens=4000,
            timeout=120
        )

        return llm

    def analyze(self, query: str, session_id: Optional[str] = None) -> str:
        """执行分析"""

        print(f"\n{'='*70}")
        print(f"📊 LangChain Agent开始分析: {query}")
        print(f"{'='*70}\n")

        try:
            # 执行Agent
            result = self.agent_executor.invoke({
                "input": query,
                "current_date": datetime.now().strftime("%Y-%m-%d"),
                "tools": "\n".join([f"- {t.name}: {t.description}" for t in self.tools])
            })

            # 提取最终答案
            final_answer = result.get("output", "未生成报告")

            # 统计数据
            steps = result.get("intermediate_steps", [])
            tool_calls = len(steps)

            print(f"\n{'='*70}")
            print(f"✅ LangChain分析完成")
            print(f"{'='*70}")
            print(f"   工具调用次数: {tool_calls}")
            print(f"   报告长度: {len(final_answer.split())} 词")
            print(f"   数据点使用: {tool_calls}")

            return final_answer

        except Exception as e:
            print(f"\n❌ LangChain分析失败: {str(e)}")

            # 如果LangChain失败，回退到原Agent
            print("   ⚠️ 回退到原始Agent...")
            from agent import Agent as FallbackAgent
            fallback = FallbackAgent(self.provider, self.model)
            return fallback.run(query, max_steps=20)

    async def analyze_async(self, query: str, session_id: Optional[str] = None) -> str:
        """异步执行分析"""
        # 简化版本，直接调用同步方法
        return self.analyze(query, session_id)

    def get_agent_info(self) -> Dict[str, Any]:
        """获取Agent信息"""
        return {
            "provider": self.provider,
            "model": self.model,
            "tools_count": len(self.tools),
            "tools": [t.name for t in self.tools],
            "framework": "LangChain 1.0.2 (真实实现)",
            "max_iterations": self.agent_executor.max_iterations
        }

# ============================================
# 兼容性函数
# ============================================

def create_langchain_financial_agent(**kwargs):
    """创建Agent的工厂函数"""
    return LangChainFinancialAgent(**kwargs)

__all__ = [
    "LangChainFinancialAgent",
    "create_langchain_financial_agent"
]