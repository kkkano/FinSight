"""新闻报道的时效、出处与事件分组合同；不把转载数量当作事实核验。"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.config.ticker_mapping import CN_TO_TICKER, COMPANY_MAP

NEWS_QUALITY_VERSION = "news-event-v1"
NEWS_MAX_AGE_HOURS = 7 * 24
_MEDIA_DOMAINS = (
    "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com",
    "marketwatch.com", "finance.yahoo.com", "nasdaq.com", "apnews.com",
    "bbc.com", "bbc.co.uk", "caixin.com", "yicai.com", "stcn.com",
)
_OFFICIAL_DOMAINS = ("sec.gov", "hkexnews.hk", "sse.com.cn", "szse.cn", "cninfo.com.cn")
_COMPANY_DOMAINS = {
    "AAPL": ("apple.com",), "NVDA": ("nvidia.com",),
    "MSFT": ("microsoft.com",), "INTC": ("intel.com",),
    "AMD": ("amd.com",), "AMZN": ("aboutamazon.com", "amazon.com"),
    "GOOG": ("abc.xyz", "google.com"), "GOOGL": ("abc.xyz", "google.com"),
    "META": ("meta.com", "fb.com"), "TSLA": ("tesla.com",),
    "AAOI": ("ao-inc.com",), "TSM": ("tsmc.com",),
    "0700.HK": ("tencent.com",), "TCEHY": ("tencent.com",),
}
_COMMENTARY_DOMAINS = ("seekingalpha.com", "fool.com", "reddit.com", "x.com", "twitter.com")
_EXTRA_ALIASES = {
    "AAOI": ("Applied Optoelectronics", "应用光电"),
    "0700.HK": ("Tencent", "腾讯", "腾讯控股"),
    "9988.HK": ("Alibaba", "阿里巴巴"),
    "600519.SS": ("贵州茅台", "茅台"),
}
_RUMOR = re.compile(r"\b(rumou?rs?|unconfirmed|alleged|reportedly|sources say)\b|传闻|据传|未经证实|网传", re.I)
_OPINION = re.compile(
    r"\b(opinion|commentary|should you|is .{1,30} a buy|why .{1,70} (?:buy|sell)|"
    r"could|might|will .{1,50}\?|stock forecast|price prediction)\b|观点|评论|值得买吗|"
    r"是否值得|可能|或将|股价预测|投资建议", re.I,
)
_TRACKING_KEYS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref", "referrer", "source"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def news_domain(url: Any) -> str:
    try:
        parsed = urlsplit(str(url or "").strip())
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return ""
        return str(parsed.hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def canonical_news_url(url: Any) -> str:
    host = news_domain(url)
    if not host:
        return ""
    parsed = urlsplit(str(url).strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_KEYS]
    # 只删追踪参数；id 等文章身份参数必须保留。
    netloc = host
    try:
        if parsed.port and parsed.port not in {80, 443}:
            netloc += f":{parsed.port}"
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), urlencode(sorted(query)), ""))


def parse_news_time(value: Any) -> tuple[datetime | None, str]:
    """只解析来源的明确发布时间；抓取时间、标题中的日期不补为发布时间。"""
    if value is None or isinstance(value, bool):
        return None, "unknown"
    precision = "timestamp"
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed, precision = datetime.combine(value, datetime.min.time()), "date"
        elif isinstance(value, (int, float)):
            if value <= 0:
                return None, "unknown"
            parsed = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, UTC)
        else:
            text = str(value).strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                precision = "date"
                parsed = datetime.fromisoformat(text)
            elif re.fullmatch(r"\d{8}T\d{6}", text):
                parsed = datetime.strptime(text, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
            else:
                try:
                    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                except ValueError:
                    parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            # 缺失时区只认可日期精度，不捏造盘中先后顺序。
            parsed, precision = parsed.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC), "date"
        return parsed.astimezone(UTC), precision
    except (ValueError, TypeError, OverflowError, OSError):
        return None, "unknown"


def normalized_news_time(value: Any) -> tuple[str | None, str]:
    parsed, precision = parse_news_time(value)
    if parsed is None:
        return None, precision
    return (parsed.date().isoformat() if precision == "date" else parsed.isoformat().replace("+00:00", "Z")), precision


def news_subject_terms(ticker: str) -> list[str]:
    symbol = str(ticker or "").strip().upper()
    aliases = [symbol, *_EXTRA_ALIASES.get(symbol, ())]
    mapped = COMPANY_MAP.get(symbol)
    if mapped:
        aliases.append(mapped)
    for mapping in (COMPANY_MAP, CN_TO_TICKER):
        aliases.extend(str(alias) for alias, target in mapping.items() if str(target).upper() == symbol)
    return list(dict.fromkeys(term for term in aliases if term))


def _mentions(text: str, terms: Iterable[str], ticker: str) -> bool:
    for term in terms:
        if re.search(r"[\u4e00-\u9fff]", term):
            if term in text:
                return True
        elif term.upper() == ticker.upper() and len(term) <= 2:
            if re.search(rf"(?<!\w)\$?{re.escape(term.upper())}(?!\w)", text):
                return True
        elif re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.I):
            return True
    return False


def news_subject_match(ticker: str, title: str, snippet: str = "") -> str:
    if not ticker or ticker.startswith("^"):
        return "market"
    terms = news_subject_terms(ticker)
    if _mentions(title, terms, ticker):
        return "headline"
    # 搜索页经常在无关摘要里带查询词，不把它投射成公司事件。
    if _mentions(snippet, terms, ticker):
        return "summary_only"
    return "none"


def news_source_tier(url: Any, ticker: str = "") -> str:
    host = news_domain(url)
    if any(domain_matches(host, domain) for domain in (*_OFFICIAL_DOMAINS, *_COMPANY_DOMAINS.get(ticker.upper(), ()))):
        return "primary"
    if any(domain_matches(host, domain) for domain in _MEDIA_DOMAINS):
        return "established_media"
    if any(domain_matches(host, domain) for domain in _COMMENTARY_DOMAINS):
        return "opinion_or_community"
    return "unknown"


def _is_discovery_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = news_domain(url)
    path = parsed.path.lower()
    return (
        host in {"google.com", "bing.com", "news.google.com"}
        or "/search" in path or "/site-search" in path
        or (host == "finance.yahoo.com" and path.startswith("/quote/") and path.endswith("/news"))
        or (host == "finnhub.io" and path.startswith("/api/news"))
    )


def _title_key(title: str, source: str) -> str:
    clean = html.unescape(unicodedata.normalize("NFKC", title)).strip()
    if source:
        clean = re.sub(r"\s*[-–—|]\s*" + re.escape(source) + r"\s*$", "", clean, flags=re.I)
    return re.sub(r"[^\w]+", " ", clean.casefold()).strip()


def annotate_news_item(item: Mapping[str, Any], *, ticker: str = "", now: datetime | None = None,
                       max_age_hours: int = NEWS_MAX_AGE_HOURS) -> dict[str, Any]:
    row = dict(item)
    observed = (now or utc_now()).astimezone(UTC)
    previous_quality = row.get("event_quality") if isinstance(row.get("event_quality"), dict) else {}
    # 缓存命中时重新判断时效，但不把读取缓存的时刻伪装成重新抓取。
    first_observed = previous_quality.get("observed_at") or observed.isoformat().replace("+00:00", "Z")
    symbol = str(ticker or row.get("ticker") or "").upper()
    title = str(row.get("headline") or row.get("title") or "").strip()
    snippet = str(row.get("snippet") or row.get("summary") or "").strip()
    original_url = str(row.get("url") or row.get("link") or "").strip()
    canonical_url = canonical_news_url(original_url)
    url = original_url if canonical_url else ""
    published, precision = parse_news_time(row.get("published_at") or row.get("published_date") or row.get("datetime") or row.get("time_published"))
    if row.get("published_at_precision") == "date" and published is not None:
        precision = "date"
    published_text = None if published is None else published.date().isoformat() if precision == "date" else published.isoformat().replace("+00:00", "Z")
    if published is None:
        freshness = "unknown"
    elif (published.date() > observed.date() if precision == "date" else published > observed + timedelta(minutes=5)):
        freshness = "future"
    elif published < observed - timedelta(hours=max_age_hours):
        freshness = "stale"
    else:
        freshness = "fresh"

    subject = news_subject_match(symbol, title, snippet)
    tier = news_source_tier(url, symbol)
    retrieval_kind = str(row.get("retrieval_kind") or "provider_feed")
    kind = "report"
    if retrieval_kind in {"search", "search_snippet"} or _is_discovery_url(url) or not url:
        kind = "discovery"
    elif _RUMOR.search(title):
        kind = "rumor"
    elif tier == "opinion_or_community" or _OPINION.search(title) or title.rstrip().endswith(("?", "？")):
        kind = "opinion"
    reasons = []
    if freshness != "fresh":
        reasons.append(f"publication_time_{freshness}")
    if subject in {"none", "summary_only"}:
        reasons.append("subject_not_confirmed_in_headline")
    if tier == "unknown":
        reasons.append("source_unclassified")
    if kind != "report":
        reasons.append(f"content_{kind}")
    usable = freshness == "fresh" and subject in {"headline", "market"} and tier in {"primary", "established_media"} and kind == "report"
    role = "reported_news" if usable else "historical_news" if freshness == "stale" else "opinion" if kind == "opinion" and freshness == "fresh" else "discovery"
    key = f"{symbol}|{_title_key(title, str(row.get('source') or ''))}|{published.date().isoformat() if published else 'unknown'}"
    event_id = "news_event:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    row.update({"headline": title, "title": title, "url": url, "ticker": symbol,
                "published_at": published_text, "datetime": published_text,
                "published_at_precision": precision, "retrieval_kind": retrieval_kind})
    row["event_quality"] = {
        "version": NEWS_QUALITY_VERSION, "event_id": event_id,
        "canonical_url": canonical_url,
        "published_at": published_text, "published_precision": precision,
        "observed_at": first_observed,
        "occurred_at": None, "freshness": freshness, "max_age_hours": max_age_hours,
        "source_domain": news_domain(url), "source_tier": tier, "subject_match": subject,
        "content_kind": kind, "evidence_role": role, "usable_as_catalyst": usable,
        "verification": "headline_only" if usable else "discovery_only", "reasons": reasons,
        "report_count": 1, "source_count": 1 if news_domain(url) else 0,
        "independence": "unverified", "grouping": "exact_headline_same_publication_day",
    }
    return row


def prepare_news_items(items: Iterable[Any], *, ticker: str = "", now: datetime | None = None,
                       max_age_hours: int = NEWS_MAX_AGE_HOURS) -> list[dict[str, Any]]:
    """保守地合并同标题、同发表日的报道；不同动作/后续进展不模糊合并。"""
    observed = now or utc_now()
    groups: dict[str, list[dict[str, Any]]] = {}
    article_groups: dict[tuple[str, str], str] = {}
    for item in items:
        if not isinstance(item, Mapping) or not (item.get("title") or item.get("headline")):
            continue
        row = annotate_news_item(item, ticker=ticker, now=observed, max_age_hours=max_age_hours)
        article_key = (canonical_news_url(row["url"]), str(row.get("published_at") or "unknown"))
        group_id = article_groups.get(article_key) if row["url"] else None
        group_id = group_id or row["event_quality"]["event_id"]
        if row["url"]:
            article_groups[article_key] = group_id
        groups.setdefault(group_id, []).append(row)
    output = []
    ranks = {"primary": 0, "established_media": 1, "opinion_or_community": 2, "unknown": 3}
    for members in groups.values():
        members.sort(key=lambda row: (not row["event_quality"]["usable_as_catalyst"], ranks[row["event_quality"]["source_tier"]], row["published_at"] or ""))
        representative = members[0]
        # 同一 URL 同时刻的不同标题是同一报道；跨日更新和不同报道仍保留。
        representative["event_quality"]["grouping"] = "canonical_url_same_time_or_exact_headline_same_day"
        reports: dict[str, dict[str, Any]] = {}
        for member in members:
            # 再次走合同（缓存/轻量快照）仍保留全部出处，不让分组计数倍增。
            previous = member.get("supporting_reports")
            candidates = previous if isinstance(previous, list) else [member]
            for candidate in candidates:
                report_url = canonical_news_url(candidate.get("url"))
                if report_url:
                    reports.setdefault(report_url, {key: candidate.get(key) for key in ("url", "source", "published_at", "retrieval_kind")})
        representative["supporting_reports"] = list(reports.values())[:20]
        quality = representative["event_quality"]
        quality["report_count"] = len(reports) or 1
        quality["source_count"] = len({news_domain(url) for url in reports})
        output.append(representative)
    output.sort(key=lambda row: row.get("published_at") or "", reverse=True)
    output.sort(key=lambda row: (not row["event_quality"]["usable_as_catalyst"], row["event_quality"]["freshness"] != "fresh"))
    return output


def news_quality_label(item: Mapping[str, Any]) -> str:
    quality = item.get("event_quality") or {}
    labels = []
    freshness = quality.get("freshness")
    if freshness in {"unknown", "stale", "future"}:
        labels.append({"unknown": "发布时间未知", "stale": "旧闻背景", "future": "发布时间异常"}[freshness])
    kind = quality.get("content_kind")
    if kind in {"discovery", "rumor", "opinion"}:
        labels.append({"discovery": "检索线索，待核实", "rumor": "传闻，待核实", "opinion": "观点"}[kind])
    if quality.get("subject_match") in {"none", "summary_only"}:
        labels.append("主体关联未确认")
    if quality.get("source_tier") == "unknown":
        labels.append("来源待核实")
    if quality.get("usable_as_catalyst"):
        labels.append("报道，未核原文")
    return "；".join(labels)
