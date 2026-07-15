# -*- coding: utf-8 -*-
"""Agent 身份、职责与产品绑定的单一事实源。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    key: str
    name_zh: str
    short_zh: str
    glyph: str
    color_token: str
    mandate_zh: str
    tools: tuple[str, ...]
    dashboard_tabs: tuple[str, ...] = ()


AGENT_PROFILES: dict[str, AgentProfile] = {
    "price_agent": AgentProfile(
        key="price_agent",
        name_zh="价格行为分析师",
        short_zh="价格",
        glyph="P",
        color_token="t-info",
        mandate_zh="趋势、动量、关键价位、量价确认与价格行为风险",
        tools=(
            "search",
            "get_stock_price",
            "get_stock_historical_data",
            "get_market_benchmark_history",
            "get_relative_strength",
            "analyze_historical_drawdowns",
            "get_performance_comparison",
            "get_option_chain_metrics",
        ),
        dashboard_tabs=("technical", "peers", "overview"),
    ),
    "news_agent": AgentProfile(
        key="news_agent",
        name_zh="舆情新闻分析师",
        short_zh="新闻",
        glyph="N",
        color_token="t-warning",
        mandate_zh="新闻情绪量化、催化事件识别、来源核验与价格传导",
        tools=(
            "search",
            "get_company_news",
            "get_news_sentiment",
            "get_event_calendar",
            "score_news_source_reliability",
        ),
        dashboard_tabs=("news", "overview"),
    ),
    "fundamental_agent": AgentProfile(
        key="fundamental_agent",
        name_zh="基本面分析师",
        short_zh="基本面",
        glyph="F",
        color_token="t-up",
        mandate_zh="增长、盈利质量、现金流、EPS 修正与估值支撑",
        tools=(
            "search",
            "get_financial_statements",
            "get_company_info",
            "get_earnings_estimates",
            "get_eps_revisions",
        ),
        dashboard_tabs=("financial", "peers", "overview"),
    ),
    "technical_agent": AgentProfile(
        key="technical_agent",
        name_zh="技术面分析师",
        short_zh="技术面",
        glyph="T",
        color_token="t-predict",
        mandate_zh="RSI、MACD、均线、形态与交易信号研判",
        tools=(
            "search",
            "get_stock_historical_data",
            "get_stock_price",
            "get_option_chain_metrics",
            "get_market_sentiment",
        ),
        dashboard_tabs=("technical", "overview"),
    ),
    "macro_agent": AgentProfile(
        key="macro_agent",
        name_zh="宏观分析师",
        short_zh="宏观",
        glyph="M",
        color_token="t-accent",
        mandate_zh="通胀、利率、就业、政策与跨资产环境影响",
        tools=(
            "search",
            "get_fred_data",
            "get_official_macro_releases",
            "get_market_sentiment",
            "get_economic_events",
        ),
        dashboard_tabs=("overview",),
    ),
    "risk_agent": AgentProfile(
        key="risk_agent",
        name_zh="风险分析师",
        short_zh="风险",
        glyph="R",
        color_token="t-down",
        mandate_zh="波动率、回撤、因子敞口、压力测试与下行风险",
        tools=(
            "search",
            "get_stock_price",
            "analyze_historical_drawdowns",
            "get_factor_exposure",
            "run_portfolio_stress_test",
        ),
        dashboard_tabs=("peers", "overview"),
    ),
    "deep_search_agent": AgentProfile(
        key="deep_search_agent",
        name_zh="深度研究员",
        short_zh="深搜",
        glyph="D",
        color_token="t-text-2",
        mandate_zh="研报、监管文件与长文档的证据化深度调研",
        tools=("search",),
        dashboard_tabs=(),
    ),
}


def profile(key: str) -> AgentProfile:
    return AGENT_PROFILES[key]


def lead_agent_for_operation(operation: str) -> str:
    """返回业务操作的固定 lead，未知操作由基本面分析师兜底。"""
    name = str(operation or "").strip().lower()
    if name in {"investment_opinion", "generate_report", "report_generation", "compare"}:
        return "fundamental_agent"
    if name == "technical":
        return "technical_agent"
    if name == "price":
        return "price_agent"
    if name in {"fetch", "news_impact", "analyze_impact"}:
        return "news_agent"
    if name.startswith("earnings_"):
        return "fundamental_agent"
    if name.startswith("macro_"):
        return "macro_agent"
    if name.startswith("portfolio_") or name == "rebalance_check":
        return "risk_agent"
    if name == "qa":
        return "deep_search_agent"
    return "fundamental_agent"


__all__ = [
    "AGENT_PROFILES",
    "AgentProfile",
    "lead_agent_for_operation",
    "profile",
]
