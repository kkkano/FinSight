import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from email.utils import parsedate_to_datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yfinance as yf

from .env import ALPHA_VANTAGE_API_KEY, finnhub_client
from .http import _http_get
from .search import search
from .utils import _normalize_published_date

logger = logging.getLogger(__name__)

# ── RSS-dedicated lightweight session ────────────────────────────
_RSS_SESSION: Optional[requests.Session] = None
_RSS_TIMEOUT = int(os.getenv("FINSIGHT_RSS_TIMEOUT", "4"))
_RSS_MAX_RETRIES = int(os.getenv("FINSIGHT_RSS_MAX_RETRIES", "1"))
_MAX_RSS_FEEDS = int(os.getenv("FINSIGHT_MAX_RSS_FEEDS", "6"))


def _get_rss_session() -> requests.Session:
    """Lightweight session: 1 retry, short timeout, no aggressive backoff."""
    global _RSS_SESSION
    if _RSS_SESSION is not None:
        return _RSS_SESSION
    retry = Retry(
        total=_RSS_MAX_RETRIES,
        backoff_factor=0.1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "FinSight/1.0 NewsBot"})
    _RSS_SESSION = session
    return session


def _rss_get(url: str, timeout: int = _RSS_TIMEOUT) -> requests.Response:
    """HTTP GET using the lightweight RSS session."""
    return _get_rss_session().get(url, timeout=timeout)

NEWS_TAG_RULES = [
    ("科技", ["tech", "technology", "software", "hardware", "cloud", "cyber", "科技", "软件", "硬件", "云", "数据中心", "互联网"]),
    ("AI", ["ai", "artificial intelligence", "genai", "大模型", "生成式", "人工智能", "AIGC"]),
    ("半导体", ["semiconductor", "chip", "foundry", "tsmc", "asml", "nvidia", "半导体", "芯片", "晶圆", "光刻"]),
    ("军事", ["military", "defense", "missile", "army", "navy", "weapon", "drone", "军事", "国防", "导弹", "战机", "无人机", "武器"]),
    ("能源", ["oil", "crude", "gas", "lng", "opec", "能源", "石油", "原油", "天然气", "煤炭", "电力"]),
    ("宏观", ["cpi", "ppi", "gdp", "pmi", "fomc", "inflation", "jobs", "payroll", "宏观", "经济", "利率", "通胀", "就业", "非农", "央行"]),
    ("金融", ["bank", "banking", "credit", "bond", "yield", "金融", "银行", "债券", "收益率", "信贷"]),
    ("监管", ["regulator", "regulation", "antitrust", "sec", "doj", "监管", "反垄断", "制裁", "罚款"]),
    ("并购", ["merger", "acquisition", "buyout", "deal", "并购", "收购", "合并", "交易", "要约"]),
    ("财报", ["earnings", "guidance", "revenue", "profit", "业绩", "财报", "营收", "利润", "指引"]),
    ("加密", ["crypto", "bitcoin", "ethereum", "blockchain", "加密", "比特币", "以太坊", "区块链"]),
    ("汽车", ["ev", "electric vehicle", "automotive", "auto", "汽车", "电动车", "新能源车"]),
    ("消费", ["consumer", "retail", "e-commerce", "消费", "零售", "电商"]),
    ("医药", ["pharma", "biotech", "drug", "医疗", "医药", "生物", "疫苗"]),
    ("地产", ["real estate", "property", "housing", "地产", "楼市"]),
    ("地缘", ["geopolitical", "geopolitics", "war", "conflict", "sanction", "地缘", "冲突", "战争"]),
    ("中国", ["china", "chinese", "中国", "大陆"]),
    ("美国", ["united states", "u.s.", "美国", "白宫", "华盛顿"]),
]

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

def _is_reasonable_headline(text: str, window: str = "") -> bool:
    """简单过滤：需要日期/时间线索，避免百科/介绍类条目。"""
    combined = (window or "") + " " + text
    has_date = re.search(
        r"(\d{4}-\d{2}-\d{2}|\b20\d{2}\b|\b\d{1,2}\s+(hours?|days?)\s+ago\b)",
        combined,
        re.IGNORECASE,
    )
    if not has_date:
        return False
    lowered = combined.lower()
    if "wall street journal" in lowered:
        return False
    return True



