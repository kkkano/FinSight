import yfinance as yf
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
import time
import re
import finnhub
import pandas as pd
import os
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# 搜索相关导入（已测试可用）
try:
    from ddgs import DDGS  # 新版本包名（推荐）
    DDGS_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS  # 旧版本包名（兼容，但会显示警告）
        DDGS_AVAILABLE = True
        print("[Warning] 建议使用 'pip install ddgs' 替代 'duckduckgo_search'")
    except ImportError:
        DDGS = None
        DDGS_AVAILABLE = False
        print("[Warning] 搜索功能不可用：未安装 ddgs 或 duckduckgo_search")

try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TavilyClient = None
    TAVILY_AVAILABLE = False
    print("[Warning] Tavily 搜索不可用：未安装 tavily-python")

# 维基百科支持（免费，不需要API key）
try:
    import wikipedia
    wikipedia.set_lang("zh")  # 设置中文
    WIKIPEDIA_AVAILABLE = True
except ImportError:
    wikipedia = None
    WIKIPEDIA_AVAILABLE = False
    print("[Warning] 维基百科不可用：未安装 wikipedia，运行: pip install wikipedia")

# 加载 .env 文件中的环境变量
load_dotenv()

# ============================================
# API配置
# ============================================
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip('"')  # 移除可能的引号
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip('"')
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "").strip('"')  # Massive.com (原 Polygon.io) - 请在 .env 文件中配置
IEX_CLOUD_API_KEY = os.getenv("IEX_CLOUD_API_KEY", "").strip('"')  # IEX Cloud (免费额度: 50万次/月)
TIINGO_API_KEY = os.getenv("TIINGO_API_KEY", "").strip('"')  # Tiingo (免费额度: 每日500次)
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip('"')  # Twelve Data (免费额度)
MARKETSTACK_API_KEY = os.getenv("MARKETSTACK_API_KEY", "").strip('"')  # Marketstack (免费额度: 1000次/月)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip('"')  # Tavily Search API (AI搜索，免费额度: 1000次/月)

# ============================================
# API 客户端初始化
# ============================================
# 在脚本顶部初始化一次，以提高效率
try:
    finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
except Exception as e:
    print(f"Failed to initialize Finnhub client: {e}")
    finnhub_client = None

# ============================================
# 辅助函数
# ============================================

def search(query: str) -> str:
    """
    使用多数据源策略执行网页搜索并合并结果。
    同时使用：维基百科 + Tavily Search + DuckDuckGo，然后合并总结
    
    Args:
        query: 搜索查询字符串
        
    Returns:
        格式化的合并搜索结果
    """
    all_results = []
    sources_used = []
    
    # 1. 尝试维基百科（最准确，免费）
    if WIKIPEDIA_AVAILABLE:
        try:
            wiki_result = _search_with_wikipedia(query)
            if wiki_result and len(wiki_result) > 100:
                all_results.append({
                    'source': 'Wikipedia',
                    'content': wiki_result
                })
                sources_used.append('Wikipedia')
                print(f"[Search] ✅ 维基百科获取信息成功: {query[:50]}...")
        except Exception as e:
            print(f"[Search] 维基百科搜索失败: {e}")
    
    # 2. 尝试 Tavily Search (AI搜索)
    if TAVILY_API_KEY and TAVILY_AVAILABLE:
        try:
            tavily_result = _search_with_tavily(query)
            if tavily_result and len(tavily_result) > 50:
                all_results.append({
                    'source': 'Tavily',
                    'content': tavily_result
                })
                sources_used.append('Tavily')
                print(f"[Search] ✅ Tavily 搜索成功: {query[:50]}...")
        except Exception as e:
            error_msg = str(e) if e else "未知错误"
            error_type = type(e).__name__
            if "Forbidden" in error_type or "403" in error_msg or "401" in error_msg:
                print(f"[Search] Tavily API 认证失败 ({error_type}): 请检查 TAVILY_API_KEY 是否正确")
            else:
                print(f"[Search] Tavily 搜索失败: {error_msg}")
    
    # 3. 尝试 DuckDuckGo
    if DDGS_AVAILABLE and DDGS is not None:
        try:
            ddgs_result = _search_with_duckduckgo(query)
            if ddgs_result and len(ddgs_result) > 50:
                all_results.append({
                    'source': 'DuckDuckGo',
                    'content': ddgs_result
                })
                sources_used.append('DuckDuckGo')
                print(f"[Search] ✅ DuckDuckGo 搜索成功: {query[:50]}...")
        except Exception as e:
            print(f"[Search] DuckDuckGo 搜索失败: {e}")
    
    # 4. 合并所有结果
    if not all_results:
        return "Search error: 所有搜索源均失败，无法获取搜索结果。"
    
    # 合并结果
    combined_result = _merge_search_results(all_results, query)
    
    print(f"[Search] ✅ 成功使用 {len(sources_used)} 个搜索源: {', '.join(sources_used)}")
    return combined_result


def _search_with_duckduckgo(query: str) -> str:
    """使用 DuckDuckGo 搜索"""
    if not DDGS_AVAILABLE or DDGS is None:
        raise Exception("DuckDuckGo 不可用")
    
    for attempt in range(3):  # 增加重试次数
        try:
            ddgs = DDGS()
            
            try:
                results = list(ddgs.text(query, max_results=10, safesearch='moderate'))
            except TypeError:
                results = list(ddgs.text(query, max_results=10))
            
            if not results:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None
            
            # 验证结果相关性
            query_lower = query.lower()
            relevant_results = []
            for res in results:
                title = res.get('title', '')
                body = res.get('body', '')
                title_lower = title.lower()
                body_lower = body.lower()
                
                query_words = [w for w in query_lower.split() if len(w) > 2 and w not in ['the', 'and', 'or', 'for', 'with', 'from']]
                is_relevant = any(word in title_lower or word in body_lower for word in query_words) if query_words else True
                
                if is_relevant or len(relevant_results) < 3:
                    relevant_results.append(res)
            
            if not relevant_results:
                if attempt < 2:
                    time.sleep(2)
                    continue
                relevant_results = results[:3]
            
            formatted = []
            for i, res in enumerate(relevant_results[:10], 1):
                title = res.get('title', 'No title')
                body = res.get('body', 'No summary')
                href = res.get('href', 'No link')
                
                title = title.encode('utf-8', 'ignore').decode('utf-8').strip()
                body = body.encode('utf-8', 'ignore').decode('utf-8').strip()
                
                if not title or not body:
                    continue
                    
                formatted.append(f"{i}. {title}\n   {body[:200]}...\n   {href}")
            
            if formatted:
                return "Search Results (DuckDuckGo):\n" + "\n\n".join(formatted)
            else:
                return None
                
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                raise e
    
    return None


