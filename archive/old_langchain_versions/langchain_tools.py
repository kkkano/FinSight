#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangChain版本的工具模块
使用最新的@tool装饰器重构所有金融数据获取工具
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential
from concurrent.futures import ThreadPoolExecutor

# 导入现有工具的实际实现函数
from tools import (
    get_stock_price, get_company_news, get_company_info,
    search, get_market_sentiment, get_economic_events,
    get_performance_comparison, analyze_historical_drawdowns, get_current_datetime
)

# ============================================
# Pydantic输入模型定义
# ============================================

class TickerInput(BaseModel):
    """股票代码输入模型"""
    ticker: str = Field(description="股票代码，例如 'AAPL', 'NVDA', '^GSPC'")

class SearchInput(BaseModel):
    """搜索查询输入模型"""
    query: str = Field(description="搜索查询字符串")

class ComparisonInput(BaseModel):
    """比较分析输入模型"""
    tickers: Dict[str, str] = Field(description="股票代码字典，例如 {'Name': 'TICK'}")

class DateInput(BaseModel):
    """日期输入模型（无参数）"""
    pass

# ============================================
# LangChain工具定义
# ============================================

@tool(args_schema=TickerInput)
def get_stock_price(input_data: TickerInput) -> str:
    """获取股票实时价格和基本面数据

    Args:
        input_data: 包含股票代码的输入参数

    Returns:
        详细的价格信息和基本面数据
    """
    try:
        return get_stock_price(input_data.ticker)
    except Exception as e:
        return f"获取股价失败: {str(e)}"

@tool(args_schema=TickerInput)
def get_company_news(input_data: TickerInput) -> str:
    """获取公司最新新闻和市场动态

    Args:
        input_data: 包含股票代码的输入参数

    Returns:
        格式化的新闻摘要
    """
    try:
        return get_company_news(input_data.ticker)
    except Exception as e:
        return f"获取新闻失败: {str(e)}"

@tool(args_schema=TickerInput)
def get_company_info(input_data: TickerInput) -> str:
    """获取公司基本信息和财务数据

    Args:
        input_data: 包含股票代码的输入参数

    Returns:
        公司基本信息和财务指标
    """
    try:
        return get_company_info(input_data.ticker)
    except Exception as e:
        return f"获取公司信息失败: {str(e)}"

@tool(args_schema=SearchInput)
def search(input_data: SearchInput) -> str:
    """使用搜索引擎获取市场信息

    Args:
        input_data: 包含搜索查询的输入参数

    Returns:
        搜索结果摘要
    """
    try:
        return search(input_data.query)
    except Exception as e:
        return f"搜索失败: {str(e)}"

@tool(args_schema=DateInput)
def get_market_sentiment(input_data: DateInput) -> str:
    """获取当前市场情绪指标

    Returns:
        CNN恐惧贪婪指数等市场情绪数据
    """
    try:
        return get_market_sentiment()
    except Exception as e:
        return f"获取市场情绪失败: {str(e)}"

@tool(args_schema=DateInput)
def get_economic_events(input_data: DateInput) -> str:
    """获取即将到来的重要经济事件

    Returns:
        即将发布的经济数据和时间表
    """
    try:
        return get_economic_events()
    except Exception as e:
        return f"获取经济事件失败: {str(e)}"

@tool(args_schema=ComparisonInput)
def get_performance_comparison(input_data: ComparisonInput) -> str:
    """获取多只股票的表现对比

    Args:
        input_data: 包含股票代码字典的输入参数

    Returns:
        表格化的表现对比数据
    """
    try:
        return get_performance_comparison(input_data.tickers)
    except Exception as e:
        return f"获取表现对比失败: {str(e)}"

@tool(args_schema=TickerInput)
def analyze_historical_drawdowns(input_data: TickerInput) -> str:
    """分析历史最大回撤和恢复情况

    Args:
        input_data: 包含股票代码的输入参数

    Returns:
        历史回撤分析和恢复时间统计
    """
    try:
        return analyze_historical_drawdowns(input_data.ticker)
    except Exception as e:
        return f"回撤分析失败: {str(e)}"

@tool(args_schema=DateInput)
def get_current_datetime(input_data: DateInput) -> str:
    """获取当前日期和时间

    Returns:
        格式化的当前时间戳
    """
    try:
        return get_current_datetime()
    except Exception as e:
        return f"获取时间失败: {str(e)}"

# ============================================
# 工具集合
# ============================================

FINANCIAL_TOOLS = [
    get_stock_price,
    get_company_news,
    get_company_info,
    search,
    get_market_sentiment,
    get_economic_events,
    get_performance_comparison,
    analyze_historical_drawdowns,
    get_current_datetime,
]

# 工具名称映射，便于查找
TOOL_NAMES = {tool.name: tool for tool in FINANCIAL_TOOLS}

def get_tool_by_name(tool_name: str) -> Optional[Any]:
    """根据工具名称获取工具对象"""
    return TOOL_NAMES.get(tool_name)

def get_tool_descriptions() -> str:
    """获取所有工具的描述信息"""
    descriptions = []
    for tool in FINANCIAL_TOOLS:
        descriptions.append(f"- {tool.name}: {tool.description}")
    return "\n".join(descriptions)

# ============================================
# 异步工具支持
# ============================================

async def async_tool_execution(tool_func, *args, **kwargs):
    """异步执行工具函数"""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(executor, tool_func, *args, **kwargs)

class AsyncFinancialTools:
    """异步金融工具类"""

    def __init__(self):
        self.tools = FINANCIAL_TOOLS

    async def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """异步执行指定工具"""
        tool = get_tool_by_name(tool_name)
        if not tool:
            return f"未找到工具: {tool_name}"

        try:
            # 创建输入对象
            if hasattr(tool, 'args_schema') and tool.args_schema:
                input_obj = tool.args_schema(**tool_input)
                result = await async_tool_execution(tool.func, input_obj)
            else:
                result = await async_tool_execution(tool.func, tool_input)

            return result
        except Exception as e:
            return f"工具执行失败: {str(e)}"

    def get_available_tools(self) -> List[str]:
        """获取可用工具列表"""
        return [tool.name for tool in self.tools]

# ============================================
# 重试机制增强
# ============================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def robust_tool_execution(tool_func, *args, **kwargs):
    """带重试机制的工具执行"""
    return tool_func(*args, **kwargs)

class RobustFinancialTools:
    """带错误恢复的金融工具类"""

    @staticmethod
    def safe_execute(tool_name: str, tool_input: Dict[str, Any]) -> str:
        """安全执行工具，包含错误处理和重试"""
        tool = get_tool_by_name(tool_name)
        if not tool:
            return f"未找到工具: {tool_name}"

        try:
            if hasattr(tool, 'args_schema') and tool.args_schema:
                input_obj = tool.args_schema(**tool_input)
                result = robust_tool_execution(tool.func, input_obj)
            else:
                result = robust_tool_execution(tool.func, tool_input)

            return result
        except Exception as e:
            return f"工具执行失败（已重试）: {str(e)}"

# ============================================
# 导出的主要接口
# ============================================

__all__ = [
    'FINANCIAL_TOOLS',
    'get_tool_by_name',
    'get_tool_descriptions',
    'AsyncFinancialTools',
    'RobustFinancialTools',
    'get_stock_price',
    'get_company_news',
    'get_company_info',
    'search',
    'get_market_sentiment',
    'get_economic_events',
    'get_performance_comparison',
    'analyze_historical_drawdowns',
    'get_current_datetime',
]