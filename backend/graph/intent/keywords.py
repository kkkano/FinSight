# -*- coding: utf-8 -*-
"""意图关键词唯一家（WP2 Task 2 / ORC-12）。

全部词条自 backend/graph/nodes/understand_request.py 逐字搬运，未增删改任何词条。
注意：conversation_router.py 的判定函数内还存在一批**内联** token 集合（如
_query_explicitly_requests_technical 的 technical_tokens），与本表语义重叠但内容已漂移；
为保证零行为变更，本任务不做合并——统一收敛计划在 WP2 Task 3 的意图管线重排中执行。
"""
from __future__ import annotations

import re


_INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "VTI", "^IXIC", "^DJI", "^GSPC", "^RUT", "^VIX"}
_NON_ASSET_TOKENS = {
    "PDF", "DOC", "DOCX", "PPT", "PPTX", "CSV", "TXT", "HTML", "URL",
    "IV", "PCR", "RSI", "MACD",
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF",
}
_NEWS_HINTS = ("新闻", "消息", "大新闻", "发生什么", "快讯", "news", "headline", "latest")
_PRICE_HINTS = ("价格", "股价", "涨了多少", "跌了多少", "涨幅", "跌幅", "表现", "行情", "price", "quote", "performance")
_IMPACT_HINTS = ("影响", "冲击", "拖累", "风险", "利好", "利空", "impact", "affect", "risk")
_TECHNICAL_HINTS = ("技术面", "技术分析", "k线", "均线", "macd", "rsi", "technical")
_VALUATION_CONCEPT_HINTS = ("估值", "valuation", "p/e", "pe", "p/s", "ps")
_VALUATION_JUDGMENT_HINTS = ("贵", "便宜", "合理", "匹配", "增长", "growth", "expensive", "cheap", "overvalued", "undervalued")
_ROUTER_GENERIC_COMPANY_OPERATIONS = {"price", "fetch", "qa", "daily_brief", "analyze_impact", "news_impact"}
_ROUTER_SPECIFIC_COMPANY_OPERATIONS = {
    "earnings_impact",
    "earnings_performance",
    "valuation_sanity",
    "investment_opinion",
    "technical",
}
_COMPARE_HINTS = ("对比", "比较", "相比", "vs", "versus", "谁更强", "哪个好", "哪个", "compare")
_REPORT_PEER_CONTEXT_HINTS = (
    "覆盖",
    "包括",
    "结合",
    "竞争",
    "竞品",
    "对手",
    "同业",
    "competitive",
    "competitor",
    "peer",
    "cover",
)
_ALERT_HINTS = ("提醒", "预警", "到达", "触及", "涨到", "跌到", "跌破", "突破", "低于", "高于", "alert", "notify", "remind me")
_PORTFOLIO_HINTS = ("持仓", "组合", "仓位", "调仓", "portfolio", "holdings", "rebalance")
_HOLDINGS_HINTS = (
    "13f",
    "form 4",
    "form4",
    "insider",
    "institutional holdings",
    "superinvestor",
    "buffett",
    "berkshire",
    "名义持仓",
    "机构持仓",
    "名人持仓",
    "内部人交易",
    "增持",
    "减持",
    "加仓",
    "巴菲特",
    "伯克希尔",
)
_PRIVATE_INSIDER_INFO_HINTS = (
    "insider information",
    "inside information",
    "material nonpublic",
    "mnpi",
    "内幕消息",
    "内幕信息",
    "未公开重大信息",
)
_PUBLIC_INSIDER_DISCLOSURE_HINTS = (
    "form 4",
    "form4",
    "insider transaction",
    "insider transactions",
    "insider 买卖",
    "内部人交易",
)
_MACRO_HINTS = (
    "美联储", "联储", "降息", "加息", "利率", "fomc", "fed", "cpi", "ppi", "通胀",
    "国债", "收益率", "宏观", "大盘", "纳指", "公告", "大型科技股", "科技股估值", "market",
)
_THEME_HINTS = ("半导体", "芯片", "ai", "人工智能", "大型科技股", "科技股")
_FALLBACK_HINTS = ("如果不知道", "不知道就", "没持仓就", "没有持仓就", "按等权", "按大型科技股", "fallback")
_LIGHTWEIGHT_COMPARE_HINTS = ("如果不知道", "不知道就", "按", "代表", "先别长篇", "别长篇", "不要长篇", "简单说", "短一点")
# P2 (2026-05-03) — vague subject deixis: when the user says "this stock"
# without naming it AND ui_context.active_symbol is present, do a transparent
# weak fallback (bind active_symbol + warn user it can be corrected).
# Risk: a wrong fallback is corrected by one user message; a missed fallback
# costs an extra clarify round-trip. We bias toward the cheaper failure mode.
_VAGUE_SUBJECT_HINTS = (
    "这只票", "这个票", "那只票", "这只股", "这个股", "那只股",
    "这家公司", "那家公司", "这家", "那家",
    "它", "他", "那它", "那他",
    "这只", "这个", "这支",
    "刚才那个", "刚才说的", "之前那个",
    "this stock", "that stock", "this one", "the company",
)
_ASSET_DEICTIC_HINTS = (
    "这只票", "这个票", "那只票", "这只股", "这个股", "那只股",
    "这家公司", "那家公司", "this stock", "that stock", "the company",
)
_SOCIAL_PREFIX_RE = re.compile(r"^\s*(你好|您好|早|早上好|嗨|哈喽|hello|hi)[，,。\s]*(今天天气不错[，,。\s]*)?", re.IGNORECASE)
_GLOBAL_CHAT_VIEWS = {"chat", "main", "global", "conversation"}
_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)
_FORBIDDEN_DIRECT_REPLY_MARKERS = (
    "本轮问题包含",
    "分析对象：",
    "问题：",
)
_RESEARCH_CONFIRMATION_ASK_TERMS = (
    "你希望",
    "是否",
    "要不要",
    "需要我",
    "我可以",
    "如果你希望",
    "would you like",
    "do you want",
    "should i",
)
_RESEARCH_CONFIRMATION_ACTION_TERMS = (
    "启动研究",
    "开始研究",
    "进入研究",
    "研究链路",
    "研究模式",
    "拉取最新",
    "获取最新",
    "最新实时",
    "start research",
    "research mode",
)


_THEME_HINTS = (*_THEME_HINTS, "semiconductor", "semiconductors", "sector", "chips")
