import yfinance as yf
import json
from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
import time
import re


def get_stock_price(ticker: str) -> str:
    time.sleep(1)  # Rate limit fix
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            raise ValueError("Empty hist")
        current_price = hist['Close'].iloc[-1]
        info = stock.info
        prev_close = info.get('previousClose', current_price)  # Fallback to current if 0
        if prev_close == 0:
            raise ValueError("No prev_close")
        change = current_price - prev_close
        change_percent = (change / prev_close) * 100
        return f"Current price for {ticker}: ${current_price:.2f} | Change: ${change:.2f} ({change_percent:+.2f}%)"
    except Exception as e:
        return f"Error fetching price for {ticker}: {str(e)}. Fallback: Use search."

def get_company_news(ticker: str) -> str:
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        now = datetime.now().timestamp()
        recent_news = [n for n in news if n.get('providerPublishTime', 0) > now - 30*24*3600][:5]
        if not recent_news:
            return search(f"recent news {ticker} last 30 days")  # Fallback
        news_list = []
        for i, article in enumerate(recent_news, 1):
            news_list.append(f"{i}. {article.get('title', 'No title')} ({article.get('publisher', 'Unknown')})")
        return "Latest News:\n" + "\n".join(news_list)
    except Exception as e:
        return search(f"recent news {ticker}")

def get_company_info(ticker: str) -> str:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info:
            raise ValueError("No info")
        result = f"""Company Profile for {ticker}:
- Name: {info.get('longName', 'N/A')}
- Sector: {info.get('sector', 'N/A')}
- Industry: {info.get('industry', 'N/A')}
- Market Cap: ${info.get('marketCap', 0):,.0f}
- P/E Ratio: {info.get('trailingPE', 'N/A')}
- Forward P/E: {info.get('forwardPE', 'N/A')}
- Description: {info.get('longBusinessSummary', 'N/A')[:200]}..."""
        return result
    except Exception as e:
        return search(f"company profile {ticker}")

def search(query: str) -> str:
    for _ in range(2):  # Retry
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=10))
            if not results:
                return "No search results found."
            formatted = []
            for i, res in enumerate(results, 1):
                body = res.get('body') or res.get('snippet', 'No snippet')
                formatted.append(f"{i}. {res.get('title', 'No title')}\n   {body[:150]}...\n   {res.get('href', 'No link')}")
            return "Search Results:\n" + "\n\n".join(formatted)
        except:
            time.sleep(2)
    return f"Search error: Max retries exceeded."

def get_market_sentiment() -> str:
    today = date.today().strftime("%Y-%m-%d")
    try:
        url = f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{today}"
        response = requests.get(url, timeout=15)
        data = response.json()['fear_and_greed']['data'][-1]  # Latest
        score = data['score']
        rating = data['rating']  # e.g., "Fear"
        return f"CNN Fear & Greed Index: {score} ({rating})"
    except Exception as e:
        return f"Fear & Greed Index unavailable: {str(e)}"

def get_economic_events() -> str:
    now = datetime.now()
    query = f"major upcoming US economic events {now.year} {now.strftime('%B %Y')} (FOMC, CPI, retail sales, GDP)"
    raw = search(query)
    # Simple parse: extract dates like "10/15"
    events = re.findall(r'(\d{1,2}/\d{1,2}):?\s*([A-Z]{3,})', raw)
    return f"Parsed Events: {events}\nFull: {raw}"

def get_performance_comparison(tickers: dict) -> str:
    try:
        data = {}
        for name, ticker in tickers.items():
            time.sleep(1)
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="2y")  # Ensure full YTD
                if hist.empty:
                    print(f"No data for {ticker}")
                    continue
                end_price = hist['Close'].iloc[-1]
                current_year = hist.index[-1].year
                ytd_data = hist[hist.index.year == current_year]
                if not ytd_data.empty:
                    ytd_start = ytd_data['Close'].iloc[0]
                    perf_ytd = ((end_price - ytd_start) / ytd_start) * 100
                else:
                    perf_ytd = 0.0
                # 1y using approx 252 trading days
                if len(hist) >= 252:
                    one_year_ago = hist['Close'].shift(252).dropna().iloc[-1]
                    perf_1y = ((end_price - one_year_ago) / one_year_ago) * 100
                else:
                    perf_1y = 0.0
                data[name] = {
                    "Current": f"{end_price:.2f}",
                    "YTD": f"{perf_ytd:+.2f}%",
                    "1-Year": f"{perf_1y:+.2f}%"
                }
            except Exception as e:
                print(f"Error processing {ticker}: {e}")
                continue
        if not data:
            return "Could not fetch performance data for any ticker."
        result = "Performance Comparison:\n\n"
        result += f"{'Index':<25} {'Current':<12} {'YTD':<12} {'1-Year':<12}\n"
        result += "-" * 65 + "\n"
        for name, metrics in data.items():
            result += f"{name:<25} {metrics['Current']:<12} {metrics['YTD']:<12} {metrics['1-Year']:<12}\n"
        return result
    except Exception as e:
        return f"Performance comparison error: {str(e)}"

def analyze_historical_drawdowns(ticker: str = "^IXIC") -> str:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="10y")  # Faster than max
        if hist.empty:
            return f"No historical data for {ticker}."
        hist['cummax'] = hist['Close'].cummax()
        hist['drawdown'] = (hist['Close'] - hist['cummax']) / hist['cummax']
        drawdowns = []
        in_drawdown = False
        start_date = None
        peak_val = 0
        min_val = 0
        for i in range(len(hist)):
            current_dd = hist['drawdown'].iloc[i]
            current_close = hist['Close'].iloc[i]
            current_cummax = hist['cummax'].iloc[i]
            current_date = hist.index[i]
            if current_dd < 0 and not in_drawdown:
                in_drawdown = True
                start_date = current_date
                peak_val = current_cummax
                min_val = current_close
            elif current_dd < 0 and in_drawdown:
                if current_close < min_val:
                    min_val = current_close
            elif current_dd == 0 and in_drawdown:
                in_drawdown = False
                end_date = current_date
                drawdowns.append({
                    "start": start_date,
                    "end": end_date,
                    "peak": peak_val,
                    "trough": min_val,
                    "drawdown": (min_val - peak_val) / peak_val,
                    "recovery_days": (end_date - start_date).days
                })
        # Handle ongoing drawdown
        if in_drawdown:
            drawdowns.append({
                "start": start_date,
                "end": None,
                "peak": peak_val,
                "trough": min_val,
                "drawdown": (min_val - peak_val) / peak_val,
                "recovery_days": "Ongoing"
            })
        if not drawdowns:
            return f"No significant drawdowns found for {ticker}."
        top_3 = sorted(drawdowns, key=lambda x: x['drawdown'])[:3]
        result = [f"Top 3 Historical Drawdowns for {ticker}:\n"]
        for i, dd in enumerate(top_3, 1):
            result.append(
                f"{i}. {dd['start'].year} Crash: Max Drawdown {dd['drawdown']:.2%} | "
                f"Recovery: {dd['recovery_days']} days ({dd['start'].strftime('%Y-%m-%d')} to {dd['end'].strftime('%Y-%m-%d') if dd['end'] else 'Ongoing'})"
            )
        return "\n".join(result)
    except Exception as e:
        return f"Historical analysis error: {str(e)}. Use search for historical drawdowns."

def get_current_datetime() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")