def _merge_search_results(results: list, query: str) -> str:
    """
    合并多个搜索源的结果
    
    Args:
        results: 搜索结果列表，每个元素包含 'source' 和 'content'
        query: 原始查询
        
    Returns:
        合并后的搜索结果文本
    """
    if not results:
        return "No search results found."
    
    # 如果只有一个结果，直接返回
    if len(results) == 1:
        return results[0]['content']
    
    # 合并多个结果
    merged_parts = []
    merged_parts.append(f"🔍 综合搜索结果 (来自 {len(results)} 个数据源):\n")
    merged_parts.append("=" * 60 + "\n\n")
    
    # 按优先级排序：Wikipedia > Tavily > DuckDuckGo
    source_priority = {'Wikipedia': 1, 'Tavily': 2, 'DuckDuckGo': 3}
    results_sorted = sorted(results, key=lambda x: source_priority.get(x['source'], 99))
    
    for i, result in enumerate(results_sorted, 1):
        source = result['source']
        content = result['content']
        
        merged_parts.append(f"【数据源 {i}: {source}】\n")
        merged_parts.append("-" * 60 + "\n")
        
        # 提取主要内容（去除标题和格式）
        if source == 'Wikipedia':
            # 维基百科结果已经格式化好了
            merged_parts.append(content)
        elif source == 'Tavily':
            # Tavily 结果也格式化好了
            merged_parts.append(content)
        else:
            # DuckDuckGo 结果
            merged_parts.append(content)
        
        merged_parts.append("\n\n")
    
    merged_parts.append("=" * 60 + "\n")
    merged_parts.append(f"💡 提示: 以上结果来自多个搜索源，请综合参考以获得最准确的信息。\n")
    
    return "".join(merged_parts)


def _search_with_wikipedia(query: str) -> str:
    """
    使用维基百科搜索（免费，不需要API key）
    
    优先使用维基百科，因为：
    - 内容准确、权威
    - 结构化信息
    - 免费，无限制
    - 特别适合查询指数成分股、公司信息等
    """
    if not WIKIPEDIA_AVAILABLE or wikipedia is None:
        raise Exception("维基百科不可用（未安装 wikipedia）")
    
    try:
        # 尝试搜索页面（增加搜索结果数量）
        search_results = wikipedia.search(query, results=5)
        
        if not search_results:
            return None
        
        # 尝试多个搜索结果，找到最相关的
        best_result = None
        for page_title in search_results:
            try:
                page = wikipedia.page(page_title, auto_suggest=False)
                
                # 获取页面摘要和主要内容
                summary = page.summary
                content = page.content[:5000]  # 增加内容长度
                
                # 检查内容是否相关（包含查询关键词）
                query_lower = query.lower()
                content_lower = (summary + content).lower()
                
                # 如果内容包含查询关键词，认为是相关结果
                if any(keyword in content_lower for keyword in query_lower.split() if len(keyword) > 2):
                    best_result = {
                        'title': page_title,
                        'summary': summary,
                        'content': content,
                        'url': page.url
                    }
                    break
                    
            except wikipedia.exceptions.DisambiguationError as e:
                # 如果有歧义，尝试使用第一个选项
                if e.options:
                    try:
                        page = wikipedia.page(e.options[0], auto_suggest=False)
                        summary = page.summary
                        content = page.content[:5000]
                        best_result = {
                            'title': e.options[0],
                            'summary': summary,
                            'content': content,
                            'url': page.url
                        }
                        break
                    except:
                        continue
                        
            except wikipedia.exceptions.PageError:
                continue
            except Exception as e:
                print(f"[Search] 维基百科获取页面 {page_title} 失败: {e}")
                continue
        
        # 如果没找到相关结果，使用第一个搜索结果
        if not best_result and search_results:
            try:
                page = wikipedia.page(search_results[0], auto_suggest=False)
                best_result = {
                    'title': search_results[0],
                    'summary': page.summary,
                    'content': page.content[:5000],
                    'url': page.url
                }
            except:
                return None
        
        if best_result:
            # 格式化结果
            result = f"""Wikipedia Results for "{best_result['title']}":

Summary:
{best_result['summary']}

Detailed Information:
{best_result['content']}

URL: {best_result['url']}"""
            return result
        
        return None
            
    except Exception as e:
        print(f"[Search] 维基百科搜索出错: {e}")
        return None


def _search_with_tavily(query: str) -> str:
    """
    使用 Tavily Search API 进行AI搜索
    
    Tavily 是一个专门为AI应用设计的搜索API，提供：
    - 更准确的搜索结果
    - 结构化的数据格式
    - 更好的上下文理解
    """
    if not TAVILY_API_KEY:
        raise Exception("Tavily API key not configured")
    
    if not TAVILY_AVAILABLE or TavilyClient is None:
        raise Exception("Tavily 客户端不可用（未安装 tavily-python）")
    
    try:
        client = TavilyClient(api_key=TAVILY_API_KEY)
        
        # 执行搜索
        response = client.search(
            query=query,
            search_depth="advanced",  # basic 或 advanced
            max_results=10,
            include_answer=True,  # 包含AI生成的答案摘要
            include_raw_content=False,  # 不包含原始内容（节省token）
        )
        
        # 格式化结果
        formatted = []
        
        # 如果有AI生成的答案，优先显示
        if response.get('answer'):
            formatted.append(f"📊 AI摘要:\n{response['answer']}\n")
        
        # 显示搜索结果
        results = response.get('results', [])
        if results:
            formatted.append("搜索结果:")
            for i, res in enumerate(results, 1):
                title = res.get('title', 'No title')
                content = res.get('content', 'No content')
                url = res.get('url', 'No link')
                score = res.get('score', 0)
                
                formatted.append(
                    f"{i}. {title} (相关性: {score:.2f})\n"
                    f"   {content[:200]}...\n"
                    f"   {url}"
                )
        else:
            formatted.append("未找到相关搜索结果。")
        
        return "\n\n".join(formatted)
        
    except Exception as e:
        error_msg = str(e) if e else "未知错误"
        error_type = type(e).__name__
        print(f"[Search] Tavily API 错误 ({error_type}): {error_msg}")
        
        # 如果是 API key 相关错误，给出更明确的提示
        if "api" in error_msg.lower() or "key" in error_msg.lower() or "auth" in error_msg.lower():
            print(f"[Search] 提示: 请检查 TAVILY_API_KEY 是否正确配置")
        
        raise Exception(f"Tavily API 错误: {error_msg}")

