import yfinance as yf
import json
from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
import time
import re
import finnhub  # 新增
import pandas as pd # 新增

# ============================================
# API配置
# ============================================
ALPHA_VANTAGE_API_KEY = "QE084WG39H15OX1X"
FINNHUB_API_KEY = "d3uf9opr01qil4apq1ogd3uf9opr01qil4apq1p0" 

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
    使用 DuckDuckGo 执行网页搜索并格式化结果。
    失败时会重试一次。
    """
    for attempt in range(2):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=10))
            
            if not results:
                return "No search results found."
            
            formatted = []
            for i, res in enumerate(results, 1):
                title = res.get('title', 'No title').encode('utf-8', 'ignore').decode('utf-8')
                body = res.get('body', 'No summary').encode('utf-8', 'ignore').decode('utf-8')
                href = res.get('href', 'No link')
                formatted.append(f"{i}. {title}\n   {body[:150]}...\n   {href}")
                
            return "Search Results:\n" + "\n\n".join(formatted)
        except Exception as e:
            print(f"Search attempt {attempt + 1} failed: {e}. Retrying in 2 seconds...")
            time.sleep(2)
            
    return "Search error: Exceeded maximum retries."

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

def get_stock_price(ticker: str) -> str:
    """
    使用多数据源策略获取股票价格，以提高稳定性。
    策略顺序: Alpha Vantage -> Finnhub -> yfinance -> 网页抓取 -> 搜索引擎解析
    """
    print(f"Fetching price for {ticker} with multi-source strategy...")
    sources = [
        _fetch_with_alpha_vantage,
        _fetch_with_finnhub,  # 新增 Finnhub 作为高优先级源
        _fetch_with_yfinance,
        _scrape_yahoo_finance,
        _search_for_price
    ]
    
    for i, source_func in enumerate(sources, 1):
        try:
            result = source_func(ticker)
            if result:
                print(f"  ✓ Success with source #{i} ({source_func.__name__})!")
                return result
            time.sleep(0.5)
        except Exception as e:
            print(f"  ✗ Source #{i} ({source_func.__name__}) failed: {e}")
            continue
            
    return f"Error: All data sources failed to retrieve the price for {ticker}. Please try again later."

# ============================================
# 公司信息获取
# ============================================

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

def get_company_news(ticker: str) -> str:
    """
    使用多种方法获取公司新闻。
    优先使用 yfinance，失败后尝试 Finnhub, Alpha Vantage，最后回退到搜索。
    """
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

    # 方法2: Finnhub (新增)
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
    
    # 方法4: 网页搜索
    print(f"Falling back to search for {ticker} news")
    return search(f"{ticker} latest news stock")

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

