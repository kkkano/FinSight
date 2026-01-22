import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any, Union
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from .env import (
    ALPHA_VANTAGE_API_KEY,
    FINNHUB_API_KEY,
    IEX_CLOUD_API_KEY,
    MASSIVE_API_KEY,
    MARKETSTACK_API_KEY,
    TIINGO_API_KEY,
    TWELVE_DATA_API_KEY,
    finnhub_client,
)
from .http import _http_get
from .search import search

logger = logging.getLogger(__name__)

def _fetch_with_alpha_vantage(ticker: str):
    """优先方案：使用 Alpha Vantage API 获取实时股价"""
    logger.info(f"  - Attempting Alpha Vantage API for {ticker}...")
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'GLOBAL_QUOTE',
            'symbol': ticker,
            'apikey': ALPHA_VANTAGE_API_KEY
        }
        response = _http_get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'Global Quote' in data and data['Global Quote']:
            quote = data['Global Quote']
            price = float(quote.get('05. price', 0))
            change = float(quote.get('09. change', 0))
            change_percent_str = quote.get('10. change percent', '0%').replace('%', '')
            
            if price > 0 and change_percent_str:
                change_percent = float(change_percent_str)
                return f"{ticker} Current Price: ${price:.2f} | Change: ${change:.2f} ({change_percent:+.2f}%)"
        
        if 'Note' in data or 'Information' in data:
            logger.info(f"  - Alpha Vantage note: {data.get('Note') or data.get('Information')}")
        if 'Error Message' in data:
            logger.info(f"  - Alpha Vantage error: {data['Error Message']}")
            
        return None
    except Exception as e:
        logger.info(f"  - Alpha Vantage exception: {e}")
        return None


def _fetch_with_finnhub(ticker: str):
    """新增：使用 Finnhub API 获取实时股价"""
    if not finnhub_client:
        return None
    logger.info(f"  - Attempting Finnhub API for {ticker}...")
    try:
        quote = finnhub_client.quote(ticker)
        if quote and quote.get('c') is not None and quote.get('c') != 0:
            price = quote['c']
            change = quote.get('d', 0.0)
            change_percent = quote.get('dp', 0.0)
            return f"{ticker} Current Price: ${price:.2f} | Change: ${change:.2f} ({change_percent:+.2f}%)"
        return None
    except Exception as e:
        logger.info(f"  - Finnhub quote exception: {e}")
        return None


def _fetch_with_yfinance(ticker: str):
    """尝试使用 yfinance 获取价格"""
    logger.info(f"  - Attempting yfinance for {ticker}...")
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty or len(hist) < 2:
            return None
        
        current_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        change = current_price - prev_close
        change_percent = (change / prev_close) * 100
        
        return f"{ticker} Current Price: ${current_price:.2f} | Change: ${change:.2f} ({change_percent:+.2f}%)"
    except Exception as e:
        logger.info(f"  - yfinance exception: {e}")
        return None



def _fetch_with_twelve_data_price(ticker: str):
    """备用方案：使用 Twelve Data 获取实时价格"""
    if not TWELVE_DATA_API_KEY:
        return None
    logger.info(f"  - Attempting Twelve Data for {ticker}...")
    try:
        params = {
            "symbol": ticker,
            "interval": "1day",
            "outputsize": 2,  # 最新两天计算涨跌幅
            "apikey": TWELVE_DATA_API_KEY,
            "order": "desc",
        }
        response = _http_get("https://api.twelvedata.com/time_series", params=params, timeout=10)
        if response.status_code != 200:
            return None

        data = response.json()
        if data.get("status") != "ok" or not data.get("values"):
            # Twelve Data 返回 {"status": "error", "message": "..."} 时也走兜底
            return None

        values = data.get("values", [])
        latest = values[0] if values else None
        if not latest:
            return None

        price = float(latest.get("close", 0) or 0)
        if price <= 0:
            return None

        prev_close = None
        if len(values) > 1 and values[1].get("close"):
            prev_close = float(values[1]["close"])

        change = None
        change_percent = None
        if prev_close and prev_close != 0:
            change = price - prev_close
            change_percent = (change / prev_close) * 100.0

        msg = f"{ticker} Current Price: ${price:.2f}"
        if change is not None and change_percent is not None:
            msg += f" | Change: {change:+.2f} ({change_percent:+.2f}%)"
        return msg
    except Exception as e:
        logger.info(f"  - Twelve Data price exception: {e}")
        return None


def _fetch_yahoo_api_v8(ticker: str):
    """Yahoo Finance API v8 - 免费 JSON API，无需 API key，比爬虫更稳定"""
    logger.info(f"  - Attempting Yahoo Finance API v8 for {ticker}...")
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = _http_get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        result = data.get('chart', {}).get('result', [])
        if not result:
            return None

        meta = result[0].get('meta', {})
        price = meta.get('regularMarketPrice')
        prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')

        if not price:
            return None

        change = None
        change_percent = None
        if prev_close and prev_close != 0:
            change = price - prev_close
            change_percent = (change / prev_close) * 100.0

        msg = f"{ticker} Current Price: ${price:.2f}"
        if change is not None and change_percent is not None:
            msg += f" | Change: {change:+.2f} ({change_percent:+.2f}%)"
        return msg
    except Exception as e:
        logger.info(f"  - Yahoo API v8 exception: {e}")
        return None



def _scrape_google_finance(ticker: str):
    """Google Finance 爬虫 - 免费，无需 API key"""
    logger.info(f"  - Attempting Google Finance for {ticker}...")
    try:
        # 尝试不同交易所
        exchanges = ['NASDAQ', 'NYSE', 'NYSEARCA', '']
        for exchange in exchanges:
            if exchange:
                url = f"https://www.google.com/finance/quote/{ticker}:{exchange}"
            else:
                url = f"https://www.google.com/finance/quote/{ticker}"

            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = _http_get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                # 解析价格 - Google Finance 使用 data-last-price 属性
                match = re.search(r'data-last-price="([0-9.]+)"', response.text)
                if match:
                    price = float(match.group(1))
                    # 尝试获取变动
                    change_match = re.search(r'data-price-change="([+-]?[0-9.]+)"', response.text)
                    pct_match = re.search(r'data-price-change-percent="([+-]?[0-9.]+)"', response.text)

                    msg = f"{ticker} Current Price: ${price:.2f}"
                    if change_match and pct_match:
                        change = float(change_match.group(1))
                        pct = float(pct_match.group(1))
                        msg += f" | Change: {change:+.2f} ({pct:+.2f}%)"
                    return msg
        return None
    except Exception as e:
        logger.info(f"  - Google Finance exception: {e}")
        return None



def _scrape_cnbc(ticker: str):
    """CNBC 爬虫 - 免费，实时性好"""
    logger.info(f"  - Attempting CNBC for {ticker}...")
    try:
        url = f"https://www.cnbc.com/quotes/{ticker}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = _http_get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # CNBC 在 JSON-LD 中包含价格数据
        match = re.search(r'"price":\s*"?([0-9.]+)"?', response.text)
        if match:
            price = float(match.group(1))
            # 尝试获取变动
            change_match = re.search(r'"priceChange":\s*"?([+-]?[0-9.]+)"?', response.text)
            pct_match = re.search(r'"priceChangePercent":\s*"?([+-]?[0-9.]+)"?', response.text)

            msg = f"{ticker} Current Price: ${price:.2f}"
            if change_match and pct_match:
                change = float(change_match.group(1))
                pct = float(pct_match.group(1))
                msg += f" | Change: {change:+.2f} ({pct:+.2f}%)"
            return msg
        return None
    except Exception as e:
        logger.info(f"  - CNBC exception: {e}")
        return None



