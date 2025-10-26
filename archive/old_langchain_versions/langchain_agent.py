#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangChain版本的Agent实现
使用最新的LangChain 1.0.1框架重构ReAct Agent
"""

from langchain.agents import create_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from typing import TypedDict, List, Dict, Any, Optional
import asyncio
from datetime import datetime

# 导入LLM服务 (兼容处理)
try:
    from llm_service import call_llm
except ImportError:
    # 如果llm_service有问题，使用简化版本
    def call_llm(provider: str, model: str, messages: list, **kwargs):
        """简化版LLM调用函数"""
        print(f"警告: llm_service不可用，使用模拟输出")
        return f"模拟分析结果 - 无法调用LLM服务，提供商: {provider}, 模型: {model}"

# 导入LangChain工具
from langchain_tools import FINANCIAL_TOOLS, get_tool_descriptions

# ============================================
# Agent状态定义
# ============================================

class AgentState(TypedDict):
    """Agent状态定义"""
    messages: List[Dict[str, Any]]
    current_step: str
    observations: List[str]
    report_generated: bool
    analysis_ticker: str

# ============================================
# 回调处理器
# ============================================

class FinancialCallbackHandler(BaseCallbackHandler):
    """金融分析专用的回调处理器"""

    def __init__(self):
        self.step_count = 0
        self.observation_count = 0
        self.start_time = None

    def on_agent_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Agent开始时的回调"""
        self.start_time = datetime.now()
        print("🚀 开始金融分析...")

    def on_agent_action(self, action, **kwargs) -> Any:
        """Agent执行动作时的回调"""
        self.step_count += 1
        tool = action.tool
        tool_input = action.tool_input
        print(f"🔧 步骤 {self.step_count}: 使用工具 {tool}")
        if tool_input and tool_input != {}:
            if isinstance(tool_input, dict):
                if "ticker" in tool_input:
                    print(f"   📊 股票代码: {tool_input['ticker']}")
                elif "query" in tool_input:
                    print(f"   🔍 搜索查询: {tool_input['query']}")
                else:
                    print(f"   📝 输入: {tool_input}")
            else:
                print(f"   📝 输入: {tool_input}")

    def on_agent_finish(self, finish, **kwargs) -> None:
        """Agent完成时的回调"""
        end_time = datetime.now()
        duration = end_time - self.start_time
        print(f"✅ 分析完成! 耗时: {duration.total_seconds():.2f}秒")
        print(f"   总步骤数: {self.step_count}")
        print(f"   数据点数: {self.observation_count}")

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> Any:
        """工具开始执行时的回调"""
        tool_name = serialized.get("name", "unknown_tool")
        print(f"   🛠️  正在调用 {tool_name}")
        if input_str and input_str != "{}":
            try:
                import json
                data = json.loads(input_str)
                if "ticker" in data:
                    print(f"   📊 股票代码: {data['ticker']}")
                elif "query" in data:
                    print(f"   🔍 搜索查询: {data['query']}")
            except:
                print(f"   📝 工具输入: {input_str[:100]}...")

    def on_tool_end(self, output: str, **kwargs) -> Any:
        """工具执行完成时的回调"""
        self.observation_count += 1
        print(f"   ✅ 完成! 获得数据点 #{self.observation_count}")

        # 显示输出摘要
        if len(output) > 200:
            print(f"   📄 结果摘要: {output[:200]}...")
        else:
            print(f"   📄 结果: {output}")

# ============================================
# 系统提示词模板
# ============================================