# ============================================
# 股价获取 - 多数据源策略
# ============================================

def _fetch_with_alpha_vantage(ticker: str):
    """优先方案：使用 Alpha Vantage API 获取实时股价"""
    print(f"  - Attempting Alpha Vantage API for {ticker}...")
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'GLOBAL_QUOTE',
            'symbol': ticker,
            'apikey': ALPHA_VANTAGE_API_KEY
        }
        response = requests.get(url, params=params, timeout=10)
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
            print(f"  - Alpha Vantage note: {data.get('Note') or data.get('Information')}")
        if 'Error Message' in data:
            print(f"  - Alpha Vantage error: {data['Error Message']}")
            
        return None
    except Exception as e:
        print(f"  - Alpha Vantage exception: {e}")
        return None

def _fetch_with_finnhub(ticker: str):
    """新增：使用 Finnhub API 获取实时股价"""
    if not finnhub_client:
        return None
    print(f"  - Attempting Finnhub API for {ticker}...")
    try:
        quote = finnhub_client.quote(ticker)
        if quote and quote.get('c') is not None and quote.get('c') != 0:
            price = quote['c']
            change = quote.get('d', 0.0)
            change_percent = quote.get('dp', 0.0)
            return f"{ticker} Current Price: ${price:.2f} | Change: ${change:.2f} ({change_percent:+.2f}%)"
        return None
    except Exception as e:
        print(f"  - Finnhub quote exception: {e}")
        return None

def _fetch_with_yfinance(ticker: str):
    """尝试使用 yfinance 获取价格"""
    print(f"  - Attempting yfinance for {ticker}...")
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
        print(f"  - yfinance exception: {e}")
        return None


def _fetch_with_twelve_data_price(ticker: str):
    """备用方案：使用 Twelve Data 获取实时价格"""
    if not TWELVE_DATA_API_KEY:
        return None
    print(f"  - Attempting Twelve Data for {ticker}...")
    try:
        params = {
            "symbol": ticker,
            "interval": "1day",
            "outputsize": 2,  # 最新两天计算涨跌幅
            "apikey": TWELVE_DATA_API_KEY,
            "order": "desc",
        }
        response = requests.get("https://api.twelvedata.com/time_series", params=params, timeout=10)
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
        print(f"  - Twelve Data price exception: {e}")
        return None

def _scrape_yahoo_finance(ticker: str):
    """备用方案：直接爬取 Yahoo Finance 页面"""
    print(f"  - Attempting to scrape Yahoo Finance for {ticker}...")
    try:
        url = f"https://finance.yahoo.com/quote/{ticker}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
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
        print(f"  - Yahoo scraping exception: {e}")
        return None


def _fetch_index_price(ticker: str):
    """
    指数专用：优先 yfinance.download 获取最近两日收盘，失败再用 Stooq/搜索兜底。
    """
    if not ticker.startswith('^'):
        return None
    print(f"  - Attempting index price via yfinance.download for {ticker}...")
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
        print(f"  - Index price via yfinance failed: {e}")
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
    print(f"  - Attempting to find price via search for {ticker}...")
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
                return f"{ticker} Current Price (via search): ${price}"
        
        return None
    except Exception as e:
        print(f"  - Search price exception: {e}")
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
        resp = requests.get(url, timeout=8)
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
        print(f"  - Stooq price exception: {e}")
        return None

def get_stock_price(ticker: str) -> str:
    """
    使用多数据源策略获取股票价格，以提高稳定性。
    策略顺序: Alpha Vantage -> Finnhub -> yfinance -> Twelve Data -> 网页抓取 -> Stooq(免Key) -> 搜索引擎解析
    """
    print(f"Fetching price for {ticker} with multi-source strategy...")
    is_index = ticker.startswith('^')
    if is_index:
        sources = [
            _fetch_index_price,
            _fetch_with_stooq_price,
            _search_for_price
        ]
    else:
        sources = [
            _fetch_with_alpha_vantage,
            _fetch_with_finnhub,  # 新增 Finnhub 作为高优先级源
            _fetch_with_yfinance,
            _fetch_with_twelve_data_price,
            _scrape_yahoo_finance,
            _fetch_with_stooq_price,
            _search_for_price
        ]
    
    for i, source_func in enumerate(sources, 1):
        try:
            result = source_func(ticker)
            if result:
                print(f"  OK source #{i} ({source_func.__name__})")
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
            print(f"  FAIL source #{i} ({source_func.__name__}) failed: {e}")
            continue
            
    return f"Error: All data sources failed to retrieve the price for {ticker}. Please try again later."

# ============================================
# 公司信息获取
# ============================================

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
                print(f"[Financials] ✅ 成功获取 {ticker} 损益表数据")
        except Exception as e:
            print(f"[Financials] 获取损益表失败: {e}")
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
                print(f"[Financials] ✅ 成功获取 {ticker} 资产负债表数据")
        except Exception as e:
            print(f"[Financials] 获取资产负债表失败: {e}")
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
                print(f"[Financials] ✅ 成功获取 {ticker} 现金流量表数据")
        except Exception as e:
            print(f"[Financials] 获取现金流量表失败: {e}")
            if not result['error']:
                result['error'] = f"获取现金流量表失败: {str(e)}"
        
        # 如果所有数据都获取失败，返回错误
        if not result['financials'] and not result['balance_sheet'] and not result['cashflow']:
            result['error'] = "无法获取任何财报数据，请检查股票代码是否正确"
        
        return result
        
    except Exception as e:
        print(f"[Financials] 获取财报数据失败: {e}")
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
        print(f"yfinance info fetch for '{ticker}' failed: {e}")

    # 方法2: Finnhub (新增)
    if finnhub_client:
        try:
            print(f"Trying Finnhub for company info: {ticker}")
            profile = finnhub_client.company_profile2(symbol=ticker)
            if profile and 'name' in profile:
                return f"""Company Profile ({ticker}):
- Name: {profile.get('name', 'Unknown')}
- Sector: {profile.get('finnhubIndustry', 'Unknown')}
- Market Cap: ${int(profile.get('marketCapitalization', 0) * 1_000_000):,}
- Website: {profile.get('weburl', 'N/A')}
- Description: Search online for more details.""" # Finnhub profile doesn't include a long description
        except Exception as e:
            print(f"Finnhub profile fetch failed: {e}")
    
    # 方法3: Alpha Vantage
    try:
        print(f"Trying Alpha Vantage for company info: {ticker}")
        url = "https://www.alphavantage.co/query"
        params = {'function': 'OVERVIEW', 'symbol': ticker, 'apikey': ALPHA_VANTAGE_API_KEY}
        response = requests.get(url, params=params, timeout=10)
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
        print(f"Alpha Vantage overview fetch failed: {e}")
    
    # 方法4: 网页搜索
    print(f"Falling back to web search for '{ticker}' company info")
    return search(f"{ticker} company profile stock information")