def _fetch_with_pandas_datareader(ticker: str):
    """pandas_datareader - 免费，支持多数据源"""
    logger.info(f"  - Attempting pandas_datareader for {ticker}...")
    try:
        import pandas_datareader as pdr
        from datetime import datetime, timedelta

        end = datetime.now()
        start = end - timedelta(days=5)

        # 尝试 stooq 数据源（免费）
        df = pdr.get_data_stooq(ticker, start, end)
        if not df.empty:
            price = df['Close'].iloc[0]
            if len(df) > 1:
                prev = df['Close'].iloc[1]
                change = price - prev
                pct = (change / prev) * 100
                return f"{ticker} Current Price: ${price:.2f} | Change: {change:+.2f} ({pct:+.2f}%)"
            return f"{ticker} Current Price: ${price:.2f}"
        return None
    except ImportError:
        logger.info(f"  - pandas_datareader not installed")
        return None
    except Exception as e:
        logger.info(f"  - pandas_datareader exception: {e}")
        return None


def _scrape_yahoo_finance(ticker: str):
    """备用方案：直接爬取 Yahoo Finance 页面"""
    logger.info(f"  - Attempting to scrape Yahoo Finance for {ticker}...")
    try:
        url = f"https://finance.yahoo.com/quote/{ticker}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = _http_get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        price_elem = soup.find('fin-streamer', {'data-symbol': ticker, 'data-field': 'regularMarketPrice'})
        change_elem = soup.find('fin-streamer', {'data-symbol': ticker, 'data-field': 'regularMarketChange'})
        change_percent_elem = soup.find('fin-streamer', {'data-symbol': ticker, 'data-field': 'regularMarketChangePercent'})
        
        if price_elem and change_elem and change_percent_elem:
            price = price_elem.get('value')
            change = change_elem.get('value')
            change_percent = change_percent_elem.get('value')
            
            if price and change and change_percent:
                return f"{ticker} Current Price: ${float(price):.2f} | Change: ${float(change):.2f} ({float(change_percent)*100:+.2f}%)"
        
        return None
    except Exception as e:
        logger.info(f"  - Yahoo scraping exception: {e}")
        return None



def _fetch_index_price(ticker: str):
    """
    指数专用：优先 yfinance.download 获取最近两日收盘，失败再用 Stooq/搜索兜底。
    """
    if not ticker.startswith('^'):
        return None
    logger.info(f"  - Attempting index price via yfinance.download for {ticker}...")
    try:
        hist = yf.download(ticker, period="3d", interval="1d", progress=False, timeout=20)
        if not hist.empty and len(hist) > 0:
            closes = hist['Close'].dropna().tolist()
            if closes:
                current_price = closes[-1]
                prev_close = closes[-2] if len(closes) > 1 else None
                change = current_price - prev_close if prev_close else None
                change_pct = (change / prev_close) * 100 if prev_close else None
                msg = f"{ticker} Current Price: ${current_price:.2f}"
                if change is not None and change_pct is not None:
                    msg += f" | Change: {change:+.2f} ({change_pct:+.2f}%)"
                return msg
    except Exception as e:
        logger.info(f"  - Index price via yfinance failed: {e}")
    # Fallback 1: Stooq 免费接口
    stooq_result = _fetch_with_stooq_price(ticker)
    if stooq_result:
        return stooq_result
    # Fallback 2: 搜索兜底
    try:
        price_val = _fallback_price_value(ticker)
        if price_val:
            return f"{ticker} Current Price: ${price_val:.2f}"
    except Exception:
        pass
    return None


def _search_for_price(ticker: str):
    """最后手段：使用搜索引擎并用正则表达式解析价格"""
    logger.info(f"  - Attempting to find price via search for {ticker}...")
    try:
        search_result = search(f"{ticker} stock price today")
        patterns = [
            r'\$(\d{1,5}(?:,\d{3})*\.\d{2})',
            r'(?:Price|price)[:\s]+\$?(\d{1,5}(?:,\d{3})*\.\d{2})',
            r'(\d{1,5}(?:,\d{3})*\.\d{2})\s*USD'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, search_result)
            if match:
                price = match.group(1).replace(',', '')
                price_val = float(price)
                if price_val <= 0 or price_val > 1e8:
                    return None
                from datetime import date
                today = date.today().isoformat()
                return f"{ticker} Current Price (via search): ${price_val:.2f} (as of {today})"
        
        return None
    except Exception as e:
        logger.info(f"  - Search price exception: {e}")
        return None


def _fetch_with_stooq_price(ticker: str):
    """
    使用 stooq 免费接口获取最新收盘价（免 Key），支持部分指数和美股。
    """
    try:
        symbol = _map_to_stooq_symbol(ticker)
        if not symbol:
            return None
        url = f"https://stooq.pl/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=json"
        resp = _http_get(url, timeout=8)
        data = resp.json().get("symbols") if resp.status_code == 200 else None
        if not data:
            return None
        item = data[0]
        close = item.get("close")
        open_ = item.get("open")
        if close in (None, "N/D"):
            return None
        price = float(close)
        change = None
        change_percent = None
        if open_ not in (None, "N/D", 0):
            prev = float(open_)
            change = price - prev
            if prev:
                change_percent = (change / prev) * 100.0
        return f"{ticker} Current Price: ${price:.2f}" + (
            f" | Change: {change:+.2f} ({change_percent:+.2f}%)" if change is not None else ""
        )
    except Exception as e:
        logger.info(f"  - Stooq price exception: {e}")
        return None


def get_stock_price(ticker: str) -> str:
    """
    使用多数据源策略获取股票价格，以提高稳定性。
    根据资产类型选择不同的数据源策略。
    """
    logger.info(f"Fetching price for {ticker} with multi-source strategy...")
    upper = ticker.upper()

    # 判断资产类型
    is_index = ticker.startswith('^')
    is_crypto = any(crypto in upper for crypto in ['BTC', 'ETH', 'USDT', 'BNB', 'XRP', 'SOL', 'DOGE', 'ADA']) and '-' in upper
    is_china = upper.endswith('.SS') or upper.endswith('.SZ') or upper.startswith('000') or upper.startswith('600') or upper.startswith('300')
    is_commodity = '=' in upper  # GC=F, CL=F, SI=F

    # 根据资产类型选择数据源
    if is_crypto:
        # 加密货币：只用 yfinance 和搜索
        sources = [
            _fetch_with_yfinance,
            _fetch_yahoo_api_v8,
            _search_for_price
        ]
    elif is_china:
        # A股：只用 yfinance 和搜索（其他源不支持）
        sources = [
            _fetch_with_yfinance,
            _fetch_yahoo_api_v8,
            _search_for_price
        ]
    elif is_commodity:
        # 商品期货：只用 yfinance 和搜索
        sources = [
            _fetch_with_yfinance,
            _fetch_yahoo_api_v8,
            _search_for_price
        ]
    elif is_index:
        sources = [
            _fetch_yahoo_api_v8,
            _fetch_index_price,
            _fetch_with_stooq_price,
            _search_for_price
        ]
    else:
        # 普通美股
        sources = [
            _fetch_yahoo_api_v8,
            _scrape_google_finance,
            _fetch_with_stooq_price,
            _scrape_cnbc,
            _fetch_with_pandas_datareader,
            _fetch_with_yfinance,
            _fetch_with_alpha_vantage,
            _fetch_with_finnhub,
            _fetch_with_twelve_data_price,
            _scrape_yahoo_finance,
            _search_for_price
        ]
    
    for i, source_func in enumerate(sources, 1):
        try:
            result = source_func(ticker)
            if result:
                logger.info(f"  OK source #{i} ({source_func.__name__})")
                # 追加两档分批价，保证有具体数字
                price_num = None
                import re
                m = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", result)
                if m:
                    try:
                        price_num = float(m.group(1))
                    except Exception:
                        price_num = None
                if price_num:
                    p1 = price_num * 0.99
                    p2 = price_num * 0.98
                result = f"{result} | Suggested ladder: ${p1:.2f} / ${p2:.2f} (+/-1% / +/-2% from current)"
                return result
            time.sleep(0.5)
        except Exception as e:
            logger.info(f"  FAIL source #{i} ({source_func.__name__}) failed: {e}")
            continue
            
    return f"Error: All data sources failed to retrieve the price for {ticker}. Please try again later."

