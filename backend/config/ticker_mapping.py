# -*- coding: utf-8 -*-
"""
Centralized Ticker Mapping and Extraction
Shared by IntentClassifier and ConversationRouter
"""

import re
from typing import Dict, List, Any

# Stock ticker to company name mapping
COMPANY_MAP: Dict[str, str] = {
    # US Tech
    'AAPL': 'Apple', 'apple': 'AAPL',
    'GOOGL': 'Google', 'google': 'GOOGL', 'alphabet': 'GOOGL',
    'GOOG': 'Google',
    'MSFT': 'Microsoft', 'microsoft': 'MSFT',
    'AMZN': 'Amazon', 'amazon': 'AMZN',
    'META': 'Meta', 'facebook': 'META',
    'TSLA': 'Tesla', 'tesla': 'TSLA',
    'NVDA': 'NVIDIA', 'nvidia': 'NVDA',
    'AMD': 'AMD',
    'INTC': 'Intel', 'intel': 'INTC',
    'NFLX': 'Netflix', 'netflix': 'NFLX',
    'CRM': 'Salesforce', 'salesforce': 'CRM',
    # Chinese ADRs
    'BABA': 'Alibaba', 'alibaba': 'BABA',
    'JD': 'JD.com', 'jd': 'JD',
    'PDD': 'Pinduoduo', 'pinduoduo': 'PDD',
    'BIDU': 'Baidu', 'baidu': 'BIDU',
    'NIO': 'NIO', 'nio': 'NIO',
    'XPEV': 'XPeng', 'xpeng': 'XPEV',
    'LI': 'Li Auto', 'li auto': 'LI',
    # ETFs
    'SPY': 'S&P 500 ETF',
    'QQQ': 'Nasdaq 100 ETF',
    'DIA': 'Dow Jones ETF',
    'IWM': 'Russell 2000 ETF',
    'VTI': 'Total Stock Market ETF',
}

# Chinese name to ticker mapping
CN_TO_TICKER: Dict[str, str] = {
    '苹果': 'AAPL', '谷歌': 'GOOGL', '微软': 'MSFT',
    '亚马逊': 'AMZN', '特斯拉': 'TSLA', '英伟达': 'NVDA',
    '阿里巴巴': 'BABA', '阿里': 'BABA', '京东': 'JD',
    '拼多多': 'PDD', '百度': 'BIDU', '英特尔': 'INTC',
    '蔚来': 'NIO', '小鹏': 'XPEV', '理想': 'LI',
    '凯捷': 'CAP.PA', '奈飞': 'NFLX', '脸书': 'META',
    # Market indices
    '纳斯达克': '^IXIC', '纳斯达克指数': '^IXIC', '纳指': '^IXIC',
    '道琼斯': '^DJI', '道琼斯指数': '^DJI', '道指': '^DJI',
    '标普500': '^GSPC', '标普': '^GSPC', 'S&P 500': '^GSPC', 'sp500': '^GSPC',
    '罗素2000': '^RUT', 'VIX': '^VIX', '恐慌指数': '^VIX',
    '纽交所': '^NYA', '纽交所指数': '^NYA',
    '富时100': '^FTSE', '日经225': '^N225', '恒生指数': '^HSI',
    # Commodities
    '黄金': 'GC=F', '金价': 'GC=F', 'gold': 'GC=F',
    '白银': 'SI=F', '银价': 'SI=F', 'silver': 'SI=F',
    '原油': 'CL=F', '油价': 'CL=F', 'crude oil': 'CL=F', 'oil': 'CL=F',
    # A-shares indices
    '沪深300': '000300.SS', '沪深三百': '000300.SS', 'csi300': '000300.SS',
    '上证指数': '000001.SS', '上证': '000001.SS', '上证综指': '000001.SS',
    '深证成指': '399001.SZ', '深证': '399001.SZ',
    '创业板': '399006.SZ', '创业板指': '399006.SZ',
}

# Market index aliases
INDEX_ALIASES: Dict[str, str] = {
    # Nasdaq
    '纳斯达克': '^IXIC', '纳斯达克指数': '^IXIC', '纳指': '^IXIC',
    'nasdaq': '^IXIC', 'nasdaq composite': '^IXIC',
    # Dow Jones
    '道琼斯': '^DJI', '道琼斯指数': '^DJI', '道指': '^DJI',
    'dow jones': '^DJI', 'dow': '^DJI',
    # S&P 500
    '标普500': '^GSPC', '标普': '^GSPC', 'S&P 500': '^GSPC',
    'sp500': '^GSPC', 'sp 500': '^GSPC', '标准普尔500': '^GSPC',
    # Others
    '罗素2000': '^RUT', 'russell 2000': '^RUT',
    'VIX': '^VIX', '恐慌指数': '^VIX', 'vix指数': '^VIX',
    '纽交所': '^NYA', '纽交所指数': '^NYA', 'nyse': '^NYA',
}