# ============================================
# 新闻获取
# ============================================

MARKET_INDICES = {
    "^GSPC": "S&P 500 index",
    "^IXIC": "Nasdaq Composite index", 
    "^DJI": "Dow Jones Industrial Average",
    "^RUT": "Russell 2000 index",
    "^VIX": "VIX volatility index",
    "^NYA": "NYSE Composite index",
    "^FTSE": "FTSE 100 index",
    "^N225": "Nikkei 225 index",
    "^HSI": "Hang Seng index"
}

def _is_market_index(ticker: str) -> bool:
    """判断ticker是否为市场指数"""
    # 方法1: 检查是否在已知指数列表中
    if ticker in MARKET_INDICES:
        return True
    
    # 方法2: 检查常见指数命名模式
    index_patterns = [
        r'^\^',      # 以 ^ 开头（Yahoo Finance指数标记）
        r'SPX$',     # S&P 500 的另一种写法
        r'NDX$',     # Nasdaq 100
        r'DJI$',     # Dow Jones
    ]
    
    for pattern in index_patterns:
        if re.match(pattern, ticker):
            return True
    
    return False

def _get_index_news(ticker: str) -> str:
    """
    专门为市场指数获取新闻的方法。
    策略：通过搜索获取宏观市场新闻和指数分析。
    """
    friendly_name = MARKET_INDICES.get(ticker, ticker.replace('^', ''))
    
    print(f"  → Detected market index: {friendly_name}")
    print(f"  → Using specialized search strategy for index news...")
    
    # 策略1: 搜索指数最近表现和分析
    current_date = datetime.now().strftime('%B %Y')
    search_queries = [
        f"{friendly_name} recent performance analysis {current_date}",
        f"{friendly_name} market news today",
        f"What's driving {friendly_name} this week"
    ]
    
    all_results = []
    for query in search_queries[:2]:  # 只用前2个查询，避免过多请求
        try:
            results = search(query)
            if results and "No search results" not in results:
                all_results.append(results)
            time.sleep(1)
        except Exception as e:
            print(f"  → Search failed for '{query}': {e}")
            continue
    
    if not all_results:
        return f"Unable to fetch recent news for {friendly_name}. Please check financial news sites manually."
    
    # 解析并格式化搜索结果
    combined_results = "\n\n".join(all_results)
    
    # 尝试从搜索结果中提取新闻标题和日期
    news_items = []
    lines = combined_results.split('\n')
    
    for i, line in enumerate(lines):
        # 寻找标题模式（通常以数字开头）
        if re.match(r'^\d+\.', line.strip()):
            title = line.strip()
            # 尝试找到日期信息
            date_match = re.search(r'(\d{1,2}\s+\w+\s+ago|\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2},?\s+\d{4})', 
                                  ' '.join(lines[i:i+3]), re.IGNORECASE)
            date_str = date_match.group(1) if date_match else 'Recent'
            news_items.append(f"[{date_str}] {title}")
            
            if len(news_items) >= 5:
                break
    
    if news_items:
        return f"Latest Market News & Analysis ({friendly_name}):\n" + "\n".join(news_items)
    else:
        # 如果无法提取结构化新闻，返回原始搜索摘要
        preview = combined_results[:800] + "..." if len(combined_results) > 800 else combined_results
        return f"Recent Market Context ({friendly_name}):\n{preview}"