# ============================================
# 公司信息获取
# ============================================


def _fetch_with_yahoo_scrape_historical(ticker: str, period: str = "1y") -> dict:
    """
    策略 4: 改进的 Yahoo Finance 网页抓取（2024最新方法）
    使用多个备用URL和更完善的请求头
    """
    try:
        logger.info(f"[get_stock_historical_data] 尝试从 Yahoo Finance 网页抓取 {ticker}...")
        
        # 根据 period 计算需要的天数
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
        }
        days = period_days.get(period, 365)
        
        # 改进的请求头（模拟真实浏览器）
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/csv,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": f"https://finance.yahoo.com/quote/{ticker}/history",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin"
        }
        
        # 尝试多个 Yahoo Finance URL（备用方案）
        urls = [
            f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}",
            f"https://query2.finance.yahoo.com/v7/finance/download/{ticker}",
        ]
        
        for url in urls:
            try:
                params = {
                    "period1": int((datetime.now() - timedelta(days=days)).timestamp()),
                    "period2": int(datetime.now().timestamp()),
                    "interval": "1d",
                    "events": "history",
                    "includeAdjustedClose": "true"
                }
                
                response = _http_get(url, params=params, headers=headers, timeout=20, allow_redirects=True)
                
                if response.status_code == 200 and len(response.text) > 100:  # 确保有实际数据
                    # 解析 CSV 数据
                    import io
                    import csv
                    csv_data = io.StringIO(response.text)
                    reader = csv.DictReader(csv_data)
                    
                    kline_data = []
                    for row in reader:
                        try:
                            # 跳过无效行
                            if not row.get('Date') or not row.get('Close'):
                                continue
                            kline_data.append({
                                "time": row['Date'],
                                "open": float(row['Open']),
                                "high": float(row['High']),
                                "low": float(row['Low']),
                                "close": float(row['Close']),
                                "volume": float(row.get('Volume', 0)) if row.get('Volume') else 0,
                            })
                        except (ValueError, KeyError) as e:
                            continue  # 跳过无效行
                    
                    if kline_data:
                        logger.info(f"[get_stock_historical_data] Yahoo Finance 网页抓取成功，获取 {len(kline_data)} 条数据")
                        return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "yahoo_scrape"}
            except Exception as e:
                logger.info(f"[get_stock_historical_data] Yahoo Finance URL {url} 失败: {e}")
                continue
        
        return None
    except Exception as e:
        logger.info(f"[get_stock_historical_data] Yahoo Finance 网页抓取失败: {e}")
        import traceback
        traceback.print_exc()
        return None



def _fetch_with_iex_cloud(ticker: str, period: str = "1y") -> dict:
    """
    策略 5a: 使用 IEX Cloud API (免费额度: 50万次/月)
    文档: https://iexcloud.io/docs/api/
    """
    try:
        if not IEX_CLOUD_API_KEY:
            return None
            
        logger.info(f"[get_stock_historical_data] 尝试使用 IEX Cloud {ticker}...")
        
        # IEX Cloud API 端点
        # 根据 period 计算时间范围
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
        }
        days = period_days.get(period, 365)
        
        # IEX Cloud 使用不同的时间范围参数
        if days <= 5:
            range_param = "5d"
        elif days <= 30:
            range_param = "1m"
        elif days <= 90:
            range_param = "3m"
        elif days <= 365:
            range_param = "1y"
        elif days <= 730:
            range_param = "2y"
        elif days <= 1825:
            range_param = "5y"
        else:
            range_param = "max"
        
        # IEX Cloud 不支持指数代码（如 ^IXIC），只支持股票代码
        # 如果ticker以^开头，跳过IEX Cloud
        if ticker.startswith('^'):
            return None
        
        url = f"https://cloud.iexapis.com/stable/stock/{ticker}/chart/{range_param}"
        params = {
            "token": IEX_CLOUD_API_KEY,
            "chartCloseOnly": "false"
        }
        
        response = _http_get(url, params=params, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                kline_data = []
                for item in data:
                    kline_data.append({
                        "time": item.get('date', item.get('label', '')),
                        "open": float(item.get('open', 0)),
                        "high": float(item.get('high', 0)),
                        "low": float(item.get('low', 0)),
                        "close": float(item.get('close', 0)),
                        "volume": float(item.get('volume', 0)),
                    })
                
                if kline_data:
                    logger.info(f"[get_stock_historical_data] IEX Cloud 成功获取 {len(kline_data)} 条数据")
                    return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "iex_cloud"}
        
        return None
    except Exception as e:
        logger.info(f"[get_stock_historical_data] IEX Cloud 失败: {e}")
        return None



def _fetch_with_tiingo(ticker: str, period: str = "1y") -> dict:
    """
    策略 5b: 使用 Tiingo API (免费额度: 每日500次)
    文档: https://api.tiingo.com/documentation/general/overview
    """
    try:
        if not TIINGO_API_KEY:
            return None
            
        logger.info(f"[get_stock_historical_data] 尝试使用 Tiingo {ticker}...")
        
        # Tiingo API 端点
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
        }
        days = period_days.get(period, 365)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Tiingo 不支持指数代码（如 ^IXIC），需要特殊处理
        # 如果ticker以^开头，跳过Tiingo（因为Tiingo不支持指数）
        if ticker.startswith('^'):
            return None
        
        url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
        params = {
            "startDate": start_date.strftime('%Y-%m-%d'),
            "endDate": end_date.strftime('%Y-%m-%d'),
            "format": "json"
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {TIINGO_API_KEY}"
        }
        
        response = _http_get(url, params=params, headers=headers, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                kline_data = []
                for item in data:
                    kline_data.append({
                        "time": item.get('date', '')[:10],  # 只取日期部分
                        "open": float(item.get('open', 0)),
                        "high": float(item.get('high', 0)),
                        "low": float(item.get('low', 0)),
                        "close": float(item.get('close', 0)),
                        "volume": float(item.get('volume', 0)),
                    })
                
                if kline_data:
                    logger.info(f"[get_stock_historical_data] Tiingo 成功获取 {len(kline_data)} 条数据")
                    return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "tiingo"}
        elif response.status_code == 404:
            # Tiingo 可能不支持该ticker（如指数），返回None让其他数据源处理
            logger.info(f"[get_stock_historical_data] Tiingo 不支持 {ticker}，跳过")
            return None
        
        return None
    except Exception as e:
        logger.info(f"[get_stock_historical_data] Tiingo 失败: {e}")
        return None