def _get_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default



def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))



def _headline_is_useful(title: str, snippet: str = "") -> bool:
    combined = f"{title} {snippet}".strip()
    if not combined:
        return False
    min_chars = _get_env_int("NEWS_MIN_TITLE_CHARS", 10)
    min_words = _get_env_int("NEWS_MIN_TITLE_WORDS", 4)
    if min_chars <= 0 and min_words <= 0:
        return True

    compact = re.sub(r"\s+", "", combined)
    if _contains_cjk(combined):
        if min_chars <= 0:
            return True
        return len(compact) >= min_chars

    word_count = len(re.findall(r"[A-Za-z0-9]+", combined))
    if min_words > 0 and min_chars > 0:
        return not (word_count < min_words and len(compact) < min_chars)
    if min_words > 0:
        return word_count >= min_words
    if min_chars > 0:
        return len(compact) >= min_chars
    return True


NEWS_TAG_RULES = [
    ("科技", ["tech", "technology", "software", "hardware", "cloud", "cyber", "科技", "软件", "硬件", "云", "数据中心", "互联网"]),
    ("AI", ["ai", "artificial intelligence", "genai", "大模型", "生成式", "人工智能", "AIGC"]),
    ("半导体", ["semiconductor", "chip", "foundry", "tsmc", "asml", "nvidia", "半导体", "芯片", "晶圆", "光刻"]),
    ("军事", ["military", "defense", "missile", "army", "navy", "weapon", "drone", "军事", "国防", "导弹", "战机", "无人机", "武器"]),
    ("能源", ["oil", "crude", "gas", "lng", "opec", "能源", "石油", "原油", "天然气", "煤炭", "电力"]),
    ("宏观", ["cpi", "ppi", "gdp", "pmi", "fomc", "inflation", "jobs", "payroll", "宏观", "经济", "利率", "通胀", "就业", "非农", "央行"]),
    ("金融", ["bank", "banking", "credit", "bond", "yield", "金融", "银行", "债券", "收益率", "信贷"]),
    ("监管", ["regulator", "regulation", "antitrust", "sec", "doj", "监管", "反垄断", "制裁", "罚款"]),
    ("并购", ["merger", "acquisition", "buyout", "deal", "并购", "收购", "合并", "交易", "要约"]),
    ("财报", ["earnings", "guidance", "revenue", "profit", "业绩", "财报", "营收", "利润", "指引"]),
    ("加密", ["crypto", "bitcoin", "ethereum", "blockchain", "加密", "比特币", "以太坊", "区块链"]),
    ("汽车", ["ev", "electric vehicle", "automotive", "auto", "汽车", "电动车", "新能源车"]),
    ("消费", ["consumer", "retail", "e-commerce", "消费", "零售", "电商"]),
    ("医药", ["pharma", "biotech", "drug", "医疗", "医药", "生物", "疫苗"]),
    ("地产", ["real estate", "property", "housing", "地产", "楼市"]),
    ("地缘", ["geopolitical", "geopolitics", "war", "conflict", "sanction", "地缘", "冲突", "战争"]),
    ("中国", ["china", "chinese", "中国", "大陆"]),
    ("美国", ["united states", "u.s.", "美国", "白宫", "华盛顿"]),
]



