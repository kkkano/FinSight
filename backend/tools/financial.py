import json
import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote

import requests
import yfinance as yf

from .env import ALPHA_VANTAGE_API_KEY, OPENFIGI_API_KEY, EODHD_API_KEY, finnhub_client
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
            'error': None,
            'warnings': [],
        }

        def _to_payload(table: Any) -> dict | None:
            if table is None:
                return None
            try:
                if table.empty:
                    return None
            except Exception:
                return None

            columns = [str(col) for col in table.columns.tolist()]
            index = [str(idx) for idx in table.index.tolist()]
            return {
                'columns': columns,
                'index': index,
                'data': table.to_dict('records'),
            }

        def _fetch_with_fallbacks(table_label: str, attr_candidates: list[str]) -> dict | None:
            for attr in attr_candidates:
                try:
                    table = getattr(stock, attr)
                    payload = _to_payload(table)
                    if payload:
                        logger.info(f"[Financials] ✅ 成功获取 {ticker} {table_label} 数据 ({attr})")
                        return payload
                except Exception as exc:
                    msg = f"{table_label}:{attr}:{exc}"
                    result['warnings'].append(msg)
                    logger.info(f"[Financials] 获取 {table_label} 失败 ({attr}): {exc}")
            return None

        result['financials'] = _fetch_with_fallbacks(
            '损益表',
            ['financials', 'income_stmt', 'quarterly_financials', 'quarterly_income_stmt'],
        )
        result['balance_sheet'] = _fetch_with_fallbacks(
            '资产负债表',
            ['balance_sheet', 'quarterly_balance_sheet'],
        )
        result['cashflow'] = _fetch_with_fallbacks(
            '现金流量表',
            ['cashflow', 'quarterly_cashflow'],
        )

        if not result['financials'] and not result['balance_sheet'] and not result['cashflow']:
            result['error'] = "无法获取任何财报数据，请检查股票代码是否正确"
        else:
            # 只要拿到任意一张主表，就不把局部失败升级为全局 error
            result['error'] = None

        return result

    except Exception as e:
        logger.info(f"[Financials] 获取财报数据失败: {e}")
        return {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'financials': None,
            'balance_sheet': None,
            'cashflow': None,
            'error': f"获取财报数据失败: {str(e)}",
            'warnings': [str(e)],
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


def _serialize_table_records(table: Any, *, max_rows: int = 8) -> List[Dict[str, Any]]:
    if table is None:
        return []
    try:
        if getattr(table, "empty", True):
            return []
        frame = table.reset_index()
    except Exception:
        return []

    if frame is None or frame.empty:
        return []

    first_col = frame.columns[0]
    frame = frame.rename(columns={first_col: "period"})

    records: List[Dict[str, Any]] = []
    for _, row in frame.head(max_rows).iterrows():
        item: Dict[str, Any] = {}
        for column in frame.columns:
            value = row[column]
            if hasattr(value, "isoformat"):
                try:
                    item[str(column)] = value.isoformat()
                    continue
                except Exception:
                    pass
            if value is None:
                item[str(column)] = None
                continue
            try:
                if isinstance(value, (int, float)):
                    item[str(column)] = float(value)
                else:
                    item[str(column)] = str(value)
            except Exception:
                item[str(column)] = str(value)
        records.append(item)
    return records


def _serialize_calendar_payload(calendar_payload: Any) -> Dict[str, Any]:
    if not isinstance(calendar_payload, dict):
        return {}

    result: Dict[str, Any] = {}
    for key, value in calendar_payload.items():
        key_text = str(key)
        if isinstance(value, list):
            serialized_list: List[Any] = []
            for item in value:
                if hasattr(item, "isoformat"):
                    try:
                        serialized_list.append(item.isoformat())
                        continue
                    except Exception:
                        pass
                serialized_list.append(str(item))
            result[key_text] = serialized_list
            continue

        if hasattr(value, "isoformat"):
            try:
                result[key_text] = value.isoformat()
                continue
            except Exception:
                pass

        if isinstance(value, (int, float)):
            result[key_text] = float(value)
        elif value is None:
            result[key_text] = None
        else:
            result[key_text] = str(value)
    return result


def _infer_revision_signal(eps_revisions: List[Dict[str, Any]]) -> str:
    if not eps_revisions:
        return "unknown"

    score = 0.0
    for row in eps_revisions:
        if not isinstance(row, dict):
            continue
        up_7 = float(row.get("upLast7days") or 0.0)
        up_30 = float(row.get("upLast30days") or 0.0)
        down_7 = float(row.get("downLast7Days") or 0.0)
        down_30 = float(row.get("downLast30days") or 0.0)
        score += up_7 + up_30 - down_7 - down_30

    if score >= 6:
        return "positive"
    if score <= -6:
        return "negative"
    return "neutral"


def get_earnings_estimates(ticker: str) -> Dict[str, Any]:
    """
    Get forward earnings estimates and EPS revision trends from free yfinance.
    """
    result: Dict[str, Any] = {
        "ticker": str(ticker or "").upper(),
        "source": "yfinance",
        "as_of": datetime.now().isoformat(),
        "earnings_estimate": [],
        "eps_trend": [],
        "eps_revisions": [],
        "calendar": {},
        "revision_signal": "unknown",
        "error": None,
    }

    if not ticker:
        result["error"] = "ticker_required"
        return result

    try:
        stock = yf.Ticker(ticker)

        result["earnings_estimate"] = _serialize_table_records(getattr(stock, "earnings_estimate", None), max_rows=8)
        result["eps_trend"] = _serialize_table_records(getattr(stock, "eps_trend", None), max_rows=8)
        result["eps_revisions"] = _serialize_table_records(getattr(stock, "eps_revisions", None), max_rows=8)
        result["calendar"] = _serialize_calendar_payload(getattr(stock, "calendar", None))
        result["revision_signal"] = _infer_revision_signal(result["eps_revisions"])

        if (
            not result["earnings_estimate"]
            and not result["eps_trend"]
            and not result["eps_revisions"]
            and not result["calendar"]
        ):
            result["error"] = "no_earnings_estimate_data"
        return result
    except Exception as e:
        logger.info(f"[EarningsEstimates] fetch failed for {ticker}: {e}")
        result["error"] = f"fetch_failed: {e.__class__.__name__}"
        return result


def get_eps_revisions(ticker: str) -> Dict[str, Any]:
    """
    Lightweight wrapper focused on EPS revision data.
    """
    payload = get_earnings_estimates(ticker)
    return {
        "ticker": payload.get("ticker"),
        "source": payload.get("source"),
        "as_of": payload.get("as_of"),
        "eps_revisions": payload.get("eps_revisions") if isinstance(payload.get("eps_revisions"), list) else [],
        "eps_trend": payload.get("eps_trend") if isinstance(payload.get("eps_trend"), list) else [],
        "revision_signal": payload.get("revision_signal", "unknown"),
        "error": payload.get("error"),
    }

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
