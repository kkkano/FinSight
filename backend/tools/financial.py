import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote

import requests
import yfinance as yf

from .env import ALPHA_VANTAGE_API_KEY, OPENFIGI_API_KEY, EODHD_API_KEY
from .http import _http_get, _http_post

logger = logging.getLogger(__name__)

def get_financial_statements(ticker: str) -> dict:
    """
    获取公司的财务报表数据（财报）
    包括：损益表、资产负债表、现金流量表
    
    Args:
        ticker: 股票代码
        
    Returns:
        dict: 包含 financials, balance_sheet, cashflow 的字典
    """
    try:
        stock = yf.Ticker(ticker)
        
        result = {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'financials': None,
            'balance_sheet': None,
            'cashflow': None,
            'error': None
        }
        
        # 1. 获取损益表（Income Statement）
        try:
            financials = stock.financials
            if not financials.empty:
                # 转换为字典格式，便于JSON序列化
                result['financials'] = {
                    'columns': financials.columns.tolist(),
                    'index': financials.index.tolist(),
                    'data': financials.to_dict('records')
                }
                logger.info(f"[Financials] ✅ 成功获取 {ticker} 损益表数据")
        except Exception as e:
            logger.info(f"[Financials] 获取损益表失败: {e}")
            result['error'] = f"获取损益表失败: {str(e)}"
        
        # 2. 获取资产负债表（Balance Sheet）
        try:
            balance_sheet = stock.balance_sheet
            if not balance_sheet.empty:
                result['balance_sheet'] = {
                    'columns': balance_sheet.columns.tolist(),
                    'index': balance_sheet.index.tolist(),
                    'data': balance_sheet.to_dict('records')
                }
                logger.info(f"[Financials] ✅ 成功获取 {ticker} 资产负债表数据")
        except Exception as e:
            logger.info(f"[Financials] 获取资产负债表失败: {e}")
            if not result['error']:
                result['error'] = f"获取资产负债表失败: {str(e)}"
        
        # 3. 获取现金流量表（Cash Flow）
        try:
            cashflow = stock.cashflow
            if not cashflow.empty:
                result['cashflow'] = {
                    'columns': cashflow.columns.tolist(),
                    'index': cashflow.index.tolist(),
                    'data': cashflow.to_dict('records')
                }
                logger.info(f"[Financials] ✅ 成功获取 {ticker} 现金流量表数据")
        except Exception as e:
            logger.info(f"[Financials] 获取现金流量表失败: {e}")
            if not result['error']:
                result['error'] = f"获取现金流量表失败: {str(e)}"
        
        # 如果所有数据都获取失败，返回错误
        if not result['financials'] and not result['balance_sheet'] and not result['cashflow']:
            result['error'] = "无法获取任何财报数据，请检查股票代码是否正确"
        
        return result
        
    except Exception as e:
        logger.info(f"[Financials] 获取财报数据失败: {e}")
        return {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'financials': None,
            'balance_sheet': None,
            'cashflow': None,
            'error': f"获取财报数据失败: {str(e)}"
        }