# Known valid tickers (skip common word filtering)
KNOWN_TICKERS = {
    'AAPL', 'GOOGL', 'GOOG', 'MSFT', 'AMZN', 'META', 'TSLA', 'NVDA', 'AMD', 'INTC',
    'NFLX', 'CRM', 'BABA', 'JD', 'PDD', 'BIDU', 'NIO', 'XPEV', 'LI',
    'SPY', 'QQQ', 'DIA', 'IWM', 'VTI'
}

# Common words to filter out (not tickers)
COMMON_WORDS = {
    'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS', 'PE', 'EPS', 'MACD', 'RSI', 'KDJ',
    'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HAD', 'HER', 'WAS', 'ONE', 'OUR', 'OUT',
    'HAS', 'HIS', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO', 'BOY', 'DID', 'GET', 'HIM',
    'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'DAY', 'BIG', 'HIGH', 'LOW', 'UP', 'DOWN', 'IN', 'ON', 'AT',
    'IS', 'IT', 'OF', 'TO', 'AS', 'BE', 'BY', 'DO', 'GO', 'IF', 'ME', 'MY', 'NO', 'OR', 'SO', 'WE',
    'BUY', 'SELL', 'HOLD', 'LONG', 'SHORT', 'CALL', 'BULL', 'BEAR', 'RISK', 'GAIN', 'LOSS', 'CASH',
    'BOND', 'FUND', 'LOAN', 'DEBT', 'RATE', 'TERM', 'YEAR', 'WEEK', 'MONTH', 'PRICE', 'VALUE', 'COST',
    'NEWS', 'INFO', 'DATA', 'CHART', 'TREND', 'STOCK', 'SHARE', 'TRADE', 'ORDER', 'LIMIT', 'STOP',
    'WHAT', 'WHEN', 'WHERE', 'WHY', 'WHICH', 'ABOUT', 'SHOW', 'TELL', 'GIVE', 'FIND', 'LOOK', 'HELP',
    'GOLD', 'OIL',
}


def is_probably_ticker(ticker: str) -> bool:
    if not ticker:
        return False
    if ticker in COMMON_WORDS:
        return False
    if ticker.startswith("^"):
        return True
    if len(ticker) > 8:
        return False
    return bool(re.match(r"^[A-Z0-9]{1,6}([.-][A-Z0-9]{1,4})?$", ticker))


def extract_tickers(query: str) -> Dict[str, Any]:
    """
    Extract tickers and company names from query

    Returns:
        Dict with keys: tickers, company_names, company_mentions, is_comparison
    """
    metadata = {
        'tickers': [],
        'company_names': [],
        'company_mentions': [],
        'is_comparison': False
    }

    query_lower = query.lower()
    query_original = query

    # Check for comparison query
    comparison_keywords = ['对比', '比较', 'vs', 'versus', '区别', '差异', 'compare']
    if any(kw in query_lower for kw in comparison_keywords):
        metadata['is_comparison'] = True

    # 1. Match market indices (longest match first)
    sorted_aliases = sorted(INDEX_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        pattern = re.compile(re.escape(alias), re.IGNORECASE)
        if pattern.search(query_original):
            ticker = INDEX_ALIASES[alias]
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
                metadata['company_names'].append(alias)

    # 2. Match English tickers
    potential_tickers = re.findall(r'(?<![A-Za-z])([A-Za-z]{2,5})(?![A-Za-z])', query)
    index_tickers = re.findall(r'(\^[A-Za-z]{3,})', query)
    potential_tickers.extend(index_tickers)
    dotted_tickers = re.findall(r'(?<![A-Za-z])([A-Za-z]{1,5}[.-][A-Za-z]{1,4})(?![A-Za-z])', query)
    potential_tickers.extend(dotted_tickers)
    potential_tickers = [t.upper() for t in potential_tickers]

    for ticker in potential_tickers:
        if not is_probably_ticker(ticker):
            continue
        if ticker in KNOWN_TICKERS or ticker.startswith('^'):
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
        elif ticker.lower() in COMPANY_MAP:
            real_ticker = COMPANY_MAP.get(ticker.lower())
            if real_ticker and real_ticker not in metadata['tickers']:
                metadata['tickers'].append(real_ticker)
        else:
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)

    # 3. Match Chinese company names
    sorted_cn_names = sorted(CN_TO_TICKER.keys(), key=len, reverse=True)
    for cn_name in sorted_cn_names:
        if cn_name in query_original:
            ticker = CN_TO_TICKER[cn_name]
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
                metadata['company_names'].append(cn_name)

    # 4. Match English company names (full names)
    for name, ticker in COMPANY_MAP.items():
        if len(name) > 4 and name.lower() in query_lower:
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
                metadata['company_names'].append(name)

    return metadata
