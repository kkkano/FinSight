#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangChain 1.0+ 版本的工具模块
使用最新的 @tool 装饰器和 StructuredTool API 重构所有金融数据获取工具
"""

from langchain.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import json

# 导入现有工具的实际实现函数
from tools import (
    get_stock_price as _get_stock_price,
    get_company_news as _get_company_news,
    get_company_info as _get_company_info,
    search as _search,
    get_market_sentiment as _get_market_sentiment,
    get_economic_events as _get_economic_events,
    get_performance_comparison as _get_performance_comparison,
    analyze_historical_drawdowns as _analyze_historical_drawdowns,
    get_current_datetime as _get_current_datetime
)

# ============================================
# Pydantic 输入模型定义 (LangChain 1.0+ 要求)
# ============================================

class StockTickerInput(BaseModel):
    """股票代码输入模型"""
    ticker: str = Field(
        description="股票代码,例如 'AAPL' (苹果), 'NVDA' (英伟达), '^GSPC' (标普500指数)"
    )

class SearchQueryInput(BaseModel):
    """搜索查询输入模型"""
    query: str = Field(
        description="搜索查询字符串,用于查找市场信息、新闻或分析"
    )

class TickerComparisonInput(BaseModel):
    """多股票比较输入模型"""
    tickers: str = Field(
        description="JSON格式的股票代码字典,例如: '{\"Apple\": \"AAPL\", \"NVIDIA\": \"NVDA\"}'"
    )

class EmptyInput(BaseModel):
    """空输入模型(用于不需要参数的工具)"""
    pass

# ============================================
# LangChain 1.0+ 工具定义 (使用 @tool 装饰器)
# ============================================

@tool("get_stock_price", args_schema=StockTickerInput, return_direct=False)
def get_stock_price(ticker: str) -> str:
    """获取股票的实时价格和基本面数据。
    
    这个工具使用多数据源策略(Alpha Vantage → Finnhub → yfinance → 网页抓取)
    来确保数据获取的稳定性和可靠性。
    
    Args:
        ticker: 股票代码,例如 'AAPL', 'TSLA', '^GSPC'
        
    Returns:
        包含当前价格、涨跌幅的详细字符串
    """
    try:
        return _get_stock_price(ticker)
    except Exception as e:
        return f"获取股价失败: {str(e)}"


@tool("get_company_news", args_schema=StockTickerInput, return_direct=False)
def get_company_news(ticker: str) -> str:
    """获取公司或市场指数的最新新闻和市场动态。
    
    对于公司股票,使用API获取新闻;对于市场指数(如^GSPC),使用搜索策略。
    
    Args:
        ticker: 股票代码或指数代码
        
    Returns:
        格式化的新闻摘要,包括标题、来源和日期
    """
    try:
        return _get_company_news(ticker)
    except Exception as e:
        return f"获取新闻失败: {str(e)}"


@tool("get_company_info", args_schema=StockTickerInput, return_direct=False)
def get_company_info(ticker: str) -> str:
    """获取公司的基本信息和财务数据。
    
    包括公司名称、行业、市值、网站、业务描述等信息。
    
    Args:
        ticker: 股票代码
        
    Returns:
        公司基本信息和关键财务指标
    """
    try:
        return _get_company_info(ticker)
    except Exception as e:
        return f"获取公司信息失败: {str(e)}"


@tool("search", args_schema=SearchQueryInput, return_direct=False)
def search(query: str) -> str:
    """使用DuckDuckGo搜索引擎获取市场信息和分析。
    
    适用于查找宏观市场趋势、经济事件、分析报告等内容。
    
    Args:
        query: 搜索查询字符串
        
    Returns:
        搜索结果摘要,包括标题、摘要和链接
    """
    try:
        return _search(query)
    except Exception as e:
        return f"搜索失败: {str(e)}"


@tool("get_market_sentiment", args_schema=EmptyInput, return_direct=False)
def get_market_sentiment() -> str:
    """获取当前市场情绪指标。
    
    返回CNN恐惧贪婪指数(Fear & Greed Index),范围0-100:
    - 0-25: 极度恐惧
    - 25-45: 恐惧
    - 45-55: 中性
    - 55-75: 贪婪
    - 75-100: 极度贪婪
    
    Returns:
        当前市场情绪指数和评级
    """
    try:
        return _get_market_sentiment()
    except Exception as e:
        return f"获取市场情绪失败: {str(e)}"


@tool("get_economic_events", args_schema=EmptyInput, return_direct=False)
def get_economic_events() -> str:
    """获取即将到来的重要经济事件和数据发布。
    
    包括FOMC会议、CPI数据、就业报告等关键经济指标的发布时间。
    
    Returns:
        即将发布的经济数据和事件时间表
    """
    try:
        return _get_economic_events()
    except Exception as e:
        return f"获取经济事件失败: {str(e)}"


@tool("get_performance_comparison", args_schema=TickerComparisonInput, return_direct=False)
def get_performance_comparison(tickers: str) -> str:
    """获取多只股票的表现对比分析。
    
    比较年初至今(YTD)和1年期的收益表现。
    
    Args:
        tickers: JSON格式的股票代码字典,例如 '{"Apple": "AAPL", "Microsoft": "MSFT"}'
        
    Returns:
        表格化的表现对比数据
    """
    try:
        # 解析JSON字符串为字典
        ticker_dict = json.loads(tickers)
        return _get_performance_comparison(ticker_dict)
    except json.JSONDecodeError:
        return "错误: tickers 参数必须是有效的JSON格式"
    except Exception as e:
        return f"获取表现对比失败: {str(e)}"


@tool("analyze_historical_drawdowns", args_schema=StockTickerInput, return_direct=False)
def analyze_historical_drawdowns(ticker: str) -> str:
    """分析历史最大回撤和恢复情况。
    
    分析过去20年的最大回撤事件,包括:
    - 回撤幅度
    - 回撤持续时间
    - 恢复到峰值所需时间
    
    Args:
        ticker: 股票代码或指数代码
        
    Returns:
        历史前3大回撤事件的详细分析
    """
    try:
        return _analyze_historical_drawdowns(ticker)
    except Exception as e:
        return f"回撤分析失败: {str(e)}"


@tool("get_current_datetime", args_schema=EmptyInput, return_direct=False)
def get_current_datetime() -> str:
    """获取当前日期和时间。
    
    用于确保分析报告使用正确的时间戳,必须在分析开始时调用。
    
    Returns:
        格式化的当前时间戳(YYYY-MM-DD HH:MM:SS)
    """
    try:
        return _get_current_datetime()
    except Exception as e:
        return f"获取时间失败: {str(e)}"


# ============================================
# 工具集合和辅助函数
# ============================================

# 所有可用工具的列表
FINANCIAL_TOOLS = [
    get_current_datetime,      # 优先级最高 - 必须首先调用
    get_stock_price,
    get_company_info,
    get_company_news,
    search,
    get_market_sentiment,
    get_economic_events,
    get_performance_comparison,
    analyze_historical_drawdowns,
]

def get_tool_names() -> list[str]:
    """获取所有工具的名称列表"""
    return [tool.name for tool in FINANCIAL_TOOLS]


def get_tools_description() -> str:
    """获取所有工具的详细描述"""
    descriptions = []
    for i, tool in enumerate(FINANCIAL_TOOLS, 1):
        descriptions.append(f"{i}. **{tool.name}**: {tool.description}")
    return "\n".join(descriptions)


def get_tool_by_name(name: str) -> Optional[Any]:
    """根据名称获取工具对象"""
    for tool in FINANCIAL_TOOLS:
        if tool.name == name:
            return tool
    return None


# ============================================
# 导出的主要接口
# ============================================

__all__ = [
    'FINANCIAL_TOOLS',
    'get_tool_names',
    'get_tools_description',
    'get_tool_by_name',
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