def get_financial_statements_summary(ticker: str) -> str:
    """
    获取财报数据并格式化为可读的文本摘要
    
    Args:
        ticker: 股票代码
        
    Returns:
        str: 格式化的财报摘要文本
    """
    data = get_financial_statements(ticker)
    
    if data.get('error'):
        return f"无法获取 {ticker} 的财报数据: {data['error']}"
    
    summary_parts = [f"📊 {ticker} 财务报表摘要\n"]
    summary_parts.append("=" * 50 + "\n")
    
    # 损益表摘要
    if data.get('financials'):
        financials = data['financials']
        summary_parts.append("\n📈 损益表 (Income Statement):\n")
        summary_parts.append("-" * 50 + "\n")
        
        # 获取最新年份的数据
        if financials.get('columns') and len(financials['columns']) > 0:
            latest_year = financials['columns'][0]
            summary_parts.append(f"最新财报日期: {latest_year}\n\n")
            
            # 显示关键指标
            key_metrics = ['Total Revenue', 'Net Income', 'Operating Income', 'EBIT', 'Gross Profit']
            for metric in key_metrics:
                # 在 index 中查找
                if financials.get('index'):
                    for idx, row_name in enumerate(financials['index']):
                        if metric.lower() in str(row_name).lower():
                            # 从 data 中获取值
                            if financials.get('data') and len(financials['data']) > idx:
                                value = financials['data'][idx].get(latest_year, 'N/A')
                                if value != 'N/A' and value is not None:
                                    formatted_value = f"${value/1e9:.2f}B" if abs(value) >= 1e9 else f"${value/1e6:.2f}M"
                                    summary_parts.append(f"  {row_name}: {formatted_value}\n")
    
    # 资产负债表摘要
    if data.get('balance_sheet'):
        balance_sheet = data['balance_sheet']
        summary_parts.append("\n💰 资产负债表 (Balance Sheet):\n")
        summary_parts.append("-" * 50 + "\n")
        
        if balance_sheet.get('columns') and len(balance_sheet['columns']) > 0:
            latest_year = balance_sheet['columns'][0]
            summary_parts.append(f"最新财报日期: {latest_year}\n\n")
            
            key_metrics = ['Total Assets', 'Total Liabilities', 'Total Stockholder Equity', 'Cash And Cash Equivalents']
            for metric in key_metrics:
                if balance_sheet.get('index'):
                    for idx, row_name in enumerate(balance_sheet['index']):
                        if metric.lower() in str(row_name).lower():
                            if balance_sheet.get('data') and len(balance_sheet['data']) > idx:
                                value = balance_sheet['data'][idx].get(latest_year, 'N/A')
                                if value != 'N/A' and value is not None:
                                    formatted_value = f"${value/1e9:.2f}B" if abs(value) >= 1e9 else f"${value/1e6:.2f}M"
                                    summary_parts.append(f"  {row_name}: {formatted_value}\n")
    
    # 现金流量表摘要
    if data.get('cashflow'):
        cashflow = data['cashflow']
        summary_parts.append("\n💵 现金流量表 (Cash Flow):\n")
        summary_parts.append("-" * 50 + "\n")
        
        if cashflow.get('columns') and len(cashflow['columns']) > 0:
            latest_year = cashflow['columns'][0]
            summary_parts.append(f"最新财报日期: {latest_year}\n\n")
            
            key_metrics = ['Operating Cash Flow', 'Free Cash Flow', 'Capital Expenditure']
            for metric in key_metrics:
                if cashflow.get('index'):
                    for idx, row_name in enumerate(cashflow['index']):
                        if metric.lower() in str(row_name).lower():
                            if cashflow.get('data') and len(cashflow['data']) > idx:
                                value = cashflow['data'][idx].get(latest_year, 'N/A')
                                if value != 'N/A' and value is not None:
                                    formatted_value = f"${value/1e9:.2f}B" if abs(value) >= 1e9 else f"${value/1e6:.2f}M"
                                    summary_parts.append(f"  {row_name}: {formatted_value}\n")
    
    return "".join(summary_parts)


def get_company_info(ticker: str) -> str:
    """
    从多个来源获取公司资料信息。
    优先使用 yfinance，失败时回退到 Finnhub, Alpha Vantage 或网页搜索。
    """
    # 方法1: yfinance
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        if info and 'longName' in info:
            summary = info.get('longBusinessSummary', '')
            description = (summary[:200] + '...') if summary else 'No description available'
            return f"""Company Profile ({ticker}):
- Name: {info.get('longName', 'Unknown')}
- Sector: {info.get('sector', 'Unknown')}
- Industry: {info.get('industry', 'Unknown')}
- Market Cap: ${info.get('marketCap', 0):,.0f}
- Website: {info.get('website', 'N/A')}
- Description: {description}"""
    except Exception as e:
        logger.info(f"yfinance info fetch for '{ticker}' failed: {e}")

    # 方法2: Finnhub (新增)
    if finnhub_client:
        try:
            logger.info(f"Trying Finnhub for company info: {ticker}")
            profile = finnhub_client.company_profile2(symbol=ticker)
            if profile and 'name' in profile:
                return f"""Company Profile ({ticker}):
- Name: {profile.get('name', 'Unknown')}
- Sector: {profile.get('finnhubIndustry', 'Unknown')}
- Market Cap: ${int(profile.get('marketCapitalization', 0) * 1_000_000):,}
- Website: {profile.get('weburl', 'N/A')}
- Description: Search online for more details.""" # Finnhub profile doesn't include a long description
        except Exception as e:
            logger.info(f"Finnhub profile fetch failed: {e}")
    
    # 方法3: Alpha Vantage
    try:
        logger.info(f"Trying Alpha Vantage for company info: {ticker}")
        url = "https://www.alphavantage.co/query"
        params = {'function': 'OVERVIEW', 'symbol': ticker, 'apikey': ALPHA_VANTAGE_API_KEY}
        response = _http_get(url, params=params, timeout=10)
        data = response.json()
        if 'Symbol' in data and data['Symbol']:
            description = data.get('Description', 'No description')[:200] + '...'
            return f"""Company Profile ({ticker}):
- Name: {data.get('Name', 'Unknown')}
- Sector: {data.get('Sector', 'Unknown')}
- Industry: {data.get('Industry', 'Unknown')}
- Market Cap: ${int(data.get('MarketCapitalization', 0)):,}
- Description: {description}"""
    except Exception as e:
        logger.info(f"Alpha Vantage overview fetch failed: {e}")
    
    # 方法4: 网页搜索
    logger.info(f"Falling back to web search for '{ticker}' company info")
    return search(f"{ticker} company profile stock information")