CIO_SYSTEM_PROMPT = """You are a Chief Investment Officer (CIO) at a major hedge fund. Your job is to produce COMPREHENSIVE, ACTIONABLE investment reports.

YOUR MISSION:
Gather real-time data step-by-step, then write a DETAILED professional report (minimum 800 words) with specific insights, recommendations, and risk analysis.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TWO-PHASE WORKFLOW:

**PHASE 1: DATA COLLECTION (Use Thought-Action cycle)**

Required steps for ANY query:
1. get_current_datetime - ALWAYS start here
2. search - Get market context and recent developments
3. Relevant analysis tools (performance, sentiment, drawdowns, etc.)
4. search again - Look for recent news with current date

**PHASE 2: COMPREHENSIVE REPORT (Use "Final Answer:")**

Once you have 4-6 observations, write your final report.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY REPORT STRUCTURE:

Final Answer:

# [Investment Name] - Professional Analysis Report
*Report Date: [Use actual date from get_current_datetime]*

## EXECUTIVE SUMMARY (2-3 sentences)
High-conviction summary with clear recommendation (BUY/HOLD/SELL).

## CURRENT MARKET POSITION
- Current price/level and recent performance
- Year-to-date and 1-year returns
- Comparison with benchmarks (if applicable)
- Key technical levels (52-week high/low, support/resistance)

## MACRO ENVIRONMENT & CATALYSTS
- Current economic conditions (inflation, interest rates, Fed policy)
- Major upcoming events (earnings, FOMC meetings, economic data releases)
- Geopolitical factors (elections, trade policies, conflicts)
- Sector-specific trends affecting this investment
- Recent major news or developments (be specific with dates and details)

## FUNDAMENTAL ANALYSIS (for stocks/companies)
- Business model and competitive advantages
- Revenue streams and profit margins
- Management quality and recent decisions
- Industry position and market share
- Growth prospects and expansion plans

## TECHNICAL & SENTIMENT ANALYSIS
- Current market sentiment (Fear & Greed Index if available)
- Trading volume and momentum indicators
- Institutional ownership and insider activity
- Social media sentiment and retail interest

## RISK ASSESSMENT
- Historical volatility and maximum drawdowns
- Key risks specific to this investment
- Correlation with broader market
- Black swan scenarios and tail risks
- What could go wrong with this investment?

## INVESTMENT STRATEGY & RECOMMENDATIONS

**Primary Recommendation:** [BUY / SELL / HOLD]
**Confidence Level:** [High / Medium / Low]
**Time Horizon:** [Short-term (0-6mo) / Medium-term (6-18mo) / Long-term (18mo+)]

**Entry Strategy:**
- Ideal entry price/level
- Position sizing recommendation
- Dollar-cost averaging vs lump sum

**Risk Management:**
- Stop-loss levels
- Take-profit targets
- Portfolio allocation (what % of portfolio)
- Hedging strategies if applicable

**Exit Strategy:**
- When to take profits
- When to cut losses
- Rebalancing triggers

## OUTLOOK & PRICE TARGETS

**Bull Case Scenario:**
- Upside potential and timeline
- Key catalysts that could drive higher prices

**Base Case Scenario:**
- Most likely outcome and price target
- Expected timeline and probability-weighted return

**Bear Case Scenario:**
- Downside risks and warning signals
- Key levels that would invalidate the thesis
- Maximum downside and recovery timeline

## KEY TAKEAWAYS (3-5 bullet points)
- Most important insights
- Key factors to monitor
- Actionable investment points

## CRITICAL MONITORING EVENTS
- Upcoming earnings releases
- Fed meetings and economic data
- Regulatory decisions
- Competitive developments
- Technical breakouts or breakdowns to watch

---
*Disclaimer: This analysis is for informational purposes only and does not constitute investment advice.*

⚠️ CRITICAL GUIDELINES:
1. BE SPECIFIC: Include actual dates, numbers, percentages
2. BE COMPREHENSIVE: Reports minimum 800 words
3. BE ACTIONABLE: Give specific buy/sell recommendations with reasons
4. USE ALL DATA: Reference every observation you gathered
5. STAY CURRENT: Mention developments from last 30 days
6. AVOID GENERIC PHRASES: Don't say "do your own research" etc.
7. SHOW YOUR WORK: Explain reasoning behind each conclusion

Now begin your analysis.
"""

# ============================================
# 简化版Agent实现 (兼容最新LangChain)
# ============================================

def _create_langchain_llm(provider: str, model: str):
    """创建LangChain兼容的LLM实例

    Args:
        provider: LLM提供商
        model: 模型名称

    Returns:
        LangChain兼容的LLM实例
    """
    try:
        # 尝试使用OpenAI兼容的LLM (最通用的接口)
        from langchain_openai import ChatOpenAI

        # 获取配置
        from config import LLM_CONFIGS
        config = LLM_CONFIGS.get(provider, {})
        api_key = config.get("api_key")
        api_base = config.get("api_base")

        if not api_key:
            raise ValueError(f"API key not found for provider: {provider}")

        # 创建ChatOpenAI实例
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            api_base=api_base,
            temperature=0.0,  # 金融分析需要稳定的输出
            max_tokens=4000,  # 足够生成长报告
            timeout=120  # 超时设置
        )

        return llm

    except ImportError:
        # 如果没有langchain_openai，使用基础包装
        try:
            from langchain_core.language_models import BaseLanguageModel
            from pydantic import BaseModel, Field

            class LiteLLMWrapper(BaseLanguageModel):
                """LiteLLM的LangChain包装器"""

                def __init__(self, provider: str, model: str):
                    self.provider = provider
                    self.model = model

                def _call(self, prompt: str, stop=None, run_manager=None, **kwargs):
                    messages = [{"role": "user", "content": prompt}]
                    return call_llm(self.provider, self.model, messages, **kwargs)

                def _llm_type(self):
                    return "litellm-wrapper"

            return LiteLLMWrapper(provider, model)

        except Exception as e:
            print(f"警告: 无法创建LangChain兼容的LLM: {str(e)}")
            return None