def _keyword_match(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    kw = keyword.lower()
    if _contains_cjk(kw):
        return kw in text
    if len(kw) <= 3 and kw.isalpha():
        return re.search(rf"\b{re.escape(kw)}\b", text) is not None
    return kw in text



def _headline_tags(text: str) -> List[str]:
    if not text:
        return []
    text_lower = text.lower()
    max_tags = max(1, _get_env_int("NEWS_TAG_MAX", 3))
    tags: List[str] = []
    for tag, keywords in NEWS_TAG_RULES:
        if any(_keyword_match(text_lower, kw) for kw in keywords):
            tags.append(tag)
            if len(tags) >= max_tags:
                break
    return tags



def _format_headline_line(
    date_str: str,
    title: str,
    source: str,
    url: str = "",
    snippet: str = "",
) -> str:
    tags = _headline_tags(f"{title} {snippet}".strip())
    tag_text = f"[{'/'.join(tags)}] " if tags else ""
    clean_title = (title or "").strip() or "Untitled"
    display_title = f"[{clean_title}]({url})" if url else clean_title
    clean_source = (source or "").strip()
    source_text = f"({clean_source})" if clean_source else ""
    clean_snippet = (snippet or "").strip()
    if len(clean_snippet) > 160:
        clean_snippet = clean_snippet[:157] + "..."
    snippet_text = f" - {clean_snippet}" if clean_snippet else ""
    return f"[{date_str}] {tag_text}{display_title} {source_text}{snippet_text}".strip()


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or ""
        return host.replace("www.", "")
    except Exception:
        return ""



def _extract_datetime_from_text(text: str, now: datetime) -> Optional[datetime]:
    if not text:
        return None
    lowered = text.lower()

    # Relative English (e.g., "3 hours ago", "2 days ago")
    m = re.search(r"(\d{1,2})\s*(hours?|days?)\s+ago", lowered)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        if "hour" in unit:
            return now - timedelta(hours=value)
        return now - timedelta(days=value)

    # Relative Chinese (e.g., "3小时前", "2天前", "10分钟前")
    m = re.search(r"(\d{1,2})\s*(小时|天|分钟)前", text)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        if unit == "小时":
            return now - timedelta(hours=value)
        if unit == "分钟":
            return now - timedelta(minutes=value)
        return now - timedelta(days=value)

    # Absolute date: YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None

    # Absolute date: Month DD, YYYY
    m = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})",
        text,
        re.IGNORECASE,
    )
    if m:
        try:
            month = m.group(1).title()
            day = int(m.group(2))
            year = int(m.group(3))
            month_map = {
                "Jan": 1,
                "Feb": 2,
                "Mar": 3,
                "Apr": 4,
                "May": 5,
                "Jun": 6,
                "Jul": 7,
                "Aug": 8,
                "Sep": 9,
                "Oct": 10,
                "Nov": 11,
                "Dec": 12,
            }
            return datetime(year, month_map[month], day)
        except Exception:
            return None

    return None



def _extract_datetime_from_url(url: str) -> Optional[datetime]:
    if not url:
        return None

    # Patterns like /2025/07/23/ or 2025-07-23
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", url)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None

    # Pattern like 20250723 (avoid matching long ids by requiring separators nearby)
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", url)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None

    return None



def _build_news_item(
    title: str,
    source: str,
    url: str = "",
    published_at: Any = None,
    snippet: str = "",
    ticker: Optional[str] = None,
    confidence: float = 0.7,
) -> Dict[str, Any]:
    if not title:
        return {}
    normalized_url = (url or "").strip()
    if "finnhub.io/api/news" in normalized_url.lower():
        normalized_url = ""
    published_date = _normalize_published_date(published_at)
    return {
        "headline": title,
        "title": title,
        "url": normalized_url,
        "source": source or "Unknown",
        "snippet": snippet or "",
        "published_at": published_date,
        "datetime": published_date,
        "ticker": ticker,
        "confidence": confidence,
    }



def format_news_items(items: List[Dict[str, Any]], title: str = "Latest News") -> str:
    if not items:
        return "No recent news available."
    lines: List[str] = []
    for idx, item in enumerate(items, 1):
        headline = item.get("headline") or item.get("title") or "No title"
        source = item.get("source") or "Unknown"
        url = item.get("url") or ""
        snippet = item.get("snippet") or ""
        date_str = item.get("published_at") or item.get("datetime") or "Recent"
        line = _format_headline_line(date_str, headline, source, url, snippet)
        lines.append(f"{idx}. {line}")
    return f"{title}:\n" + "\n".join(lines)