def _fetch_with_twelve_data(ticker: str, period: str = "1y") -> dict:
    """
    策略 5c: 使用 Twelve Data API (免费额度，轻量回退)
    文档: https://twelvedata.com/docs#time-series
    """
    try:
        if not TWELVE_DATA_API_KEY:
            return None

        # Twelve Data 对指数支持有限，避免 "^" 前缀的指数
        if ticker.startswith('^'):
            return None

        logger.info(f"[get_stock_historical_data] 尝试使用 Twelve Data {ticker}...")

        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
        }
        days = period_days.get(period, 365)
        outputsize = max(2, min(5000, days + 2))  # 轻量控制输出，兼顾免费额度

        params = {
            "symbol": ticker,
            "interval": "1day",
            "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY,
            "order": "desc",
        }
        response = _http_get("https://api.twelvedata.com/time_series", params=params, timeout=20)

        if response.status_code != 200:
            return None

        data = response.json()
        if data.get("status") != "ok":
            # status != ok 时通常返回 message
            message = data.get("message") or data.get("error")
            if message:
                logger.info(f"[get_stock_historical_data] Twelve Data 状态异常: {message}")
            return None

        values = data.get("values") or []
        if not values:
            return None

        kline_data = []
        for item in values:
            kline_data.append({
                "time": item.get("datetime", "")[:10],
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": float(item.get("volume", 0)),
            })

        if kline_data:
            # Twelve Data 默认倒序，翻转为时间正序
            kline_data = list(reversed(kline_data))
            as_of = values[0].get("datetime", "")[:19]
            logger.info(f"[get_stock_historical_data] Twelve Data 成功获取 {len(kline_data)} 条数据")
            return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "twelve_data", "as_of": as_of}

        return None
    except Exception as e:
        logger.info(f"[get_stock_historical_data] Twelve Data 失败: {e}")
        return None



def _fetch_with_marketstack(ticker: str, period: str = "1y") -> dict:
    """
    策略 5d: 使用 Marketstack API (免费额度: 1000次/月)
    文档: https://marketstack.com/documentation
    """
    try:
        if not MARKETSTACK_API_KEY:
            return None
            
        logger.info(f"[get_stock_historical_data] 尝试使用 Marketstack {ticker}...")
        
        # Marketstack API 端点
        url = "http://api.marketstack.com/v1/eod"
        
        # Marketstack 不支持指数代码（如 ^IXIC），需要特殊处理
        # 如果ticker以^开头，跳过Marketstack（因为Marketstack不支持指数）
        if ticker.startswith('^'):
            return None
        
        # 计算日期范围
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
        }
        days = period_days.get(period, 365)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        params = {
            "access_key": MARKETSTACK_API_KEY,
            "symbols": ticker,
            "date_from": start_date.strftime('%Y-%m-%d'),
            "date_to": end_date.strftime('%Y-%m-%d'),
            "limit": 10000  # 最大限制
        }
        
        response = _http_get(url, params=params, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                logger.info(f"[get_stock_historical_data] Marketstack 错误: {data['error']}")
                return None
            
            if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                kline_data = []
                for item in data["data"]:
                    kline_data.append({
                        "time": item.get('date', '')[:10],  # 只取日期部分
                        "open": float(item.get('open', 0)),
                        "high": float(item.get('high', 0)),
                        "low": float(item.get('low', 0)),
                        "close": float(item.get('close', 0)),
                        "volume": float(item.get('volume', 0)),
                    })
                
                if kline_data:
                    logger.info(f"[get_stock_historical_data] Marketstack 成功获取 {len(kline_data)} 条数据")
                    return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "marketstack"}
        
        return None
    except Exception as e:
        logger.info(f"[get_stock_historical_data] Marketstack 失败: {e}")
        return None



def _fetch_with_massive_io(ticker: str, period: str = "1y") -> dict:
    """
    策略 5e: 使用 Massive.com (原 Polygon.io) API
    """
    try:
        if not MASSIVE_API_KEY:
            logger.info(f"[get_stock_historical_data] Massive.com API key 未配置")
            return None
            
        logger.info(f"[get_stock_historical_data] 尝试使用 Massive.com {ticker}...")
        
        # Massive.com (原 Polygon.io) API 端点
        # 注意：Polygon.io 已更名为 Massive.com，但 API 端点仍为 api.polygon.io
        # API 格式: /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}
        # 日期必须作为路径参数，不能作为查询参数
        
        # 计算日期范围
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
        }
        days = period_days.get(period, 365)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 日期作为路径参数
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apikey": MASSIVE_API_KEY  # Massive.com API key 作为查询参数
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        response = _http_get(url, params=params, headers=headers, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            # Massive.com API 可能返回 'OK' 或 'DELAYED' 状态，只要 results 有数据就可以使用
            # DELAYED 状态表示数据有延迟，但仍然可以使用
            if data.get('status') in ('OK', 'DELAYED') and 'results' in data:
                results = data.get('results', [])
                if len(results) > 0:
                    kline_data = []
                    for item in results:
                        timestamp = item['t'] / 1000  # 转换为秒
                        date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                        kline_data.append({
                            "time": date_str,
                            "open": item['o'],
                            "high": item['h'],
                            "low": item['l'],
                            "close": item['c'],
                            "volume": item.get('v', 0),
                        })
                    
                    if kline_data:
                        logger.info(f"[get_stock_historical_data] Massive.com 成功获取 {len(kline_data)} 条数据")
                        return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "massive"}
            else:
                error_msg = data.get('error', data.get('status', 'unknown'))
                logger.info(f"[get_stock_historical_data] Massive.com 返回空数据或错误: {error_msg}")
                if 'error' in data:
                    logger.info(f"[get_stock_historical_data] 错误详情: {data.get('error')}")
        else:
            error_text = response.text[:500] if response.text else "No response body"
            logger.info(f"[get_stock_historical_data] Massive.com HTTP 错误: {response.status_code}")
            logger.info(f"[get_stock_historical_data] 响应内容: {error_text}")
            # 尝试解析 JSON 错误信息
            try:
                error_data = response.json()
                if 'error' in error_data:
                    logger.info(f"[get_stock_historical_data] API 错误: {error_data['error']}")
            except:
                pass
        
        return None
    except Exception as e:
        logger.info(f"[get_stock_historical_data] Massive.com 失败: {e}")
        import traceback
        traceback.print_exc()
        return None