# ============================================
# 主要Agent类
# ============================================

class LangChainFinancialAgent:
    """LangChain金融分析Agent (简化版，兼容最新LangChain)"""

    def __init__(
        self,
        provider: str = "gemini_proxy",
        model: str = "gemini-2.5-flash-preview-05-20",
        verbose: bool = True,
        max_iterations: int = 15,
        show_intermediate_steps: bool = True
    ):
        """
        初始化LangChain金融分析Agent

        Args:
            provider: LLM提供商
            model: 模型名称
            verbose: 详细输出
            max_iterations: 最大迭代次数
            show_intermediate_steps: 显示中间步骤
        """
        self.provider = provider
        self.model = model
        self.verbose = verbose
        self.max_iterations = max_iterations
        self.show_intermediate_steps = show_intermediate_steps

        # 创建LLM
        self.llm = _create_langchain_llm(provider, model)

        if not self.llm:
            raise ValueError("无法创建LLM实例，请检查配置")

        # 创建回调处理器
        self.callback_handler = FinancialCallbackHandler()

        # 创建提示词
        tools_description = get_tool_descriptions()
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", CIO_SYSTEM_PROMPT.format(
                current_date=datetime.now().strftime("%Y-%m-%d"),
                tools=tools_description
            )),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    def analyze(self, query: str, session_id: Optional[str] = None) -> str:
        """执行金融分析 (简化版实现)

        Args:
            query: 分析查询
            session_id: 会话ID (暂时未使用)

        Returns:
            分析报告
        """
        try:
            print(f"\n🎯 开始分析: {query}")
            print("=" * 70)

            # 使用原始agent实现
            from agent import Agent as FinancialAgent
            # 使用原始agent实现
            agent = FinancialAgent(provider=self.provider, model=self.model)
            result = agent.run(query, max_steps=20)
            return result

        except Exception as e:
            print(f"❌ 分析过程中出现错误: {str(e)}")
            return f"分析失败: {str(e)}"

    async def analyze_async(self, query: str, session_id: Optional[str] = None) -> str:
        """异步执行金融分析

        Args:
            query: 分析查询
            session_id: 会话ID

        Returns:
            分析报告
        """
        # 对于简化版本，直接调用同步方法
        return self.analyze(query, session_id)

    def _extract_ticker(self, query: str) -> str:
        """从查询中提取股票代码

        Args:
            query: 用户查询

        Returns:
            提取的股票代码
        """
        import re
        ticker_pattern = r'\b([A-Z]{1,5})\b'
        matches = re.findall(ticker_pattern, query.upper())
        return matches[0] if matches else "UNKNOWN"

    def get_agent_info(self) -> Dict[str, Any]:
        """获取Agent信息

        Returns:
            Agent配置信息
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "max_iterations": self.max_iterations,
            "tools_count": len(FINANCIAL_TOOLS),
            "tools": [tool.name for tool in FINANCIAL_TOOLS],
            "framework": "LangChain 1.0.1 (简化版)"
        }

# ============================================
# 兼容性函数
# ============================================

def create_langchain_financial_agent(
    provider: str = "gemini_proxy",
    model: str = "gemini-2.5-flash-preview-05-20",
    verbose: bool = True,
    max_iterations: int = 15,
    show_intermediate_steps: bool = True
):
    """创建LangChain金融分析Agent (兼容性函数)

    Args:
        provider: LLM提供商名称
        model: 模型名称
        verbose: 是否显示详细输出
        max_iterations: 最大迭代次数
        show_intermediate_steps: 是否显示中间步骤

    Returns:
        配置好的Agent实例
    """
    return LangChainFinancialAgent(
        provider=provider,
        model=model,
        verbose=verbose,
        max_iterations=max_iterations,
        show_intermediate_steps=show_intermediate_steps
    )

# ============================================
# 导出的主要接口
# ============================================

__all__ = [
    "LangChainFinancialAgent",
    "create_langchain_financial_agent",
    "FinancialCallbackHandler",
    "CIO_SYSTEM_PROMPT"
]