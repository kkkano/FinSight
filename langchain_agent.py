#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangChain 1.0+ 版本的 Agent 实现
使用最新的 create_agent API（基于 LangGraph）重构 ReAct Agent
"""

from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from typing import Any, Dict, List, Optional
from datetime import datetime
import os
from dotenv import load_dotenv

# 导入重构后的工具
from langchain_tools import FINANCIAL_TOOLS, get_tools_description

# 加载环境变量
load_dotenv()

# ============================================
# 系统提示词
# ============================================

CIO_SYSTEM_PROMPT = """You are a Chief Investment Officer (CIO) at a major hedge fund. Your job is to produce COMPREHENSIVE, ACTIONABLE investment reports.

CURRENT DATE: {current_date}

YOU HAVE ACCESS TO THE FOLLOWING TOOLS:

{tools}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT WORKFLOW - FOLLOW THIS EXACTLY:

**PHASE 1: DATA COLLECTION (4-6 steps minimum)**

MANDATORY STEPS (in this order):
1. Get current date/time using get_current_datetime
2. Search for market context
3. Get specific data for the investment (price, info, news)
4. Get market sentiment if relevant
5. Additional analysis as needed

**PHASE 2: COMPREHENSIVE REPORT**

After collecting enough data, write your final report with:

# [Investment Name] - Professional Analysis Report
*Report Date: [Actual date from tool]*

## EXECUTIVE SUMMARY
High-conviction summary with clear recommendation (BUY/HOLD/SELL).

## CURRENT MARKET POSITION
- Current price and recent performance
- YTD and 1-year returns  
- Key technical levels

## MACRO ENVIRONMENT & CATALYSTS
- Economic conditions
- Upcoming events
- Recent developments

## RISK ASSESSMENT
- Key risks and scenarios
- Historical volatility

## INVESTMENT STRATEGY & RECOMMENDATIONS

**Primary Recommendation:** [BUY / SELL / HOLD]
**Confidence Level:** [High / Medium / Low]

**Entry Strategy** and **Risk Management** details

## KEY TAKEAWAYS
- 3-5 actionable bullet points

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL RULES:
1. ALWAYS start with get_current_datetime
2. Collect 4-6 observations before final answer
3. Reports MUST be 800+ words
4. Include specific numbers, dates, and prices
5. NO generic advice

Begin your analysis now."""

# ============================================
# 回调处理器
# ============================================

class FinancialAnalysisCallback(BaseCallbackHandler):
    """金融分析专用回调处理器"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.step_count = 0
        self.tool_calls = []
        self.start_time = None
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> Any:
        """当工具开始执行时"""
        self.step_count += 1
        if self.verbose:
            tool_name = serialized.get("name", "unknown")
            print(f"\n[Step {self.step_count}] {tool_name}")
            if input_str and input_str != "{}":
                preview = input_str[:100] + "..." if len(input_str) > 100 else input_str
                print(f"   Input: {preview}")
    
    def on_tool_end(self, output: str, **kwargs) -> Any:
        """当工具执行完成时"""
        if self.verbose:
            # 处理 output 可能不是字符串的情况
            output_str = str(output) if not isinstance(output, str) else output
            preview = output_str[:150] + "..." if len(output_str) > 150 else output_str
            print(f"   Result: {preview}")
    
    def on_tool_error(self, error: Exception, **kwargs) -> Any:
        """当工具执行出错时"""
        if self.verbose:
            print(f"   Error: {str(error)}")

# ============================================
# LangChain Financial Agent 类
# ============================================

class LangChainFinancialAgent:
    """
    LangChain 1.0+ 金融分析 Agent
    使用最新的 create_agent API（基于 LangGraph）
    """
    
    def __init__(
        self,
        provider: str = "gemini_proxy",
        model: str = "gemini-2.5-flash-preview-05-20",
        verbose: bool = True,
        max_iterations: int = 20,
    ):
        """
        初始化 LangChain Financial Agent
        
        Args:
            provider: LLM 提供商
            model: 模型名称
            verbose: 是否显示详细输出
            max_iterations: 最大迭代次数
        """
        self.provider = provider
        self.model = model
        self.verbose = verbose
        self.max_iterations = max_iterations
        
        # 初始化 LLM
        self.llm = self._create_llm()
        
        # 创建系统提示词
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tools_desc = get_tools_description()
        self.system_prompt = CIO_SYSTEM_PROMPT.format(
            current_date=current_date,
            tools=tools_desc
        )
        
        # 创建回调
        self.callback = FinancialAnalysisCallback(verbose=verbose)
        
        # 创建 Agent（使用 LangGraph）
        self.agent = create_agent(
            model=self.llm,
            tools=FINANCIAL_TOOLS,
            system_prompt=self.system_prompt,  # 系统提示词
        )
    
    def _create_llm(self) -> ChatOpenAI:
        """创建 LLM 实例"""
        api_key = os.getenv("GEMINI_PROXY_API_KEY")
        api_base = os.getenv("GEMINI_PROXY_API_BASE", "https://x666.me/v1")
        
        if not api_key:
            raise ValueError("未找到 GEMINI_PROXY_API_KEY 环境变量")
        
        llm = ChatOpenAI(
            model=self.model,
            openai_api_key=api_key,
            openai_api_base=api_base,
            temperature=0.0,
            max_tokens=4000,
            request_timeout=120,
        )
        
        return llm
    
    def analyze(self, query: str) -> Dict[str, Any]:
        """
        执行金融分析
        
        Args:
            query: 分析查询
            
        Returns:
            包含分析结果的字典
        """
        print(f"\n{'='*70}")
        print(f"[Analysis Start] {query}")
        print(f"{'='*70}\n")
        
        self.callback.start_time = datetime.now()
        
        try:
            # 使用 LangGraph Agent 执行
            result = self.agent.invoke(
                {"messages": [HumanMessage(content=query)]},
                config={"callbacks": [self.callback]}
            )
            
            # 提取最后的 AI 消息作为输出
            messages = result.get("messages", [])
            if messages:
                last_message = messages[-1]
                output = last_message.content if hasattr(last_message, 'content') else str(last_message)
            else:
                output = "No output generated"
            
            return {
                "success": True,
                "output": output,
                "messages": messages,
                "step_count": self.callback.step_count,
            }
        
        except Exception as e:
            print(f"\n[ERROR] Analysis failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "step_count": self.callback.step_count,
            }
    
    def get_agent_info(self) -> Dict[str, Any]:
        """获取 Agent 配置信息"""
        return {
            "framework": "LangChain 1.0+ (LangGraph)",
            "provider": self.provider,
            "model": self.model,
            "max_iterations": self.max_iterations,
            "tools_count": len(FINANCIAL_TOOLS),
            "tools": [tool.name for tool in FINANCIAL_TOOLS],
        }

# ============================================
# 便捷函数
# ============================================

def create_financial_agent(
    provider: str = "gemini_proxy",
    model: str = "gemini-2.5-flash-preview-05-20",
    verbose: bool = True,
    max_iterations: int = 20,
) -> LangChainFinancialAgent:
    """
    创建金融分析 Agent 的便捷函数
    
    Args:
        provider: LLM 提供商
        model: 模型名称
        verbose: 是否显示详细输出
        max_iterations: 最大迭代次数
        
    Returns:
        配置好的 Agent 实例
    """
    return LangChainFinancialAgent(
        provider=provider,
        model=model,
        verbose=verbose,
        max_iterations=max_iterations
    )

# ============================================
# 导出的主要接口
# ============================================

__all__ = [
    'LangChainFinancialAgent',
    'create_financial_agent',
    'FinancialAnalysisCallback',
]