def get_company_news(ticker: str) -> str:
    """
    智能获取新闻：自动识别是公司股票还是市场指数。
    - 公司股票：使用 API (yfinance, Finnhub, Alpha Vantage)
    - 市场指数：使用搜索策略获取宏观市场新闻
    """
    # 🔍 关键判断：这是指数还是公司股票？
    if _is_market_index(ticker):
        return _get_index_news(ticker)
    
    # --- 以下是原有的公司新闻获取逻辑 ---
    
    # 方法1: yfinance
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if news:
            news_list = []
            for i, article in enumerate(news[:5], 1):
                title = article.get('title', 'No title')
                publisher = article.get('publisher', 'Unknown source')
                pub_time = article.get('providerPublishTime', 0)
                date_str = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d') if pub_time else 'Unknown date'
                news_list.append(f"{i}. [{date_str}] {title} ({publisher})")
            return f"Latest News ({ticker}):\n" + "\n".join(news_list)
    except Exception as e:
        print(f"yfinance news error for {ticker}: {e}")

    # 方法2: Finnhub
    if finnhub_client:
        try:
            print(f"Trying Finnhub news for {ticker}")
            to_date = date.today().strftime("%Y-%m-%d")
            from_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
            news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
            if news:
                news_list = []
                for i, article in enumerate(news[:5], 1):
                    title = article.get('headline', 'No title')
                    source = article.get('source', 'Unknown')
                    pub_time = article.get('datetime', 0)
                    date_str = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d') if pub_time else 'Unknown'
                    news_list.append(f"{i}. [{date_str}] {title} ({source})")
                return f"Latest News ({ticker}):\n" + "\n".join(news_list)
        except Exception as e:
            print(f"Finnhub news fetch failed: {e}")

    # 方法3: Alpha Vantage
    try:
        print(f"Trying Alpha Vantage news for {ticker}")
        url = "https://www.alphavantage.co/query"
        params = {'function': 'NEWS_SENTIMENT', 'tickers': ticker, 'limit': 5, 'apikey': ALPHA_VANTAGE_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if 'feed' in data and data['feed']:
            news_list = []
            for i, article in enumerate(data['feed'][:5], 1):
                title = article.get('title', 'No title')
                source = article.get('source', 'Unknown')
                date_str = article.get('time_published', '')[:8]
                if date_str:
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                news_list.append(f"{i}. [{date_str}] {title} ({source})")
            return f"Latest News ({ticker}):\n" + "\n".join(news_list)
    except Exception as e:
        print(f"Alpha Vantage news fetch failed: {e}")
    
    # 方法4: 回退到公司特定搜索
    print(f"Falling back to search for {ticker} news")
    return search(f"{ticker} company latest news stock")

# ============================================
# 其他工具函数（保持不变或稍作修改）
# ============================================

def get_market_sentiment() -> str:
    """
    获取市场情绪指标 - CNN Fear & Greed Index
    使用更完整的请求头来模拟浏览器，提高成功率。
    """
    try:
        # 主要API地址
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        
        # 伪装成一个从CNN官网页面发出请求的真实浏览器
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            # 'Referer' 是最关键的头信息，告诉服务器请求的来源页面
            'Referer': 'https://www.cnn.com/markets/fear-and-greed',
            'Origin': 'https://www.cnn.com',
        }
        
        print("Attempting to fetch from CNN API with full headers...")
        response = requests.get(url, headers=headers, timeout=10)
        
        # 如果状态码不是 2xx，则会引发 HTTPError 异常
        response.raise_for_status() 
        
        data = response.json()
        score = float(data['fear_and_greed']['score'])
        rating = data['fear_and_greed']['rating']
        
        print("CNN API fetch successful!")
        return f"CNN Fear & Greed Index: {score:.1f} ({rating})"
    
    except requests.exceptions.HTTPError as http_err:
        print(f"CNN API failed with HTTP error: {http_err}. Trying fallback search...")
    except Exception as e:
        # 捕获其他所有可能的异常，例如网络问题、JSON解析错误等
        print(f"CNN API failed with other error: {e}. Trying fallback search...")
    # --- 如果上面的 try 代码块出现任何异常，则执行下面的回退逻辑 ---
    try:
        search_result = search("CNN Fear and Greed Index current value today")
        # 使用正则表达式从搜索结果中提取数值和评级
        match = re.search(r'(?:Index|Score)[:\s]*(\d+\.?\d*)\s*\((\w+\s?\w*)\)', search_result, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            rating = match.group(2)
            print("Fallback search successful!")
            return f"CNN Fear & Greed Index (via search): {score:.1f} ({rating})"
    except Exception as search_e:
        print(f"Search fallback also failed: {search_e}")
    
    # 如果所有方法都失败了，返回一个通用错误信息
    return "Fear & Greed Index: Unable to fetch. Please check manually."
def get_economic_events() -> str:
    """搜索当前月份的主要美国经济事件"""
    now = datetime.now()
    query = f"major upcoming US economic events {now.strftime('%B %Y')} (FOMC, CPI, jobs report)"
    return search(query)

def get_performance_comparison(tickers: dict) -> str:
    """比较字典中股票代码的年初至今和1年期表现"""
    data = {}
    for name, ticker in tickers.items():
        time.sleep(1) # 避免请求过于频繁
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2y")
            if hist.empty:
                print(f"Warning: No historical data for {ticker}")
                continue
            
            end_price = hist['Close'].iloc[-1]
            
            # YTD Performance
            start_of_year = datetime(datetime.now().year, 1, 1)
            ytd_hist = hist[hist.index.tz_localize(None) >= start_of_year]
            if ytd_hist.empty:
                perf_ytd = float('nan')
            else:
                start_price_ytd = ytd_hist['Close'].iloc[0]
                perf_ytd = ((end_price - start_price_ytd) / start_price_ytd) * 100
            
            # 1-Year Performance
            one_year_ago = datetime.now() - timedelta(days=365)
            one_year_hist = hist[hist.index.tz_localize(None) >= one_year_ago]
            if one_year_hist.empty:
                 perf_1y = float('nan')
            else:
                start_price_1y = one_year_hist['Close'].iloc[0]
                perf_1y = ((end_price - start_price_1y) / start_price_1y) * 100

            data[name] = {
                "Current": f"{end_price:,.2f}", 
                "YTD": f"{perf_ytd:+.2f}%" if not pd.isna(perf_ytd) else "N/A", 
                "1-Year": f"{perf_1y:+.2f}%" if not pd.isna(perf_1y) else "N/A"
            }
        except Exception as e:
            print(f"Error processing performance for '{ticker}': {e}")
            data[name] = {"Current": "N/A", "YTD": "N/A", "1-Year": "N/A"}
    
    if not data:
        return "Unable to fetch performance data for any ticker."
            
    header = f"{'Ticker':<25} {'Current Price':<15} {'YTD %':<12} {'1-Year %':<12}\n" + "-" * 67 + "\n"
    rows = [f"{name:<25} {metrics['Current']:<15} {metrics['YTD']:<12} {metrics['1-Year']:<12}" for name, metrics in data.items()]
    return "Performance Comparison:\n\n" + header + "\n".join(rows)

def analyze_historical_drawdowns(ticker: str = "^IXIC") -> str:
    """计算并报告过去20年的前3大历史回撤（已修复时区问题）"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="20y") # 延长至20年以捕获更多事件
        if hist.empty:
            return f"No historical data available for {ticker}."
        
        # --- 关键修复：移除索引的时区信息 ---
        hist.index = hist.index.tz_localize(None)
            
        hist['peak'] = hist['Close'].cummax()
        hist['drawdown'] = (hist['Close'] - hist['peak']) / hist['peak']
        
        # 找到所有回撤的谷底
        # 使用一个技巧来分组连续的回撤期
        drawdown_groups = hist[hist['drawdown'] < 0]
        if drawdown_groups.empty:
            return f"No significant drawdowns found for {ticker} in the last 20 years."
        # 找到每个回撤期内的最低点
        troughs = drawdown_groups.loc[drawdown_groups.groupby((drawdown_groups['drawdown'] == 0).cumsum())['drawdown'].idxmin()]
        top_3 = troughs.nsmallest(3, 'drawdown')
        if top_3.empty:
            return f"No significant drawdowns found for {ticker}."
        result = [f"Top 3 Historical Drawdowns for {ticker} (last 20y):\n"]
        for _, row in top_3.iterrows():
            trough_date = row.name
            # 找到这个谷底对应的峰值日期
            peak_price = row['peak']
            
            # 找到回撤开始的日期（即第一次达到峰值的日期）
            peak_date = hist[(hist.index <= trough_date) & (hist['Close'] == peak_price)].index.max()
            
            # 查找恢复日期（即谷底之后第一次回到峰值价格的日期）
            recovery_df = hist[hist.index > trough_date]
            recovery_date_series = recovery_df[recovery_df['Close'] >= peak_price].index
            recovery_date = recovery_date_series[0] if not recovery_date_series.empty else None
            
            duration = (trough_date - peak_date).days
            recovery_days = (recovery_date - trough_date).days if recovery_date else "Ongoing"
            result.append(
                f"- Drawdown: {row['drawdown']:.2%} (from {peak_date.strftime('%Y-%m-%d')} to {trough_date.strftime('%Y-%m-%d')})\n"
                f"  Duration to trough: {duration} days. Recovery time: {recovery_days} days."
            )
        return "\n".join(result)
    except Exception as e:
        return f"Historical analysis error: {e}."
def get_current_datetime() -> str:
    """返回当前日期和时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _fetch_with_yahoo_scrape_historical(ticker: str, period: str = "1y") -> dict:
    """
    策略 4: 改进的 Yahoo Finance 网页抓取（2024最新方法）
    使用多个备用URL和更完善的请求头
    """
    try:
        print(f"[get_stock_historical_data] 尝试从 Yahoo Finance 网页抓取 {ticker}...")
        
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
                
                response = requests.get(url, params=params, headers=headers, timeout=20, allow_redirects=True)
                
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
                        print(f"[get_stock_historical_data] Yahoo Finance 网页抓取成功，获取 {len(kline_data)} 条数据")
                        return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "yahoo_scrape"}
            except Exception as e:
                print(f"[get_stock_historical_data] Yahoo Finance URL {url} 失败: {e}")
                continue
        
        return None
    except Exception as e:
        print(f"[get_stock_historical_data] Yahoo Finance 网页抓取失败: {e}")
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
            
        print(f"[get_stock_historical_data] 尝试使用 IEX Cloud {ticker}...")
        
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
        
        response = requests.get(url, params=params, timeout=20)
        
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
                    print(f"[get_stock_historical_data] IEX Cloud 成功获取 {len(kline_data)} 条数据")
                    return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "iex_cloud"}
        
        return None
    except Exception as e:
        print(f"[get_stock_historical_data] IEX Cloud 失败: {e}")
        return None