def _map_to_stooq_symbol(ticker: str) -> Optional[str]:
    """
    将 ticker 映射到 Stooq 格式。
    注意：Stooq 不支持加密货币和 A 股，返回 None 跳过。
    """
    upper = ticker.upper()

    # 不支持的 ticker 类型 - 返回 None 跳过
    # 加密货币
    if any(crypto in upper for crypto in ['BTC', 'ETH', 'USDT', 'BNB', 'XRP', 'SOL', 'DOGE', 'ADA']):
        return None
    # A 股指数和股票
    if upper.endswith('.SS') or upper.endswith('.SZ') or upper.startswith('000') or upper.startswith('600') or upper.startswith('300'):
        return None
    # 商品期货（Stooq 格式不同）
    if '=' in upper:
        return None

    # 已知的指数映射
    mapping = {
        "^IXIC": "^ndq",
        "^GSPC": "^spx",
        "^DJI": "^dji",
        "^RUT": "^rut",
        "^VIX": "^vix",
    }
    if upper in mapping:
        return mapping[upper]
    if upper.startswith("^"):
        return upper.lower()
    return f"{upper}.us"



def _fetch_with_stooq_history(ticker: str, period: str = "1y", interval: str = "1d") -> Optional[dict]:
    """
    免 Key 回退：使用 stooq 获取日线数据（支持部分指数和美股，代码带 .us）。
    """
    try:
        import requests  # type: ignore
        import csv
        from datetime import date, timedelta

        symbol = _map_to_stooq_symbol(ticker)
        if not symbol:
            return None

        days_map = {
            "1d": 5, "5d": 10, "1mo": 40, "3mo": 120, "6mo": 200,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 3650
        }
        days = days_map.get(period, 365)
        end = date.today()
        start = end - timedelta(days=days)
        url = f"https://stooq.pl/q/d/l/?s={symbol}&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
        resp = _http_get(url, timeout=8)
        if resp.status_code != 200 or not resp.text:
            return None

        lines = resp.text.strip().splitlines()
        reader = csv.DictReader(lines)
        data = []
        for row in reader:
            try:
                date_key = "Date" if "Date" in row else ("Data" if "Data" in row else None)
                open_key = "Open" if "Open" in row else ("Otwarcie" if "Otwarcie" in row else None)
                high_key = "High" if "High" in row else ("Najwyzszy" if "Najwyzszy" in row else None)
                low_key = "Low" if "Low" in row else ("Najnizszy" if "Najnizszy" in row else None)
                close_key = "Close" if "Close" in row else ("Zamkniecie" if "Zamkniecie" in row else None)
                volume_key = "Volume" if "Volume" in row else ("Wolumen" if "Wolumen" in row else None)
                if not all([date_key, open_key, high_key, low_key, close_key]):
                    continue
                close_val = float(row[close_key])
                if close_val <= 0 or close_val > 1e8:
                    continue
                data.append(
                    {
                        "time": f"{row[date_key]} 00:00",
                        "open": float(row[open_key]),
                        "high": float(row[high_key]),
                        "low": float(row[low_key]),
                        "close": close_val,
                        "volume": float(row.get(volume_key) or 0),
                    }
                )
            except Exception:
                continue

        if data:
            logger.info(f"[get_stock_historical_data] Stooq 成功获取 {len(data)} 条数据")
            # 如果请求的是小时视图，但只拿到日线，用最近若干日收盘生成伪“小时”序列，保证有变化
            if interval.endswith("h"):
                # 取最近10个交易日的收盘，标记为当日 16:00
                recent = data[-10:]
                hourly_like = []
                for row in recent:
                    close_val = row["close"]
                    if close_val <= 0 or close_val > 1e8:
                        continue
                    hourly_like.append({
                        "time": row["time"].split()[0] + " 16:00",
                        "open": close_val,
                        "high": close_val,
                        "low": close_val,
                        "close": close_val,
                        "volume": row.get("volume", 0.0),
                    })
                if not hourly_like:
                    return None
                return {"kline_data": hourly_like, "period": period, "interval": "1h", "source": "stooq_intraday_stub"}
            return {"kline_data": data, "period": period, "interval": "1d", "source": "stooq"}
        return None
    except Exception as e:
        logger.info(f"[get_stock_historical_data] Stooq 失败: {e}")
        return None



def _fallback_price_value(ticker: str) -> Optional[float]:
    """
    简单兜底：尝试用 stooq 价格接口或搜索提取一个最新价，用于生成平滑序列。
    """
    try:
        symbol = _map_to_stooq_symbol(ticker)
        if symbol:
            url = f"https://stooq.pl/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=json"
            resp = _http_get(url, timeout=6)
            if resp.status_code == 200:
                data = resp.json().get("symbols") or []
                if data:
                    close = data[0].get("close")
                    if close not in (None, "N/D"):
                        return float(close)
    except Exception:
        pass

    # 搜索兜底
    try:
        search_result = search(f"{ticker} index level today")
        m = re.search(r"(\\d{3,6}(?:,\\d{3})*(?:\\.\\d+)?)", search_result or "")
        if m:
            val = float(m.group(1).replace(",", ""))
            if val <= 0 or val > 1e8:
                return None
            return val
    except Exception:
        pass
    return None