def _extract_search_items(text: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    current: Dict[str, str] | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^\d+\.", stripped):
            if current:
                items.append(current)
            title = re.sub(r"^\d+\.\s*", "", stripped).strip()
            current = {"title": title, "snippet": "", "url": ""}
            continue
        if stripped.startswith("http"):
            if current and not current.get("url"):
                current["url"] = stripped
            continue
        if stripped and current and not current.get("snippet"):
            current["snippet"] = stripped

    if current:
        items.append(current)

    return items



def _format_search_news_items(
    text: str,
    limit: int = 5,
    max_age_days: int = 7,
    now: Optional[datetime] = None,
) -> tuple[list[str], bool]:
    now = now or datetime.utcnow()
    items = _extract_search_items(text)
    enriched = []

    for item in items:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        if not _headline_is_useful(title, snippet):
            continue
        candidate_text = f"{title} {snippet}"
        dt = _extract_datetime_from_text(candidate_text, now)
        if not dt and item.get("url"):
            dt = _extract_datetime_from_url(item["url"])
        age_days = (now - dt).days if dt else None
        url = item.get("url", "")
        source = _domain_from_url(url)
        enriched.append(
            {
                "title": title,
                "snippet": snippet,
                "url": url,
                "source": source,
                "date": dt,
                "age_days": age_days,
            }
        )

    recent = [
        item
        for item in enriched
        if item["date"] and (now - item["date"]) <= timedelta(days=max_age_days)
    ]
    use_items = recent if recent else enriched

    lines: List[str] = []
    for item in use_items[:limit]:
        date_str = item["date"].strftime("%Y-%m-%d") if item["date"] else "未知日期"
        source = item["source"] or "source"
        url = item["url"] or ""
        lines.append(
            _format_headline_line(
                date_str,
                item["title"],
                source,
                url,
                item.get("snippet", ""),
            )
        )

    return lines, bool(recent)



def _build_search_news_items(
    text: str,
    limit: int = 5,
    max_age_days: int = 7,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow()
    items = _extract_search_items(text)
    enriched = []

    for item in items:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        if not _headline_is_useful(title, snippet):
            continue
        candidate_text = f"{title} {snippet}"
        dt = _extract_datetime_from_text(candidate_text, now)
        if not dt and item.get("url"):
            dt = _extract_datetime_from_url(item["url"])
        age_days = (now - dt).days if dt else None
        url = item.get("url", "")
        source = _domain_from_url(url)
        enriched.append(
            {
                "title": title,
                "snippet": snippet,
                "url": url,
                "source": source,
                "date": dt,
                "age_days": age_days,
            }
        )

    recent = [
        item
        for item in enriched
        if item["date"] and (now - item["date"]) <= timedelta(days=max_age_days)
    ]
    use_items = recent if recent else enriched

    results: List[Dict[str, Any]] = []
    for item in use_items[:limit]:
        published_at = item["date"].strftime("%Y-%m-%d") if item["date"] else None
        results.append(
            _build_news_item(
                title=item["title"],
                source=item["source"] or "search",
                url=item["url"],
                published_at=published_at,
                snippet=item.get("snippet", ""),
                confidence=0.4,
            )
        )
    return [item for item in results if item]



def _parse_rss_items(
    xml_text: str,
    limit: int = 5,
    max_age_days: int = 2,
    now: Optional[datetime] = None,
) -> tuple[list[str], bool]:
    now = now or datetime.utcnow()
    lines: List[str] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return [], False

    items = root.findall(".//item")
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title or not pub_date:
            continue
        if not _headline_is_useful(title, ""):
            continue

        try:
            dt = parsedate_to_datetime(pub_date)
        except Exception:
            dt = None
        if not dt:
            continue
        if dt.tzinfo:
            dt = dt.astimezone(tz=None).replace(tzinfo=None)

        if (now - dt) > timedelta(days=max_age_days):
            continue

        source = _domain_from_url(link)
        date_str = dt.strftime("%Y-%m-%d")
        lines.append(_format_headline_line(date_str, title, source, link))
        if len(lines) >= limit:
            break

    return lines, bool(lines)



def _fetch_rss_headlines(
    feed_urls: List[str],
    limit: int = 5,
    max_age_days: int = 2,
) -> tuple[list[str], bool]:
    all_lines: List[str] = []
    feeds_to_try = feed_urls[:_MAX_RSS_FEEDS]
    for url in feeds_to_try:
        try:
            resp = _rss_get(url, timeout=_RSS_TIMEOUT)
            if resp.status_code != 200:
                continue
            lines, ok = _parse_rss_items(resp.text, limit=limit, max_age_days=max_age_days)
            if ok:
                all_lines.extend(lines)
        except Exception:
            continue
        if len(all_lines) >= limit:
            break
    return all_lines[:limit], bool(all_lines)



def _fetch_finnhub_market_news(limit: int = 5, max_age_hours: int = 48) -> tuple[list[str], bool]:
    if not finnhub_client:
        return [], False

    now = datetime.utcnow()
    try:
        items = finnhub_client.general_news("general")
    except Exception:
        return [], False

    lines = []
    for item in items or []:
        ts = item.get("datetime")
        if not ts:
            continue
        try:
            dt = datetime.utcfromtimestamp(ts)
        except Exception:
            continue
        if (now - dt) > timedelta(hours=max_age_hours):
            continue
        title = item.get("headline") or item.get("summary") or "No title"
        snippet = item.get("summary") or ""
        if not _headline_is_useful(title, snippet):
            continue
        source = item.get("source") or "finnhub"
        url = item.get("url") or ""
        lines.append(
            _format_headline_line(
                dt.strftime("%Y-%m-%d"),
                title,
                source,
                url,
                snippet,
            )
        )
        if len(lines) >= limit:
            break
    return lines, bool(lines)

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


def _get_index_news(ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    专门为市场指数获取新闻的方法（结构化输出）。
    策略：通过搜索获取宏观市场新闻和指数分析。
    """
    friendly_name = MARKET_INDICES.get(ticker, ticker.replace('^', ''))
    
    logger.info(f"  → Detected market index: {friendly_name}")
    logger.info(f"  → Using specialized search strategy for index news...")
    
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
            logger.info(f"  → Search failed for '{query}': {e}")
            continue
    
    if not all_results:
        return []
    
    # 解析并格式化搜索结果
    combined_results = "\n\n".join(all_results)
    
    # 尝试从搜索结果中提取新闻标题和日期
    news_items: List[Dict[str, Any]] = []
    lines = combined_results.split('\n')
    
    for i, line in enumerate(lines):
        # 寻找标题模式（通常以数字开头）
        if re.match(r'^\d+\.', line.strip()):
            raw_title = line.strip()
            title = re.sub(r'^\d+\.\s*', '', raw_title).strip()
            window = ' '.join(lines[i:i+3])
            # 尝试找到日期信息
            date_match = re.search(r'(\d{1,2}\s+\w+\s+ago|\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2},?\s+\d{4})', 
                                  window, re.IGNORECASE)
            if not _is_reasonable_headline(title, window):
                continue
            if not _headline_is_useful(title, window):
                continue
            date_str = date_match.group(1) if date_match else 'Recent'
            item = _build_news_item(
                title=title,
                source="search",
                url="",
                published_at=date_str,
                snippet=window,
                ticker=ticker,
                confidence=0.4,
            )
            if item:
                news_items.append(item)
            
            if len(news_items) >= limit:
                break
    
    return news_items


def get_company_news(ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    智能获取新闻：自动识别是公司股票还是市场指数（结构化输出）。
    - 公司股票：使用 API (yfinance, Finnhub, Alpha Vantage)
    - 市场指数：使用搜索策略获取宏观市场新闻
    """
    try:
        limit = int(limit) if limit is not None else 5
    except Exception:
        limit = 5
    limit = max(1, min(limit, 20))
    # 🔍 关键判断：这是指数还是公司股票？
    if _is_market_index(ticker):
        # 优先用 alert_scheduler 的新闻抓取（含48h过滤）
        try:
            from backend.services.alert_scheduler import fetch_news_articles
            articles = fetch_news_articles(ticker)
            if articles:
                items: List[Dict[str, Any]] = []
                for a in articles:
                    title = a.get("title") or a.get("headline") or a.get("summary") or "No title"
                    snippet = a.get("summary") or a.get("description") or ""
                    if not _headline_is_useful(title, snippet):
                        continue
                    source = a.get("source") or a.get("publisher") or "Unknown"
                    published_at = a.get("published_at") or a.get("datetime") or a.get("providerPublishTime") or 0
                    url = a.get("url") or a.get("link") or ""
                    item = _build_news_item(
                        title=title,
                        source=source,
                        url=url,
                        published_at=published_at,
                        snippet=snippet,
                        ticker=ticker,
                        confidence=0.7,
                    )
                    if item:
                        items.append(item)
                    if len(items) >= limit:
                        break
                if items:
                    return items
        except Exception as e:
            logger.info(f"index news via alert_scheduler failed: {e}")

        # 先试 yfinance 的新闻（部分指数也有）
        try:
            stock = yf.Ticker(ticker)
            news = stock.news
            if news:
                items = []
                for article in news:
                    title = article.get('title', 'No title')
                    snippet = article.get('summary') or article.get('description') or ""
                    if not _headline_is_useful(title, snippet):
                        continue
                    publisher = article.get('publisher', 'Unknown source')
                    pub_time = article.get('providerPublishTime', 0)
                    url = article.get('link') or article.get('url') or ''
                    item = _build_news_item(
                        title=title,
                        source=publisher,
                        url=url,
                        published_at=pub_time,
                        snippet=snippet,
                        ticker=ticker,
                        confidence=0.7,
                    )
                    if item:
                        items.append(item)
                    if len(items) >= limit:
                        break
                if items:
                    return items
        except Exception as e:
            logger.info(f"yfinance index news error for {ticker}: {e}")

        # 再退回搜索策略
        return _get_index_news(ticker, limit=limit)
    
    # --- 以下是原有的公司新闻获取逻辑 ---
    
    # 方法1: yfinance
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if news:
            items = []
            for article in news:
                title = article.get('title', 'No title')
                snippet = article.get('summary') or article.get('description') or ""
                if not _headline_is_useful(title, snippet):
                    continue
                publisher = article.get('publisher', 'Unknown source')
                pub_time = article.get('providerPublishTime', 0)
                url = article.get('link') or article.get('url') or ''
                item = _build_news_item(
                    title=title,
                    source=publisher,
                    url=url,
                    published_at=pub_time,
                    snippet=snippet,
                    ticker=ticker,
                    confidence=0.7,
                )
                if item:
                    items.append(item)
                if len(items) >= limit:
                    break
            if items:
                return items
    except Exception as e:
        logger.info(f"yfinance news error for {ticker}: {e}")

    # 方法2: Finnhub
    if finnhub_client:
        try:
            logger.info(f"Trying Finnhub news for {ticker}")
            to_date = date.today().strftime("%Y-%m-%d")
            from_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
            news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
            if news:
                items = []
                for article in news:
                    title = article.get('headline', 'No title')
                    snippet = article.get('summary') or ""
                    if not _headline_is_useful(title, snippet):
                        continue
                    source = article.get('source', 'Unknown')
                    pub_time = article.get('datetime', 0)
                    url = article.get('url') or ''
                    item = _build_news_item(
                        title=title,
                        source=source,
                        url=url,
                        published_at=pub_time,
                        snippet=snippet,
                        ticker=ticker,
                        confidence=0.8,
                    )
                    if item:
                        items.append(item)
                    if len(items) >= limit:
                        break
                if items:
                    return items
        except Exception as e:
            logger.info(f"Finnhub news fetch failed: {e}")

    # 方法3: Alpha Vantage
    try:
        logger.info(f"Trying Alpha Vantage news for {ticker}")
        url = "https://www.alphavantage.co/query"
        params = {'function': 'NEWS_SENTIMENT', 'tickers': ticker, 'limit': 5, 'apikey': ALPHA_VANTAGE_API_KEY}
        response = _http_get(url, params=params, timeout=10)
        data = response.json()
        if 'feed' in data and data['feed']:
            items = []
            for article in data['feed']:
                title = article.get('title', 'No title')
                source = article.get('source', 'Unknown')
                date_str = article.get('time_published', '')[:8]
                if date_str:
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                snippet = article.get('summary') or ""
                if not _headline_is_useful(title, snippet):
                    continue
                url = article.get('url') or article.get('link') or ''
                item = _build_news_item(
                    title=title,
                    source=source,
                    url=url,
                    published_at=date_str,
                    snippet=snippet,
                    ticker=ticker,
                    confidence=0.8,
                )
                if item:
                    items.append(item)
                if len(items) >= limit:
                    break
            if items:
                return items
    except Exception as e:
        logger.info(f"Alpha Vantage news fetch failed: {e}")
    
    # 方法4: 回退到公司特定搜索
    logger.info(f"Falling back to search for {ticker} news")
    fallback_text = search(f"{ticker} company latest news stock")
    items = _build_search_news_items(fallback_text, limit=limit, max_age_days=7)
    if items:
        for item in items:
            if isinstance(item, dict):
                item.setdefault("ticker", ticker)
        return items
    return []



def get_news_sentiment(ticker: str, limit: int = 5) -> str:
    """
    获取新闻情绪 (Alpha Vantage NEWS_SENTIMENT)
    """
    if not ticker:
        return "News Sentiment: ticker is required."

    if not ALPHA_VANTAGE_API_KEY:
        return "News Sentiment: ALPHA_VANTAGE_API_KEY not configured."

    try:
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'NEWS_SENTIMENT',
            'tickers': ticker,
            'limit': limit,
            'apikey': ALPHA_VANTAGE_API_KEY,
        }
        response = _http_get(url, params=params, timeout=10)
        data = response.json()

        if not data or 'feed' not in data or not data.get('feed'):
            if isinstance(data, dict):
                if data.get('Note'):
                    return f"News Sentiment: rate limited ({data.get('Note')})"
                if data.get('Information'):
                    return f"News Sentiment: {data.get('Information')}"
                if data.get('Error Message'):
                    return f"News Sentiment: {data.get('Error Message')}"
            return "News Sentiment: no data found."

        def _extract_sentiment(item: Dict[str, Any], symbol: str):
            symbol_upper = symbol.upper()
            for ts in item.get('ticker_sentiment', []):
                if ts.get('ticker', '').upper() == symbol_upper:
                    return ts.get('ticker_sentiment_score'), ts.get('ticker_sentiment_label')
            return item.get('overall_sentiment_score'), item.get('overall_sentiment_label')

        lines = []
        scores: List[float] = []
        for i, item in enumerate(data.get('feed', [])[:limit], 1):
            title = item.get('title', 'No title')
            source = item.get('source', 'Unknown')
            time_published = item.get('time_published', '')
            date_str = time_published[:8]
            if date_str and len(date_str) == 8:
                date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            else:
                date_str = 'Unknown date'
            url = item.get('url') or item.get('link') or ''
            score, label = _extract_sentiment(item, ticker)
            sentiment_desc = "N/A"
            try:
                if score is not None:
                    score_val = float(score)
                    scores.append(score_val)
                    sentiment_desc = f"{label or 'Unknown'} ({score_val:.2f})"
                elif label:
                    sentiment_desc = label
            except Exception:
                if label:
                    sentiment_desc = label

            headline = f"[{title}]({url})" if url else title
            lines.append(f"{i}. [{date_str}] {headline} ({source}) 情绪: {sentiment_desc}")

        avg_text = ""
        if scores:
            avg_score = sum(scores) / len(scores)
            avg_text = f"\n平均情绪分数: {avg_score:.2f}"

        return f"News Sentiment ({ticker}):{avg_text}\n" + "\n".join(lines)
    except Exception as e:
        return f"News Sentiment: fetch failed ({str(e)})"



def get_market_news_headlines(limit: int = 5) -> str:
    """
    市场泛化新闻：不带 ticker 的情况，抓取全球/美股要闻。
    使用搜索聚合并提取编号行作为标题，否则返回简短提示。
    """
    # 0) 官方 RSS（Reuters/Bloomberg），优先 48h 内
    bloomberg_default_feeds = [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://feeds.bloomberg.com/technology/news.rss",
        "https://feeds.bloomberg.com/politics/news.rss",
        "https://feeds.bloomberg.com/wealth/news.rss",
        "https://feeds.bloomberg.com/pursuits/news.rss",
        "https://feeds.bloomberg.com/businessweek/news.rss",
        "https://feeds.bloomberg.com/industries/news.rss",
    ]
    market_default_feeds = [
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        "https://seekingalpha.com/feed.xml",
    ]

    reuters_env = os.getenv("REUTERS_RSS_URLS", "").strip()
    reuters_feeds = [u.strip() for u in reuters_env.split(",") if u.strip()]

    bloomberg_env = os.getenv("BLOOMBERG_RSS_URLS", "").strip()
    bloomberg_env_feeds = [u.strip() for u in bloomberg_env.split(",") if u.strip()]
    if bloomberg_env_feeds:
        bloomberg_feeds = bloomberg_default_feeds + [
            u for u in bloomberg_env_feeds if u not in bloomberg_default_feeds
        ]
    else:
        bloomberg_feeds = bloomberg_default_feeds

    market_env = os.getenv("MARKET_NEWS_RSS_URLS", "").strip()
    market_env_feeds = [u.strip() for u in market_env.split(",") if u.strip()]
    if market_env_feeds:
        market_feeds = market_default_feeds + [
            u for u in market_env_feeds if u not in market_default_feeds
        ]
    else:
        market_feeds = market_default_feeds

    rss_feeds: List[str] = []
    seen_urls = set()
    for url in (bloomberg_feeds + market_feeds + reuters_feeds):
        if url and url not in seen_urls:
            seen_urls.add(url)
            rss_feeds.append(url)

    rss_lines, rss_ok = _fetch_rss_headlines(rss_feeds, limit=limit * 2, max_age_days=2)
    if rss_ok:
        return "最近48小时市场要闻(RSS):\n" + "\n".join(rss_lines[:limit])

    # 1) Finnhub 市场新闻（48h）
    finnhub_lines, finnhub_ok = _fetch_finnhub_market_news(limit=limit * 2, max_age_hours=48)
    if finnhub_ok:
        return "最近48小时市场要闻(Finnhub):\n" + "\n".join(finnhub_lines[:limit])

    # 2) 尝试用 alert_scheduler 的新闻抓取（已含48h过滤），优先指数与代表性ETF
    try:
        from backend.services.alert_scheduler import fetch_news_articles
        for idx_ticker in ["^GSPC", "^IXIC", "SPY", "QQQ", "DIA", "IWM"]:
            try:
                articles = fetch_news_articles(idx_ticker)
            except Exception as inner:
                logger.info(f"[MarketNews] fetch_news_articles failed for {idx_ticker}: {inner}")
                continue
            if articles:
                lines = []
                for a in articles:
                    title = a.get("title") or a.get("headline") or a.get("summary") or "No title"
                    snippet = a.get("summary") or a.get("description") or ""
                    if not _headline_is_useful(title, snippet):
                        continue
                    source = a.get("source") or a.get("publisher") or "Unknown"
                    published_at = a.get("published_at") or a.get("datetime") or a.get("providerPublishTime") or 0
                    if isinstance(published_at, str):
                        date_str = published_at.split("T")[0]
                    else:
                        date_str = datetime.fromtimestamp(published_at).strftime("%Y-%m-%d") if published_at else "Recent"
                    url = a.get("url") or a.get("link") or ""
                    line = _format_headline_line(date_str, title, source, url, snippet)
                    lines.append(f"{len(lines) + 1}. {line}")
                    if len(lines) >= limit:
                        break
                if lines:
                    return "最近48小时市场要闻:\n" + "\n".join(lines)
    except Exception as e:
        logger.info(f"[MarketNews] fetch via alert_scheduler failed: {e}")

    # 3) 搜索聚合兜底
    queries = [
        "global stock market breaking news today",
        "US stock market headlines today",
        "market moving news today equities"
    ]
    combined = []
    for q in queries:
        try:
            res = search(q)
            combined.append(res)
        except Exception as e:
            logger.info(f"[MarketNews] search failed for '{q}': {e}")
            continue
    if not combined:
        return "未能获取可靠的市场热点信息，请直接查看 Bloomberg/Reuters/WSJ 等权威来源。"
    
    text = "\n\n".join(combined)
    lines, has_recent = _format_search_news_items(text, limit=limit, max_age_days=3)
    if not has_recent:
        lines, has_recent = _format_search_news_items(text, limit=limit, max_age_days=7)

    if not has_recent:
        retry_queries = [
            "global stock market news last 24 hours",
            "US stock market headlines last 24 hours",
            "market moving news past week site:reuters.com",
        ]
        retry_combined = []
        for q in retry_queries:
            try:
                res = search(q)
                retry_combined.append(res)
            except Exception as e:
                logger.info(f"[MarketNews] retry search failed for '{q}': {e}")
                continue
        if retry_combined:
            retry_text = "\n\n".join(retry_combined)
            retry_lines, retry_recent = _format_search_news_items(retry_text, limit=limit, max_age_days=7)
            if retry_lines and retry_recent:
                return "最近市场热点(近7天):\n" + "\n".join(retry_lines)
            if retry_recent:
                lines = retry_lines
                has_recent = True

    if has_recent and lines:
        return "最近市场热点(近7天):\n" + "\n".join(lines)

    return "近7天内未检索到可靠市场热点，请直接查看 Bloomberg/Reuters/WSJ 等权威来源。"
# ============================================
# 其他工具函数（保持不变或稍作修改）
# ============================================