def _fetch_with_tiingo(ticker: str, period: str = "1y") -> dict:
    """
    策略 5b: 使用 Tiingo API (免费额度: 每日500次)
    文档: https://api.tiingo.com/documentation/general/overview
    """
    try:
        if not TIINGO_API_KEY:
            return None
            
        print(f"[get_stock_historical_data] 尝试使用 Tiingo {ticker}...")
        
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
        
        response = requests.get(url, params=params, headers=headers, timeout=20)
        
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
                    print(f"[get_stock_historical_data] Tiingo 成功获取 {len(kline_data)} 条数据")
                    return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "tiingo"}
        elif response.status_code == 404:
            # Tiingo 可能不支持该ticker（如指数），返回None让其他数据源处理
            print(f"[get_stock_historical_data] Tiingo 不支持 {ticker}，跳过")
            return None
        
        return None
    except Exception as e:
        print(f"[get_stock_historical_data] Tiingo 失败: {e}")
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

        print(f"[get_stock_historical_data] 尝试使用 Twelve Data {ticker}...")

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
        response = requests.get("https://api.twelvedata.com/time_series", params=params, timeout=20)

        if response.status_code != 200:
            return None

        data = response.json()
        if data.get("status") != "ok":
            # status != ok 时通常返回 message
            message = data.get("message") or data.get("error")
            if message:
                print(f"[get_stock_historical_data] Twelve Data 状态异常: {message}")
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
            print(f"[get_stock_historical_data] Twelve Data 成功获取 {len(kline_data)} 条数据")
            return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "twelve_data", "as_of": as_of}

        return None
    except Exception as e:
        print(f"[get_stock_historical_data] Twelve Data 失败: {e}")
        return None


def _fetch_with_marketstack(ticker: str, period: str = "1y") -> dict:
    """
    策略 5d: 使用 Marketstack API (免费额度: 1000次/月)
    文档: https://marketstack.com/documentation
    """
    try:
        if not MARKETSTACK_API_KEY:
            return None
            
        print(f"[get_stock_historical_data] 尝试使用 Marketstack {ticker}...")
        
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
        
        response = requests.get(url, params=params, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                print(f"[get_stock_historical_data] Marketstack 错误: {data['error']}")
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
                    print(f"[get_stock_historical_data] Marketstack 成功获取 {len(kline_data)} 条数据")
                    return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "marketstack"}
        
        return None
    except Exception as e:
        print(f"[get_stock_historical_data] Marketstack 失败: {e}")
        return None