# ============================================
# 新闻获取
# ============================================


def resolve_company_ticker(company: str, limit: int = 5) -> Dict[str, Any]:
    """Resolve a company name to tickers using OpenFIGI/Finnhub/EODHD/search."""
    if not company:
        return {"query": company, "source": "none", "matches": []}

    matches: List[Dict[str, Any]] = []
    sources: List[str] = []
    seen = set()

    def _append_matches(items: List[Dict[str, Any]], source: str) -> None:
        if not items:
            return
        if source not in sources:
            sources.append(source)
        for item in items:
            symbol = item.get("symbol") if isinstance(item, dict) else None
            if not symbol or symbol in seen:
                continue
            matches.append(item)
            seen.add(symbol)
            if len(matches) >= limit:
                return

    if OPENFIGI_API_KEY:
        try:
            _append_matches(_openfigi_symbol_lookup(company, limit), "openfigi")
        except Exception as e:
            logger.info(f"OpenFIGI lookup failed for {company}: {e}")

    if len(matches) < limit and finnhub_client:
        try:
            lookup = finnhub_client.symbol_lookup(company)
            results = lookup.get("result", []) if isinstance(lookup, dict) else []
            finnhub_matches = []
            for item in results:
                symbol = item.get("displaySymbol") or item.get("symbol")
                if not symbol:
                    continue
                finnhub_matches.append({
                    "symbol": symbol,
                    "description": item.get("description") or "",
                    "type": item.get("type") or "",
                    "primaryExchange": item.get("primaryExchange") or item.get("exchange") or "",
                    "source": "finnhub",
                })
            _append_matches(finnhub_matches, "finnhub")
        except Exception as e:
            logger.info(f"Finnhub symbol lookup failed for {company}: {e}")

    if len(matches) < limit and EODHD_API_KEY:
        try:
            _append_matches(_eodhd_symbol_lookup(company, limit), "eodhd")
        except Exception as e:
            logger.info(f"EODHD lookup failed for {company}: {e}")

    if len(matches) < limit:
        try:
            text = search(f"{company} ticker symbol")
            pattern = r"\b[A-Z]{1,5}(?:[.-][A-Z]{1,4})?\b"
            symbols = []
            for symbol in re.findall(pattern, text or ""):
                if symbol not in symbols:
                    symbols.append(symbol)
            search_matches = [
                {"symbol": sym, "description": "", "type": "search", "primaryExchange": "", "source": "search"}
                for sym in symbols[:limit]
            ]
            _append_matches(search_matches, "search")
        except Exception as e:
            logger.info(f"Search fallback for ticker lookup failed: {e}")

    source_label = "+".join(sources) if sources else "error"
    return {"query": company, "source": source_label, "matches": matches[:limit]}



def _openfigi_symbol_lookup(company: str, limit: int = 5) -> List[Dict[str, Any]]:
    if not OPENFIGI_API_KEY:
        return []
    url = "https://api.openfigi.com/v3/search"
    headers = {"X-OPENFIGI-APIKEY": OPENFIGI_API_KEY}
    payload = {"query": company, "limit": max(limit, 5)}
    resp = _http_post(url, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("data", []) if isinstance(data, dict) else []
    matches: List[Dict[str, Any]] = []
    for item in results:
        symbol = item.get("ticker")
        if not symbol:
            continue
        exchange = item.get("exchCode") or item.get("mic") or ""
        desc = item.get("name") or item.get("securityDescription") or ""
        matches.append({
            "symbol": symbol,
            "description": desc,
            "type": item.get("securityType") or item.get("marketSecDes") or "",
            "primaryExchange": exchange,
            "source": "openfigi",
        })
    return matches



def _eodhd_symbol_lookup(company: str, limit: int = 5) -> List[Dict[str, Any]]:
    if not EODHD_API_KEY:
        return []
    url = f"https://eodhd.com/api/search/{quote(company)}"
    params = {"api_token": EODHD_API_KEY, "fmt": "json"}
    resp = _http_get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    matches: List[Dict[str, Any]] = []
    for item in data[: max(limit, 5)]:
        symbol = item.get("Code") or item.get("code")
        exchange = item.get("Exchange") or item.get("exchange") or ""
        if symbol and exchange and "." not in symbol:
            symbol = f"{symbol}.{exchange}"
        if not symbol:
            continue
        matches.append({
            "symbol": symbol,
            "description": item.get("Name") or item.get("name") or "",
            "type": item.get("Type") or item.get("type") or "",
            "primaryExchange": exchange,
            "source": "eodhd",
        })
    return matches