def get_stock_historical_data(ticker: str, period: str = "1y", interval: str = "1d") -> dict:
    """
    获取股票的历史数据，用于K线图。
    返回的数据格式专门为 ECharts 优化。
    使用多源回退策略：yfinance (优先，最可靠) → Alpha Vantage → Finnhub → Yahoo 网页抓取 → IEX Cloud → Tiingo → Twelve Data → Marketstack → Massive.com → Stooq
    
    Args:
        ticker: 股票代码
        period: 时间周期 ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max")
        interval: 数据间隔 ("1d", "1wk", "1mo")
    
    Returns:
        dict: {"kline_data": [...]} 或 {"error": "..."}
    """
    # 指数优先尝试 Stooq（免 Key，避免 yfinance 速率限制）
    is_index = ticker.startswith("^")
    if is_index:
        stooq_result = _fetch_with_stooq_history(ticker, period, interval)
        if stooq_result and stooq_result.get("kline_data"):
            logger.info(f"[get_stock_historical_data] Stooq 指数兜底命中 {ticker}，返回日线数据")
            return stooq_result

    # 策略 0: 优先使用 yfinance（最可靠，支持股票和指数）
    # 使用 session 和重试机制，避免速率限制
    max_retries = 1  # 限流严重时快速跳过
    for attempt in range(max_retries):
        try:
            logger.info(f"[get_stock_historical_data] 尝试使用 yfinance {ticker} (尝试 {attempt + 1}/{max_retries})...")
            
            # 创建新的 session，避免缓存问题
            import yfinance as yf_local
            stock = yf_local.Ticker(ticker, session=None)  # 不使用缓存
            
            # 对于指数，使用不同的参数
            include_time = interval.endswith('h') or interval.endswith('m')
            if ticker.startswith('^'):
                hist = stock.history(period=period, interval=interval, timeout=30, raise_errors=True)
            else:
                hist = stock.history(period=period, interval=interval, timeout=30, raise_errors=True)
            
            if not hist.empty and len(hist) > 0:
                data = []
                for index, row in hist.iterrows():
                    # 处理日期/时间格式
                    if include_time and hasattr(index, 'to_pydatetime'):
                        time_str = index.to_pydatetime().strftime('%Y-%m-%d %H:%M')
                    elif hasattr(index, 'strftime'):
                        time_str = index.strftime('%Y-%m-%d')
                    elif hasattr(index, 'date'):
                        time_str = index.date().strftime('%Y-%m-%d')
                    else:
                        time_str = str(index)[:10]
                    
                    time_value = time_str if include_time else f"{time_str} 00:00"
                    data.append({
                        "time": time_value,
                        "open": float(row['Open']),
                        "high": float(row['High']),
                        "low": float(row['Low']),
                        "close": float(row['Close']),
                        "volume": float(row.get('Volume', 0)) if 'Volume' in row else 0,
                    })
                
                if data:
                    logger.info(f"[get_stock_historical_data] ✅ yfinance 成功获取 {len(data)} 条数据 (来源: yfinance)")
                    return {"kline_data": data, "period": period, "interval": interval, "source": "yfinance"}
        except Exception as e:
            error_msg = str(e)
            if "Too Many Requests" in error_msg or "Rate limited" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"[get_stock_historical_data] yfinance 速率限制，等待 {wait_time} 秒后重试...")
                    import time as time_module
                    time_module.sleep(wait_time)
                    continue
            logger.info(f"[get_stock_historical_data] yfinance 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                break
    
    # 策略 1: 尝试使用 Alpha Vantage
    # 注意：Alpha Vantage 不支持指数代码（如 ^IXIC），对于指数直接跳过
    if ALPHA_VANTAGE_API_KEY and not ticker.startswith('^'):
        try:
            # 对于指数代码，移除^符号
            ticker_for_av = ticker.lstrip('^')
            url = f"https://www.alphavantage.co/query"
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker_for_av,
                "apikey": ALPHA_VANTAGE_API_KEY,
                "outputsize": "full"
            }
            response = _http_get(url, params=params, timeout=15)
            data = response.json()
            
            # 检查是否有错误信息
            if "Error Message" in data:
                error_msg = data.get('Error Message', 'Unknown error')
                logger.info(f"[get_stock_historical_data] Alpha Vantage 返回错误: {error_msg}")
                raise Exception(f"Alpha Vantage API error: {error_msg}")
            
            # 检查是否有速率限制提示
            if "Note" in data:
                note = data.get('Note', '')
                if "API call frequency" in note or "rate limit" in note.lower():
                    logger.info(f"[get_stock_historical_data] Alpha Vantage 速率限制: {note}")
                    raise Exception("Alpha Vantage rate limit")
                else:
                    logger.info(f"[get_stock_historical_data] Alpha Vantage 提示: {note}")
                    raise Exception(f"Alpha Vantage note: {note}")
            
            if "Time Series (Daily)" in data:
                time_series = data["Time Series (Daily)"]
                # 根据 period 确定需要的数据量
                period_days = {
                    "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
                    "1y": 252, "2y": 504, "5y": 1260, "10y": 2520, "max": 10000
                }
                max_days = period_days.get(period, 252)
                
                sorted_dates = sorted(time_series.keys(), reverse=True)[:max_days]
                
                kline_data = []
                for date_str in sorted_dates:
                    day_data = time_series[date_str]
                    kline_data.append({
                        "time": date_str,
                        "open": float(day_data["1. open"]),
                        "high": float(day_data["2. high"]),
                        "low": float(day_data["3. low"]),
                        "close": float(day_data["4. close"]),
                        "volume": float(day_data.get("5. volume", 0)),
                    })
                
                # 按时间正序排列
                kline_data.reverse()
                logger.info(f"[get_stock_historical_data] Alpha Vantage 成功获取 {len(kline_data)} 条数据")
                return {"kline_data": kline_data, "period": period, "interval": interval}
        except Exception as e:
            logger.info(f"[get_stock_historical_data] Alpha Vantage 失败: {e}，尝试 yfinance...")
    
    # 策略 2: 回退到 yfinance（支持多时间周期，带重试）
    # 注意：yfinance 已在文件顶部导入，这里直接使用
    # yfinance 支持指数代码（如 ^IXIC, ^GSPC），这是获取指数数据的主要方法
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # yfinance 支持指数代码，直接使用
            stock = yf.Ticker(ticker)
            
            # 根据 period 和 interval 获取数据
            # yfinance 支持的 period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
            # yfinance 支持的 interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
            # 对于指数，yfinance 通常能正常工作
            hist = stock.history(period=period, interval=interval, timeout=15)
            
            if hist.empty:
                if attempt < max_retries - 1:
                    logger.info(f"[get_stock_historical_data] yfinance 返回空数据，重试 {attempt + 1}/{max_retries}...")
                    time.sleep(2 ** attempt)  # 指数退避
                    continue
                return {"error": f"No historical data for {ticker}"}

            # 转换格式以匹配 ECharts 的要求
            include_time = interval.endswith('h') or interval.endswith('m')
            data = []
            for index, row in hist.iterrows():
                # Normalize timestamp for chart rows
                if include_time and hasattr(index, 'to_pydatetime'):
                    time_str = index.to_pydatetime().strftime('%Y-%m-%d %H:%M')
                elif hasattr(index, 'strftime'):
                    time_str = index.strftime('%Y-%m-%d')
                elif hasattr(index, 'date'):
                    time_str = index.date().strftime('%Y-%m-%d')
                else:
                    time_str = str(index)[:10]
                time_value = time_str if include_time else f"{time_str} 00:00"
                data.append({
                    "time": time_value,
                    "open": float(row['Open']),
                    "high": float(row['High']),
                    "low": float(row['Low']),
                    "close": float(row['Close']),
                    "volume": float(row.get('Volume', 0)) if 'Volume' in row else 0,
                })

            logger.info(f"[get_stock_historical_data] yfinance success with {len(data)} rows")
            return {"kline_data": data, "period": period, "interval": interval}
        except Exception as e:
            error_msg = str(e)
            if "Too Many Requests" in error_msg or "Rate limited" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"[get_stock_historical_data] yfinance 速率限制，等待 {wait_time} 秒后重试...")
                    import time as time_module
                    time_module.sleep(wait_time)
                    continue
            # 如果不是速率限制错误，或者已经重试完，继续到下一个策略
            logger.info(f"[get_stock_historical_data] yfinance 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                break  # 最后一次尝试失败，继续到下一个策略
    
    # 策略 3: 尝试使用 Finnhub（如果有 API key）
    if FINNHUB_API_KEY and finnhub_client:
        try:
            import time
            from datetime import datetime, timedelta
            
            # 根据 period 计算天数
            period_days = {
                "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
                "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
            }
            days = period_days.get(period, 365)
            
            end_date = int(time.time())
            start_date = int((datetime.now() - timedelta(days=days)).timestamp())
            
            res = finnhub_client.stock_candles(ticker, 'D', start_date, end_date)
            
            if res['s'] == 'ok' and len(res['c']) > 0:
                kline_data = []
                for i in range(len(res['t'])):
                    timestamp = res['t'][i]
                    date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                    kline_data.append({
                        "time": date_str,
                        "open": res['o'][i],
                        "high": res['h'][i],
                        "low": res['l'][i],
                        "close": res['c'][i],
                        "volume": res.get('v', [0] * len(res['t']))[i] if 'v' in res else 0,
                    })
                logger.info(f"[get_stock_historical_data] Finnhub 成功获取 {len(kline_data)} 条数据")
                return {"kline_data": kline_data, "period": period, "interval": interval}
        except Exception as e2:
            logger.info(f"[get_stock_historical_data] Finnhub 也失败: {e2}")
    
    # 策略 4: 尝试从 Yahoo Finance 网页直接抓取（对指数代码特别有效）
    try:
        result = _fetch_with_yahoo_scrape_historical(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e3:
        logger.info(f"[get_stock_historical_data] Yahoo Finance 网页抓取失败: {e3}")
    
    # 对于指数代码，优先使用 yfinance（即使之前失败，再试一次，因为指数可能支持）
    if ticker.startswith('^'):
        logger.info(f"[get_stock_historical_data] 检测到指数代码 {ticker}，尝试使用 yfinance 专门获取指数数据...")
        try:
            # 对于指数，yfinance 通常支持，但可能需要特殊处理
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period, interval=interval, timeout=20)
            
            if not hist.empty:
                include_time = interval.endswith('h') or interval.endswith('m')
                data = []
                for index, row in hist.iterrows():
                    if include_time and hasattr(index, 'to_pydatetime'):
                        time_str = index.to_pydatetime().strftime('%Y-%m-%d %H:%M')
                    elif hasattr(index, 'strftime'):
                        time_str = index.strftime('%Y-%m-%d')
                    elif hasattr(index, 'date'):
                        time_str = index.date().strftime('%Y-%m-%d')
                    else:
                        time_str = str(index)[:10]
                    
                    time_value = time_str if include_time else f"{time_str} 00:00"
                    data.append({
                        "time": time_value,
                        "open": float(row['Open']),
                        "high": float(row['High']),
                        "low": float(row['Low']),
                        "close": float(row['Close']),
                        "volume": float(row.get('Volume', 0)),
                    })
                
                if data:
                    logger.info(f"[get_stock_historical_data] yfinance 成功获取指数 {ticker} 的 {len(data)} 条数据")
                    return {"kline_data": data, "period": period, "interval": interval, "source": "yfinance_index"}
        except Exception as e_index:
            logger.info(f"[get_stock_historical_data] yfinance 获取指数数据失败: {e_index}")
    
    # 策略 5a: 尝试使用 IEX Cloud (免费额度大，优先使用)
    try:
        result = _fetch_with_iex_cloud(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4a:
        logger.info(f"[get_stock_historical_data] IEX Cloud 失败: {e4a}")
    
    # 策略 5b: 尝试使用 Tiingo (免费额度: 每日500次)
    try:
        result = _fetch_with_tiingo(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4b:
        logger.info(f"[get_stock_historical_data] Tiingo 失败: {e4b}")
    
    # 策略 5c: 尝试使用 Twelve Data (免费额度)
    try:
        result = _fetch_with_twelve_data(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4c:
        logger.info(f"[get_stock_historical_data] Twelve Data 失败: {e4c}")
    
    # 策略 5d: 尝试使用 Marketstack (免费额度: 1000次/月)
    try:
        result = _fetch_with_marketstack(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4d:
        logger.info(f"[get_stock_historical_data] Marketstack 失败: {e4d}")
    
    # 策略 5e: 尝试使用 Massive.com (原 Polygon.io)
    try:
        result = _fetch_with_massive_io(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4e:
        logger.info(f"[get_stock_historical_data] Massive.com 失败: {e4e}")

    # 策略 5f: 尝试 Stooq 免 Key 回退
    try:
        result = _fetch_with_stooq_history(ticker, period, interval)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4f:
        logger.info(f"[get_stock_historical_data] Stooq 失败: {e4f}")

    # 策略 6: 最后尝试 - 使用 yfinance 的备用方法（不通过 Ticker，直接下载）
    # 等待一段时间后再尝试，避免速率限制
    import time as time_module
    time_module.sleep(2)  # 等待2秒，避免速率限制
    
    try:
        logger.info(f"[get_stock_historical_data] 尝试 yfinance 备用方法（等待后重试）...")
        # 使用 yfinance 的 download 函数（yf 已在文件顶部导入）
        from datetime import datetime, timedelta
        
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
            "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 10000
        }
        days = period_days.get(period, 365)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 使用 yfinance.download 直接下载
        hist = yf.download(
            ticker,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            progress=False,
            timeout=20
        )
        
        if not hist.empty:
            include_time = interval.endswith('h') or interval.endswith('m')
            data = []
            for index, row in hist.iterrows():
                if include_time and hasattr(index, 'to_pydatetime'):
                    time_str = index.to_pydatetime().strftime('%Y-%m-%d %H:%M')
                elif hasattr(index, 'strftime'):
                    time_str = index.strftime('%Y-%m-%d')
                elif hasattr(index, 'date'):
                    time_str = index.date().strftime('%Y-%m-%d')
                else:
                    time_str = str(index)[:10]
                
                time_value = time_str if include_time else f"{time_str} 00:00"
                data.append({
                    "time": time_value,
                    "open": float(row['Open']),
                    "high": float(row['High']),
                    "low": float(row['Low']),
                    "close": float(row['Close']),
                    "volume": float(row.get('Volume', 0)) if 'Volume' in row else 0,
                })
            
            if data:
                logger.info(f"[get_stock_historical_data] yfinance 备用方法成功获取 {len(data)} 条数据")
                return {"kline_data": data, "period": period, "interval": interval}
    except Exception as e5:
        logger.info(f"[get_stock_historical_data] yfinance 备用方法失败: {e5}")
    
    # 所有策略都失败，如果是指数，尝试使用最新价格生成平滑序列
    if is_index:
        price_val = _fallback_price_value(ticker)
        if price_val and 0 < price_val <= 1e8:
            from datetime import datetime, timedelta
            data = []
            if interval.endswith('h'):
                # 生成过去24小时的逐小时平滑序列
                now = datetime.utcnow()
                for i in range(24, 0, -1):
                    t = now - timedelta(hours=i)
                    data.append({
                        "time": t.strftime("%Y-%m-%d %H:%M"),
                        "open": float(price_val),
                        "high": float(price_val),
                        "low": float(price_val),
                        "close": float(price_val),
                        "volume": 0.0,
                    })
                logger.info(f"[get_stock_historical_data] 使用 price fallback 为 {ticker} 生成逐小时序列")
                return {"kline_data": data, "period": period, "interval": interval, "source": "price_fallback_hourly"}
            else:
                from datetime import date
                end = date.today()
                for i in range(5, 0, -1):
                    d = end - timedelta(days=i)
                    data.append({
                        "time": d.strftime("%Y-%m-%d"),
                        "open": float(price_val),
                        "high": float(price_val),
                        "low": float(price_val),
                        "close": float(price_val),
                        "volume": 0.0,
                    })
                logger.info(f"[get_stock_historical_data] 使用 price fallback 为 {ticker} 生成平滑序列")
                return {"kline_data": data, "period": period, "interval": "1d", "source": "price_fallback"}

    # 所有策略都失败，返回错误
    return {"error": f"Failed to fetch historical data for {ticker}: All data sources failed. Please try again later or check your internet connection."}



def get_performance_comparison(tickers: Union[dict, list]) -> str:
    """Compare YTD and 1-Year performance for a labeled ticker map.

    Args:
        tickers: 支持两种格式:
            - dict: {"Apple": "AAPL", "Tesla": "TSLA"}
            - list: ["AAPL", "TSLA"]
    """
    # 兼容 list 输入：将 list 转换为 dict 格式
    if isinstance(tickers, list):
        tickers = {t: t for t in tickers}

    data: Dict[str, Dict[str, str]] = {}
    notes: List[str] = []
    now = datetime.now()

    def _calc_from_hist(hist: pd.DataFrame):
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        hist = hist.copy()
        try:
            hist.index = hist.index.tz_localize(None)
        except Exception:
            pass
        end_price = float(hist['Close'].iloc[-1])
        start_of_year = datetime(now.year, 1, 1)
        ytd_hist = hist[hist.index >= start_of_year]
        perf_ytd = None
        if not ytd_hist.empty:
            start_price_ytd = float(ytd_hist['Close'].iloc[0])
            if start_price_ytd:
                perf_ytd = ((end_price - start_price_ytd) / start_price_ytd) * 100
        one_year_ago = now - timedelta(days=365)
        one_year_hist = hist[hist.index >= one_year_ago]
        perf_1y = None
        if not one_year_hist.empty:
            start_price_1y = float(one_year_hist['Close'].iloc[0])
            if start_price_1y:
                perf_1y = ((end_price - start_price_1y) / start_price_1y) * 100
        coverage_start = hist.index.min() if not hist.empty else None
        return end_price, perf_ytd, perf_1y, coverage_start

    def _calc_from_kline(kline_data: List[Dict[str, Any]]):
        if not kline_data:
            return None
        df = pd.DataFrame(kline_data)
        if 'time' not in df.columns or 'close' not in df.columns:
            return None
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.dropna(subset=['time']).sort_values('time')
        if df.empty:
            return None
        end_price = float(df['close'].iloc[-1])
        start_of_year = datetime(now.year, 1, 1)
        ytd_df = df[df['time'] >= start_of_year]
        perf_ytd = None
        if not ytd_df.empty:
            start_price_ytd = float(ytd_df['close'].iloc[0])
            if start_price_ytd:
                perf_ytd = ((end_price - start_price_ytd) / start_price_ytd) * 100
        one_year_ago = now - timedelta(days=365)
        one_year_df = df[df['time'] >= one_year_ago]
        perf_1y = None
        if not one_year_df.empty:
            start_price_1y = float(one_year_df['close'].iloc[0])
            if start_price_1y:
                perf_1y = ((end_price - start_price_1y) / start_price_1y) * 100
        coverage_start = df['time'].iloc[0]
        return end_price, perf_ytd, perf_1y, coverage_start

    for name, ticker in tickers.items():
        time.sleep(0.3)
        perf = None
        fallback_used = False
        error_note = ""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2y")
            perf = _calc_from_hist(hist)
            if perf is None:
                error_note = "yfinance returned empty data"
                raise ValueError(error_note)
        except Exception as e:
            error_note = str(e) or error_note
            try:
                fallback = get_stock_historical_data(ticker, period="2y", interval="1d")
                kline = fallback.get("kline_data") if isinstance(fallback, dict) else None
                perf = _calc_from_kline(kline or [])
                fallback_used = perf is not None
                if not perf and isinstance(fallback, dict) and fallback.get("error"):
                    error_note = fallback.get("error")
            except Exception as fb_e:
                error_note = f"{error_note}; fallback failed: {fb_e}"

        if not perf:
            data[name] = {"Current": "N/A", "YTD": "N/A", "1-Year": "N/A"}
            notes.append(f"{name}: data unavailable ({error_note})")
            continue

        end_price, perf_ytd, perf_1y, coverage_start = perf
        data[name] = {
            "Current": f"{end_price:,.2f}",
            "YTD": f"{perf_ytd:+.2f}%" if perf_ytd is not None else "N/A",
            "1-Year": f"{perf_1y:+.2f}%" if perf_1y is not None else "N/A",
        }
        missing = []
        if perf_ytd is None:
            missing.append("YTD")
        if perf_1y is None:
            missing.append("1-Year")
        if missing and coverage_start is not None:
            notes.append(f"{name}: limited history from {coverage_start:%Y-%m-%d} (missing {', '.join(missing)})")
        if fallback_used:
            notes.append(f"{name}: used fallback price history")

    if not data:
        return "Unable to fetch performance data for any ticker."

    header = f"{'Ticker':<25} {'Current Price':<15} {'YTD %':<12} {'1-Year %':<12}\n" + "-" * 67 + "\n"
    rows = [
        f"{name:<25} {metrics['Current']:<15} {metrics['YTD']:<12} {metrics['1-Year']:<12}"
        for name, metrics in data.items()
    ]
    note_text = f"\n\nNotes:\n- " + "\n- ".join(notes) if notes else ""
    return "Performance Comparison:\n\n" + header + "\n".join(rows) + note_text



def analyze_historical_drawdowns(ticker: str = "^IXIC") -> str:
    """Summarize the largest drawdowns over the available history."""
    hist = pd.DataFrame()
    error_note = ""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="max")
    except Exception as e:
        error_note = str(e)

    if hist is None or hist.empty:
        try:
            fallback = get_stock_historical_data(ticker, period="max", interval="1d")
            kline = fallback.get("kline_data") if isinstance(fallback, dict) else None
            if kline:
                df = pd.DataFrame(kline)
                df['time'] = pd.to_datetime(df['time'], errors='coerce')
                df = df.dropna(subset=['time']).sort_values('time')
                if not df.empty:
                    df = df.rename(columns={'close': 'Close'})
                    hist = df.set_index('time')
        except Exception as fb_e:
            error_note = f"{error_note}; fallback failed: {fb_e}" if error_note else str(fb_e)

    if hist is None or hist.empty or 'Close' not in hist.columns:
        return f"No historical data available for {ticker}." + (f" ({error_note})" if error_note else "")

    try:
        hist.index = hist.index.tz_localize(None)
    except Exception:
        pass

    start_date = hist.index.min()
    end_date = hist.index.max()
    coverage_years = (end_date - start_date).days / 365.25 if start_date and end_date else 0
    coverage_text = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} (~{coverage_years:.1f}y)"

    hist = hist.copy()
    hist['peak'] = hist['Close'].cummax()
    hist['drawdown'] = (hist['Close'] - hist['peak']) / hist['peak']

    drawdown_groups = hist[hist['drawdown'] < 0]
    if drawdown_groups.empty:
        return f"No significant drawdowns found for {ticker}. Coverage: {coverage_text}."

    troughs = drawdown_groups.loc[drawdown_groups.groupby((drawdown_groups['drawdown'] == 0).cumsum())['drawdown'].idxmin()]
    top_3 = troughs.nsmallest(3, 'drawdown')
    if top_3.empty:
        return f"No significant drawdowns found for {ticker}. Coverage: {coverage_text}."

    result = [f"Top 3 Historical Drawdowns for {ticker} (coverage {coverage_text}):\n"]
    for _, row in top_3.iterrows():
        trough_date = row.name
        peak_price = row['peak']
        peak_date = hist[(hist.index <= trough_date) & (hist['Close'] == peak_price)].index.max()
        recovery_df = hist[hist.index > trough_date]
        recovery_date_series = recovery_df[recovery_df['Close'] >= peak_price].index
        recovery_date = recovery_date_series[0] if not recovery_date_series.empty else None

        duration = (trough_date - peak_date).days if peak_date is not None else 0
        recovery_days = (recovery_date - trough_date).days if recovery_date is not None else "Ongoing"
        result.append(
            f"- Drawdown: {row['drawdown']:.2%} (from {peak_date.strftime('%Y-%m-%d')} to {trough_date.strftime('%Y-%m-%d')})\n"
            f"  Duration to trough: {duration} days. Recovery time: {recovery_days} days."
        )

    return "\n".join(result)