def _fetch_with_massive_io(ticker: str, period: str = "1y") -> dict:
    """
    策略 5e: 使用 Massive.com (原 Polygon.io) API
    """
    try:
        if not MASSIVE_API_KEY:
            print(f"[get_stock_historical_data] Massive.com API key 未配置")
            return None
            
        print(f"[get_stock_historical_data] 尝试使用 Massive.com {ticker}...")
        
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
        
        response = requests.get(url, params=params, headers=headers, timeout=20)
        
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
                        print(f"[get_stock_historical_data] Massive.com 成功获取 {len(kline_data)} 条数据")
                        return {"kline_data": kline_data, "period": period, "interval": "1d", "source": "massive"}
            else:
                error_msg = data.get('error', data.get('status', 'unknown'))
                print(f"[get_stock_historical_data] Massive.com 返回空数据或错误: {error_msg}")
                if 'error' in data:
                    print(f"[get_stock_historical_data] 错误详情: {data.get('error')}")
        else:
            error_text = response.text[:500] if response.text else "No response body"
            print(f"[get_stock_historical_data] Massive.com HTTP 错误: {response.status_code}")
            print(f"[get_stock_historical_data] 响应内容: {error_text}")
            # 尝试解析 JSON 错误信息
            try:
                error_data = response.json()
                if 'error' in error_data:
                    print(f"[get_stock_historical_data] API 错误: {error_data['error']}")
            except:
                pass
        
        return None
    except Exception as e:
        print(f"[get_stock_historical_data] Massive.com 失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def _map_to_stooq_symbol(ticker: str) -> Optional[str]:
    upper = ticker.upper()
    mapping = {
        "^IXIC": "^ndq",
        "^GSPC": "^spx",
        "^DJI": "^dji",
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
        resp = requests.get(url, timeout=8)
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
                data.append(
                    {
                        "time": f"{row[date_key]} 00:00",
                        "open": float(row[open_key]),
                        "high": float(row[high_key]),
                        "low": float(row[low_key]),
                        "close": float(row[close_key]),
                        "volume": float(row.get(volume_key) or 0),
                    }
                )
            except Exception:
                continue

        if data:
            print(f"[get_stock_historical_data] Stooq 成功获取 {len(data)} 条数据")
            # 如果请求的是小时视图，但只拿到日线，用最近若干日收盘生成伪“小时”序列，保证有变化
            if interval.endswith("h"):
                # 取最近10个交易日的收盘，标记为当日 16:00
                recent = data[-10:]
                hourly_like = []
                for row in recent:
                    hourly_like.append({
                        "time": row["time"].split()[0] + " 16:00",
                        "open": row["close"],
                        "high": row["close"],
                        "low": row["close"],
                        "close": row["close"],
                        "volume": row.get("volume", 0.0),
                    })
                return {"kline_data": hourly_like, "period": period, "interval": "1h", "source": "stooq_intraday_stub"}
            return {"kline_data": data, "period": period, "interval": "1d", "source": "stooq"}
        return None
    except Exception as e:
        print(f"[get_stock_historical_data] Stooq 失败: {e}")
        return None


def _fallback_price_value(ticker: str) -> Optional[float]:
    """
    简单兜底：尝试用 stooq 价格接口或搜索提取一个最新价，用于生成平滑序列。
    """
    try:
        symbol = _map_to_stooq_symbol(ticker)
        if symbol:
            url = f"https://stooq.pl/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=json"
            resp = requests.get(url, timeout=6)
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
            return float(m.group(1).replace(",", ""))
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
            print(f"[get_stock_historical_data] Stooq 指数兜底命中 {ticker}，返回日线数据")
            return stooq_result

    # 策略 0: 优先使用 yfinance（最可靠，支持股票和指数）
    # 使用 session 和重试机制，避免速率限制
    max_retries = 1  # 限流严重时快速跳过
    for attempt in range(max_retries):
        try:
            print(f"[get_stock_historical_data] 尝试使用 yfinance {ticker} (尝试 {attempt + 1}/{max_retries})...")
            
            # 创建新的 session，避免缓存问题
            import yfinance as yf_local
            stock = yf_local.Ticker(ticker, session=None)  # 不使用缓存
            
            # 对于指数，使用不同的参数
            if ticker.startswith('^'):
                # 指数数据
                hist = stock.history(period=period, interval=interval, timeout=30, raise_errors=True)
            else:
                # 股票数据
                hist = stock.history(period=period, interval=interval, timeout=30, raise_errors=True)
            
            if not hist.empty and len(hist) > 0:
                data = []
                for index, row in hist.iterrows():
                    # 处理日期格式
                    if hasattr(index, 'strftime'):
                        time_str = index.strftime('%Y-%m-%d')
                    elif hasattr(index, 'date'):
                        time_str = index.date().strftime('%Y-%m-%d')
                    else:
                        time_str = str(index)[:10]
                    
                    data.append({
                        "time": f"{time_str} 00:00",
                        "open": float(row['Open']),
                        "high": float(row['High']),
                        "low": float(row['Low']),
                        "close": float(row['Close']),
                        "volume": float(row.get('Volume', 0)) if 'Volume' in row else 0,
                    })
                
                if data:
                    print(f"[get_stock_historical_data] ✅ yfinance 成功获取 {len(data)} 条数据 (来源: yfinance)")
                    return {"kline_data": data, "period": period, "interval": interval, "source": "yfinance"}
        except Exception as e:
            error_msg = str(e)
            if "Too Many Requests" in error_msg or "Rate limited" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[get_stock_historical_data] yfinance 速率限制，等待 {wait_time} 秒后重试...")
                    import time as time_module
                    time_module.sleep(wait_time)
                    continue
            print(f"[get_stock_historical_data] yfinance 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
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
            response = requests.get(url, params=params, timeout=15)
            data = response.json()
            
            # 检查是否有错误信息
            if "Error Message" in data:
                error_msg = data.get('Error Message', 'Unknown error')
                print(f"[get_stock_historical_data] Alpha Vantage 返回错误: {error_msg}")
                raise Exception(f"Alpha Vantage API error: {error_msg}")
            
            # 检查是否有速率限制提示
            if "Note" in data:
                note = data.get('Note', '')
                if "API call frequency" in note or "rate limit" in note.lower():
                    print(f"[get_stock_historical_data] Alpha Vantage 速率限制: {note}")
                    raise Exception("Alpha Vantage rate limit")
                else:
                    print(f"[get_stock_historical_data] Alpha Vantage 提示: {note}")
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
                print(f"[get_stock_historical_data] Alpha Vantage 成功获取 {len(kline_data)} 条数据")
                return {"kline_data": kline_data, "period": period, "interval": interval}
        except Exception as e:
            print(f"[get_stock_historical_data] Alpha Vantage 失败: {e}，尝试 yfinance...")
    
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
                    print(f"[get_stock_historical_data] yfinance 返回空数据，重试 {attempt + 1}/{max_retries}...")
                    time.sleep(2 ** attempt)  # 指数退避
                    continue
                return {"error": f"No historical data for {ticker}"}

            # 转换格式以匹配 ECharts 的要求
            data = []
            for index, row in hist.iterrows():
                # 处理不同的时间索引类型
                if hasattr(index, 'strftime'):
                    time_str = index.strftime('%Y-%m-%d')
                elif hasattr(index, 'date'):
                    time_str = index.date().strftime('%Y-%m-%d')
                else:
                    time_str = str(index)[:10]  # 取前10个字符作为日期
                
                data.append({
                    "time": f"{time_str} 00:00",
                    "open": float(row['Open']),
                    "high": float(row['High']),
                    "low": float(row['Low']),
                    "close": float(row['Close']),
                    "volume": float(row.get('Volume', 0)) if 'Volume' in row else 0,
                })
            
            print(f"[get_stock_historical_data] yfinance 成功获取 {len(data)} 条数据")
            return {"kline_data": data, "period": period, "interval": interval}
        except Exception as e:
            error_msg = str(e)
            if "Too Many Requests" in error_msg or "Rate limited" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[get_stock_historical_data] yfinance 速率限制，等待 {wait_time} 秒后重试...")
                    import time as time_module
                    time_module.sleep(wait_time)
                    continue
            # 如果不是速率限制错误，或者已经重试完，继续到下一个策略
            print(f"[get_stock_historical_data] yfinance 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
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
                print(f"[get_stock_historical_data] Finnhub 成功获取 {len(kline_data)} 条数据")
                return {"kline_data": kline_data, "period": period, "interval": interval}
        except Exception as e2:
            print(f"[get_stock_historical_data] Finnhub 也失败: {e2}")
    
    # 策略 4: 尝试从 Yahoo Finance 网页直接抓取（对指数代码特别有效）
    try:
        result = _fetch_with_yahoo_scrape_historical(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e3:
        print(f"[get_stock_historical_data] Yahoo Finance 网页抓取失败: {e3}")
    
    # 对于指数代码，优先使用 yfinance（即使之前失败，再试一次，因为指数可能支持）
    if ticker.startswith('^'):
        print(f"[get_stock_historical_data] 检测到指数代码 {ticker}，尝试使用 yfinance 专门获取指数数据...")
        try:
            # 对于指数，yfinance 通常支持，但可能需要特殊处理
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period, interval=interval, timeout=20)
            
            if not hist.empty:
                data = []
                for index, row in hist.iterrows():
                    if hasattr(index, 'strftime'):
                        time_str = index.strftime('%Y-%m-%d')
                    elif hasattr(index, 'date'):
                        time_str = index.date().strftime('%Y-%m-%d')
                    else:
                        time_str = str(index)[:10]
                    
                    data.append({
                        "time": f"{time_str} 00:00",
                        "open": float(row['Open']),
                        "high": float(row['High']),
                        "low": float(row['Low']),
                        "close": float(row['Close']),
                        "volume": float(row.get('Volume', 0)),
                    })
                
                if data:
                    print(f"[get_stock_historical_data] yfinance 成功获取指数 {ticker} 的 {len(data)} 条数据")
                    return {"kline_data": data, "period": period, "interval": interval, "source": "yfinance_index"}
        except Exception as e_index:
            print(f"[get_stock_historical_data] yfinance 获取指数数据失败: {e_index}")
    
    # 策略 5a: 尝试使用 IEX Cloud (免费额度大，优先使用)
    try:
        result = _fetch_with_iex_cloud(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4a:
        print(f"[get_stock_historical_data] IEX Cloud 失败: {e4a}")
    
    # 策略 5b: 尝试使用 Tiingo (免费额度: 每日500次)
    try:
        result = _fetch_with_tiingo(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4b:
        print(f"[get_stock_historical_data] Tiingo 失败: {e4b}")
    
    # 策略 5c: 尝试使用 Twelve Data (免费额度)
    try:
        result = _fetch_with_twelve_data(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4c:
        print(f"[get_stock_historical_data] Twelve Data 失败: {e4c}")
    
    # 策略 5d: 尝试使用 Marketstack (免费额度: 1000次/月)
    try:
        result = _fetch_with_marketstack(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4d:
        print(f"[get_stock_historical_data] Marketstack 失败: {e4d}")
    
    # 策略 5e: 尝试使用 Massive.com (原 Polygon.io)
    try:
        result = _fetch_with_massive_io(ticker, period)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4e:
        print(f"[get_stock_historical_data] Massive.com 失败: {e4e}")

    # 策略 5f: 尝试 Stooq 免 Key 回退
    try:
        result = _fetch_with_stooq_history(ticker, period, interval)
        if result and "kline_data" in result and len(result["kline_data"]) > 0:
            return result
    except Exception as e4f:
        print(f"[get_stock_historical_data] Stooq 失败: {e4f}")

    # 策略 6: 最后尝试 - 使用 yfinance 的备用方法（不通过 Ticker，直接下载）
    # 等待一段时间后再尝试，避免速率限制
    import time as time_module
    time_module.sleep(2)  # 等待2秒，避免速率限制
    
    try:
        print(f"[get_stock_historical_data] 尝试 yfinance 备用方法（等待后重试）...")
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
            data = []
            for index, row in hist.iterrows():
                if hasattr(index, 'strftime'):
                    time_str = index.strftime('%Y-%m-%d')
                elif hasattr(index, 'date'):
                    time_str = index.date().strftime('%Y-%m-%d')
                else:
                    time_str = str(index)[:10]
                
                data.append({
                    "time": f"{time_str} 00:00",
                    "open": float(row['Open']),
                    "high": float(row['High']),
                    "low": float(row['Low']),
                    "close": float(row['Close']),
                    "volume": float(row.get('Volume', 0)) if 'Volume' in row else 0,
                })
            
            if data:
                print(f"[get_stock_historical_data] yfinance 备用方法成功获取 {len(data)} 条数据")
                return {"kline_data": data, "period": period, "interval": interval}
    except Exception as e5:
        print(f"[get_stock_historical_data] yfinance 备用方法失败: {e5}")
    
    # 所有策略都失败，如果是指数，尝试使用最新价格生成平滑序列
    if is_index:
        price_val = _fallback_price_value(ticker)
        if price_val:
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
                print(f"[get_stock_historical_data] 使用 price fallback 为 {ticker} 生成逐小时序列")
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
                print(f"[get_stock_historical_data] 使用 price fallback 为 {ticker} 生成平滑序列")
                return {"kline_data": data, "period": period, "interval": "1d", "source": "price_fallback"}

    # 所有策略都失败，返回错误
    return {"error": f"Failed to fetch historical data for {ticker}: All data sources failed. Please try again later or check your internet connection."}

