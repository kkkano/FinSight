from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
import os
import logging
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.agents.chart_specs import build_news_sentiment_chart_specs
from backend.agents.sentiment_brief import render_stock_brief
from backend.research.agent_quality_contract import assign_evidence_source_ids, build_agent_claim
from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


@dataclass
class NewsSentimentSnapshot:
    """整只股票的舆情聚合快照。"""

    ticker: str
    as_of: str
    sentiment_bias: Dict[str, Any]
    sentiment_trend: Dict[str, Any]
    heat: Dict[str, Any]
    catalyst_events: Dict[str, Any]
    price_transmission: Dict[str, Any]
    inputs: Dict[str, Any] = field(default_factory=dict)


class NewsAgent(BaseFinancialAgent):
    AGENT_NAME = "NewsAgent"
    CACHE_TTL = 600  # 10 minutes
    MAX_REFLECTIONS = 1  # ReAct: one Reason-Act cycle for deeper investigation
    _AUTHORITATIVE_DOMAIN_HINTS = (
        "sec.gov",
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "cnbc.com",
        "marketwatch.com",
        "finance.yahoo.com",
        "nasdaq.com",
        "fool.com",
        "seekingalpha.com",
        "investor.",
        "apple.com",
    )

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        if circuit_breaker is None:
            circuit_breaker = CircuitBreaker(
                failure_threshold=int(os.getenv("NEWS_CB_FAILURE_THRESHOLD", "3")),
                recovery_timeout=float(os.getenv("NEWS_CB_RECOVERY_TIMEOUT", "180")),
                half_open_success_threshold=int(os.getenv("NEWS_CB_HALF_OPEN_SUCCESS", "1")),
            )
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module
        self._last_convergence = None
        self._last_event_calendar: Dict[str, Any] = {}
        self._last_reliability_summary: Dict[str, Any] = {}
        self._last_sentiment_snapshot: Optional[NewsSentimentSnapshot] = None

    def _get_tool_registry(self) -> dict:
        """NewsAgent tool registry: news APIs + search for ReAct reflection."""
        registry = {}
        tools = self.tools
        if not tools:
            return registry
        search_fn = getattr(tools, "search", None)
        if search_fn:
            registry["search"] = {
                "func": search_fn,
                "description": "通用网络搜索，查询任意新闻/事件",
                "call_with": "query",
            }
        news_fn = getattr(tools, "get_company_news", None)
        if news_fn:
            registry["get_company_news"] = {
                "func": news_fn,
                "description": "获取公司新闻列表(ticker)，返回结构化新闻数据",
                "call_with": "ticker",
            }
        sentiment_fn = getattr(tools, "get_news_sentiment", None)
        if sentiment_fn:
            registry["get_news_sentiment"] = {
                "func": sentiment_fn,
                "description": "获取新闻情绪分析(ticker)，返回情绪评分和标签",
                "call_with": "ticker",
            }
        event_fn = getattr(tools, "get_event_calendar", None)
        if event_fn:
            registry["get_event_calendar"] = {
                "func": event_fn,
                "description": "获取财报/分红/宏观事件日历",
                "call_with": "ticker",
            }
        reliability_fn = getattr(tools, "score_news_source_reliability", None)
        if reliability_fn:
            registry["score_news_source_reliability"] = {
                "func": reliability_fn,
                "description": "评估新闻来源可靠度",
                "call_with": "none",
            }
        return registry

    def _is_finance_research_intent(self, query: str) -> bool:
        text = str(query or "").lower()
        signals = (
            "10-k",
            "10q",
            "10-q",
            "filing",
            "earnings",
            "transcript",
            "investment report",
            "deep report",
            "longform",
            "财报",
            "业绩",
            "研报",
            "电话会",
        )
        return any(token in text for token in signals)

    def _domain_from_url(self, url: str) -> str:
        try:
            host = urlparse(str(url or "").strip().lower()).netloc
        except Exception:
            host = ""
        return host.lstrip("www.")

    def _recover_original_article_url(self, url: str) -> str:
        text = str(url or "").strip()
        if not text.startswith(("http://", "https://")):
            return ""
        try:
            parsed = urlparse(text)
        except Exception:
            return ""

        domain = (parsed.netloc or "").lower().lstrip("www.")
        path = (parsed.path or "").lower()
        query = parse_qs(parsed.query)

        if domain == "finnhub.io" and path.startswith("/api/news"):
            for key in ("url", "article_url", "link", "u"):
                value = query.get(key, [None])[0]
                if not value:
                    continue
                decoded = unquote(str(value)).strip()
                if decoded.startswith(("http://", "https://")):
                    return decoded
            return ""

        if domain == "news.google.com":
            for key in ("url", "u"):
                value = query.get(key, [None])[0]
                if not value:
                    continue
                decoded = unquote(str(value)).strip()
                if decoded.startswith(("http://", "https://")):
                    return decoded

        return text

    def _is_authoritative_domain(self, domain: str) -> bool:
        host = str(domain or "").strip().lower()
        if not host:
            return False
        return any(hint in host for hint in self._AUTHORITATIVE_DOMAIN_HINTS)

    def _filter_authoritative_news(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            if self._is_authoritative_domain(self._domain_from_url(url)):
                filtered.append(item)
        return filtered

    _UNSCORED_RELIABILITY = {"reliability_score": None, "reliability_tier": "unscored", "reason": "unscored"}

    def _score_reliability_for_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        scorer = getattr(self.tools, "score_news_source_reliability", None)
        if not scorer:
            # P0-9: 无评分工具时诚实标记未评估，不编造 0.55
            return dict(self._UNSCORED_RELIABILITY)
        try:
            payload = scorer(source=item.get("source", ""), url=item.get("url", ""))
            if isinstance(payload, dict):
                score = payload.get("reliability_score")
                if isinstance(score, (int, float)):
                    return payload
        except Exception:
            pass
        return dict(self._UNSCORED_RELIABILITY)

    def _annotate_reliability(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        annotated: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rel = self._score_reliability_for_item(item)
            cloned = dict(item)
            cloned["source_reliability"] = rel
            score = rel.get("reliability_score")
            # P0-9: 只有真实评分才进 confidence；未评估(None)不注入
            if isinstance(score, (int, float)) and "confidence" not in cloned:
                cloned["confidence"] = max(0.1, min(0.95, float(score)))
            annotated.append(cloned)
        return annotated

    def _summarize_reliability(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        scores: List[float] = []
        high_count = 0
        low_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            rel = item.get("source_reliability")
            if not isinstance(rel, dict):
                continue
            score = rel.get("reliability_score")
            if not isinstance(score, (int, float)):
                continue
            s = float(score)
            scores.append(s)
            if s >= 0.85:
                high_count += 1
            if s < 0.65:
                low_count += 1
        avg = sum(scores) / len(scores) if scores else None
        return {
            "count": len(scores),
            "avg_reliability": round(avg, 4) if avg is not None else None,
            "high_reliability_count": high_count,
            "low_reliability_count": low_count,
        }

    def _load_event_calendar(self, ticker: str) -> Dict[str, Any]:
        event_fn = getattr(self.tools, "get_event_calendar", None)
        if not event_fn:
            return {}
        try:
            payload = event_fn(ticker=ticker, days_ahead=30)
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}
        return {}

    def _call_ticker_tool(self, fn, ticker: str, **kwargs) -> Any:
        try:
            return fn(ticker=ticker, **kwargs)
        except TypeError:
            try:
                return fn(ticker, **kwargs)
            except TypeError:
                return fn(ticker)

    def _load_news_sentiment_payload(self, ticker: str) -> Any:
        sentiment_fn = getattr(self.tools, "get_news_sentiment", None)
        if not callable(sentiment_fn):
            return None
        try:
            return self._call_ticker_tool(sentiment_fn, ticker, limit=8)
        except Exception:
            return None

    def _coerce_float(self, value: Any) -> Optional[float]:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip().replace("%", "")
            try:
                return float(text)
            except Exception:
                match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
                if match:
                    try:
                        return float(match.group(1))
                    except Exception:
                        return None
        return None

    def _sentiment_bucket(self, score: Optional[float], label: str = "") -> str:
        lowered = str(label or "").lower()
        if "neutral" in lowered:
            return "neutral"
        if "bull" in lowered or "positive" in lowered:
            return "positive"
        if "bear" in lowered or "negative" in lowered:
            return "negative"
        if score is None:
            return "neutral"
        if score >= 0.15:
            return "positive"
        if score <= -0.15:
            return "negative"
        return "neutral"

    def _parse_news_sentiment_payload(self, payload: Any) -> Dict[str, Any]:
        observations: List[Dict[str, Any]] = []
        explicit_average: Optional[float] = None
        status = "unavailable"
        raw_preview = ""

        if isinstance(payload, str):
            raw_preview = payload[:1200]
            avg_match = re.search(r"平均情绪分数\s*[:：]\s*([+-]?\d+(?:\.\d+)?)", payload)
            if avg_match:
                explicit_average = self._coerce_float(avg_match.group(1))
            for line in payload.splitlines():
                if "情绪" not in line and "sentiment" not in line.lower():
                    continue
                score = None
                score_match = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", line)
                if score_match:
                    score = self._coerce_float(score_match.group(1))
                label = ""
                label_match = re.search(r"情绪\s*[:：]\s*([^(]+)", line)
                if label_match:
                    label = label_match.group(1).strip()
                date_match = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", line)
                if score is None and not label:
                    continue
                observations.append(
                    {
                        "score": score,
                        "label": label,
                        "bucket": self._sentiment_bucket(score, label),
                        "date": date_match.group(1) if date_match else None,
                        "source": "get_news_sentiment",
                    }
                )
            if observations or explicit_average is not None:
                status = "ok"
        elif isinstance(payload, dict):
            raw_preview = json.dumps(payload, ensure_ascii=False)[:1200]
            for key in ("average_score", "avg_score", "average_sentiment_score", "overall_sentiment_score"):
                explicit_average = self._coerce_float(payload.get(key))
                if explicit_average is not None:
                    break
            feed = payload.get("feed") or payload.get("items") or payload.get("articles") or []
            if isinstance(feed, list):
                for item in feed:
                    observation = self._extract_item_sentiment(item)
                    if observation:
                        observation["source"] = "get_news_sentiment"
                        observations.append(observation)
            if observations or explicit_average is not None:
                status = "ok"

        return {
            "status": status,
            "observations": observations,
            "explicit_average": explicit_average,
            "raw_preview": raw_preview,
        }

    def _extract_item_sentiment(self, item: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None

        score = None
        label = ""
        ticker = str(item.get("ticker") or self._current_ticker or "").upper()
        for ts in item.get("ticker_sentiment") or []:
            if not isinstance(ts, dict):
                continue
            if ticker and str(ts.get("ticker") or "").upper() != ticker:
                continue
            score = self._coerce_float(ts.get("ticker_sentiment_score"))
            label = str(ts.get("ticker_sentiment_label") or "")
            break

        if score is None:
            for key in (
                "sentiment_score",
                "ticker_sentiment_score",
                "overall_sentiment_score",
                "news_sentiment_score",
            ):
                score = self._coerce_float(item.get(key))
                if score is not None:
                    break

        for key in ("sentiment_label", "ticker_sentiment_label", "overall_sentiment_label", "sentiment"):
            raw_label = item.get(key)
            if isinstance(raw_label, dict):
                raw_label = raw_label.get("label")
            if raw_label:
                label = str(raw_label)
                break

        if score is None and not label:
            return None
        return {
            "score": score,
            "label": label,
            "bucket": self._sentiment_bucket(score, label),
            "date": item.get("datetime") or item.get("published_at") or item.get("time_published"),
            "source": item.get("source") or "news_item",
        }

    def _build_sentiment_bias(
        self,
        observations: List[Dict[str, Any]],
        explicit_average: Optional[float],
    ) -> Dict[str, Any]:
        counts = {"positive": 0, "negative": 0, "neutral": 0}
        scores: List[float] = []
        for observation in observations:
            bucket = observation.get("bucket") or "neutral"
            if bucket not in counts:
                bucket = "neutral"
            counts[bucket] += 1
            score = self._coerce_float(observation.get("score"))
            if score is not None:
                scores.append(score)

        average_score = explicit_average
        if average_score is None and scores:
            average_score = sum(scores) / len(scores)

        if average_score is not None and average_score >= 0.08:
            label = "bullish"
        elif average_score is not None and average_score <= -0.08:
            label = "bearish"
        elif counts["positive"] > counts["negative"]:
            label = "bullish"
        elif counts["negative"] > counts["positive"]:
            label = "bearish"
        else:
            label = "neutral"

        total = sum(counts.values())
        denominator = total or 1
        confidence = min(0.9, 0.45 + min(total, 8) * 0.05)
        if average_score is None and total == 0:
            confidence = 0.35

        return {
            "label": label,
            "average_score": round(float(average_score), 4) if average_score is not None else None,
            "positive_count": counts["positive"],
            "negative_count": counts["negative"],
            "neutral_count": counts["neutral"],
            "positive_ratio": round(counts["positive"] / denominator, 4),
            "negative_ratio": round(counts["negative"] / denominator, 4),
            "neutral_ratio": round(counts["neutral"] / denominator, 4),
            "sample_size": total,
            "confidence": round(confidence, 4),
        }

    def _build_sentiment_trend(self, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        scores = [
            float(score)
            for score in (self._coerce_float(item.get("score")) for item in observations)
            if score is not None
        ]
        if len(scores) < 2:
            return {
                "direction": "unknown",
                "delta": None,
                "recent_average": None,
                "previous_average": None,
                "basis": "insufficient_sentiment_history",
            }

        split = max(1, len(scores) // 2)
        recent = scores[:split]
        previous = scores[split:] or scores[:split]
        recent_avg = sum(recent) / len(recent)
        previous_avg = sum(previous) / len(previous)
        delta = recent_avg - previous_avg
        if delta >= 0.08:
            direction = "improving"
        elif delta <= -0.08:
            direction = "deteriorating"
        else:
            direction = "stable"
        return {
            "direction": direction,
            "delta": round(delta, 4),
            "recent_average": round(recent_avg, 4),
            "previous_average": round(previous_avg, 4),
            "basis": "newest_items_vs_older_items",
        }

    def _event_counts(self, calendar: Dict[str, Any]) -> Dict[str, int]:
        return {
            "earnings": len(calendar.get("earnings_events") or []) if isinstance(calendar.get("earnings_events"), list) else 0,
            "dividends": len(calendar.get("dividend_events") or []) if isinstance(calendar.get("dividend_events"), list) else 0,
            "macro": len(calendar.get("macro_events") or []) if isinstance(calendar.get("macro_events"), list) else 0,
        }

    def _build_sentiment_heat(self, items: List[Dict[str, Any]], observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        calendar = self._last_event_calendar if isinstance(self._last_event_calendar, dict) else {}
        event_counts = self._event_counts(calendar)
        event_count = sum(event_counts.values())
        news_count = len([item for item in items if isinstance(item, dict)])
        discussion_proxy_score = min(1.0, (news_count / 8.0) * 0.7 + (event_count / 6.0) * 0.3)
        if news_count >= 6 or event_count >= 4:
            level = "elevated"
        elif news_count >= 3 or event_count >= 2:
            level = "active"
        elif news_count > 0:
            level = "normal"
        else:
            level = "thin"
        return {
            "level": level,
            "news_count": news_count,
            "sentiment_observation_count": len(observations),
            "event_count": event_count,
            "event_counts": event_counts,
            "discussion_proxy_score": round(discussion_proxy_score, 4),
            "discussion_proxy": "news_volume_plus_event_calendar",
        }

    def _news_title(self, item: Dict[str, Any]) -> str:
        return str(item.get("headline") or item.get("title") or "").strip()

    def _item_impact_score(self, item: Dict[str, Any]) -> float:
        for key in ("impact_score", "impact", "relevance_score"):
            score = self._coerce_float(item.get(key))
            if score is not None:
                return max(0.0, min(1.0, score))
        rel = item.get("source_reliability")
        rel_score = self._coerce_float(rel.get("reliability_score")) if isinstance(rel, dict) else None
        confidence = self._coerce_float(item.get("confidence"))
        base = rel_score if rel_score is not None else confidence
        base = float(base) if base is not None else 0.5
        lowered = self._news_title(item).lower()
        catalyst_keywords = (
            # English
            "beat",
            "beats",
            "miss",
            "earnings",
            "revenue",
            "guidance",
            "approval",
            "launch",
            "upgrade",
            "downgrade",
            "lawsuit",
            "investigation",
            "merger",
            "acquisition",
            "dividend",
            # 中文（P0-9: A股新闻催化识别）
            "财报",
            "业绩",
            "超预期",
            "不及预期",
            "净利润",
            "营收",
            "减持",
            "增持",
            "立案",
            "重组",
            "并购",
            "中标",
            "回购",
            "停牌",
            "分红",
            "解禁",
        )
        if any(token in lowered for token in catalyst_keywords):
            return max(base, 0.72)
        return min(base, 0.6)

    def _build_catalyst_events(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        events: List[Dict[str, Any]] = []
        calendar = self._last_event_calendar if isinstance(self._last_event_calendar, dict) else {}
        for key, category in (
            ("earnings_events", "earnings"),
            ("dividend_events", "dividend"),
            ("macro_events", "macro"),
        ):
            raw_events = calendar.get(key)
            if not isinstance(raw_events, list):
                continue
            for event in raw_events[:4]:
                if not isinstance(event, dict):
                    continue
                title = str(event.get("title") or event.get("event") or category).strip()
                events.append(
                    {
                        "kind": "event_calendar",
                        "category": category,
                        "title": title,
                        "date": event.get("date"),
                        "source": event.get("source") or "event_calendar",
                    }
                )

        high_impact_news = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            impact_score = self._item_impact_score(item)
            if impact_score < 0.7:
                continue
            high_impact_news += 1
            events.append(
                {
                    "kind": "news",
                    "category": "high_impact_news",
                    "title": self._news_title(item),
                    "date": item.get("datetime") or item.get("published_at"),
                    "source": item.get("source") or "news",
                    "impact_score": round(impact_score, 4),
                }
            )

        return {
            "count": len(events),
            "events": events[:8],
            "calendar_event_count": len([event for event in events if event.get("kind") == "event_calendar"]),
            "high_impact_news_count": high_impact_news,
        }

    def _load_recent_price_signal(self, ticker: str) -> Dict[str, Any]:
        history_fn = getattr(self.tools, "get_stock_historical_data", None)
        if callable(history_fn):
            try:
                payload = self._call_ticker_tool(history_fn, ticker, period="5d", interval="1d")
                if isinstance(payload, dict):
                    rows = payload.get("kline_data") or payload.get("data") or []
                    closes = []
                    if isinstance(rows, list):
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            close = self._coerce_float(row.get("close") or row.get("Close"))
                            if close is not None and close > 0:
                                closes.append(close)
                    if len(closes) >= 2:
                        change_pct = (closes[-1] - closes[0]) / closes[0] * 100.0
                        return {
                            "status": "ok",
                            "source": payload.get("source") or "get_stock_historical_data",
                            "price_change_pct": round(change_pct, 4),
                            "window": payload.get("period") or "5d",
                        }
            except Exception:
                pass

        quote_fn = getattr(self.tools, "get_stock_price", None)
        if callable(quote_fn):
            try:
                payload = self._call_ticker_tool(quote_fn, ticker)
                if isinstance(payload, dict):
                    for key in ("change_percent", "change_pct", "pct_change"):
                        change_pct = self._coerce_float(payload.get(key))
                        if change_pct is not None:
                            return {
                                "status": "ok",
                                "source": payload.get("source") or "get_stock_price",
                                "price_change_pct": round(change_pct, 4),
                                "window": "quote_change",
                            }
                if isinstance(payload, str):
                    match = re.search(r"Change[^%]*\(\s*([+-]?\d+(?:\.\d+)?)%\s*\)", payload, flags=re.IGNORECASE)
                    if match:
                        return {
                            "status": "ok",
                            "source": "get_stock_price",
                            "price_change_pct": round(float(match.group(1)), 4),
                            "window": "quote_change",
                        }
            except Exception:
                pass

        return {
            "status": "todo",
            "source": None,
            "price_change_pct": None,
            "window": None,
            "todo": "TODO: 接入 get_stock_historical_data 或可解析的 get_stock_price 变动字段后评估舆情到价格的传导。",
        }

    def _build_price_transmission(self, ticker: str, sentiment_label: str) -> Dict[str, Any]:
        signal = self._load_recent_price_signal(ticker)
        change_pct = signal.get("price_change_pct")
        if not isinstance(change_pct, (int, float)):
            return {
                "status": "todo",
                "sentiment_direction": sentiment_label,
                "price_direction": "unknown",
                "price_change_pct": None,
                "source": signal.get("source"),
                "window": signal.get("window"),
                "analysis": signal.get("todo") or "TODO: price signal unavailable.",
            }

        if change_pct >= 0.5:
            price_direction = "up"
        elif change_pct <= -0.5:
            price_direction = "down"
        else:
            price_direction = "flat"

        if sentiment_label == "bullish" and price_direction == "down":
            status = "divergence"
            analysis = "整体舆情偏多，但近期价格走弱，存在情绪与价格背离。"
        elif sentiment_label == "bearish" and price_direction == "up":
            status = "divergence"
            analysis = "整体舆情偏空，但近期价格走强，存在情绪与价格背离。"
        elif sentiment_label == "bullish" and price_direction == "up":
            status = "resonance"
            analysis = "偏多舆情与近期价格上行共振。"
        elif sentiment_label == "bearish" and price_direction == "down":
            status = "resonance"
            analysis = "偏空舆情与近期价格下行共振。"
        else:
            status = "neutral"
            analysis = "舆情方向或价格方向不够明确，暂未形成强共振/背离。"

        return {
            "status": status,
            "sentiment_direction": sentiment_label,
            "price_direction": price_direction,
            "price_change_pct": round(float(change_pct), 4),
            "source": signal.get("source"),
            "window": signal.get("window"),
            "analysis": analysis,
        }

    def _build_sentiment_snapshot(self, ticker: str, items: List[Dict[str, Any]]) -> NewsSentimentSnapshot:
        payload = self._load_news_sentiment_payload(ticker)
        parsed = self._parse_news_sentiment_payload(payload)
        observations = list(parsed.get("observations") or [])
        for item in items:
            observation = self._extract_item_sentiment(item)
            if observation:
                observations.append(observation)

        bias = self._build_sentiment_bias(observations, parsed.get("explicit_average"))
        return NewsSentimentSnapshot(
            ticker=str(ticker or "").upper(),
            as_of=datetime.now().isoformat(),
            sentiment_bias=bias,
            sentiment_trend=self._build_sentiment_trend(observations),
            heat=self._build_sentiment_heat(items, observations),
            catalyst_events=self._build_catalyst_events(items),
            price_transmission=self._build_price_transmission(str(ticker or "").upper(), str(bias.get("label") or "neutral")),
            inputs={
                "sentiment_tool_status": parsed.get("status"),
                "sentiment_tool_preview": parsed.get("raw_preview"),
                "reliability_summary": self._last_reliability_summary,
            },
        )

    def _snapshot_text(self, snapshot: NewsSentimentSnapshot) -> str:
        bias = snapshot.sentiment_bias
        trend = snapshot.sentiment_trend
        heat = snapshot.heat
        catalysts = snapshot.catalyst_events
        price = snapshot.price_transmission
        avg = bias.get("average_score")
        avg_text = f"{avg:+.2f}" if isinstance(avg, (int, float)) else "N/A"
        return (
            f"{snapshot.ticker} 整体舆情: {bias.get('label', 'neutral')} "
            f"(平均分 {avg_text}, 正/负/中占比 "
            f"{bias.get('positive_ratio', 0):.0%}/{bias.get('negative_ratio', 0):.0%}/{bias.get('neutral_ratio', 0):.0%}); "
            f"趋势: {trend.get('direction', 'unknown')}; "
            f"热度: {heat.get('level', 'normal')} (新闻 {heat.get('news_count', 0)} 条, 事件 {heat.get('event_count', 0)} 个); "
            f"催化事件: {catalysts.get('count', 0)} 个; "
            f"价格传导: {price.get('status', 'unknown')}。"
        )

    def _snapshot_has_aggregate_signal(self, snapshot: NewsSentimentSnapshot) -> bool:
        bias = snapshot.sentiment_bias
        catalysts = snapshot.catalyst_events
        price = snapshot.price_transmission
        if int(bias.get("sample_size") or 0) > 0:
            return True
        if int(catalysts.get("count") or 0) > 0:
            return True
        if price.get("price_change_pct") is not None:
            return True
        return False

    async def _initial_search(self, query: str, ticker: str) -> List[Any]:
        cache_key = f"{ticker}:news:24h"
        self._last_event_calendar = {}
        self._last_reliability_summary = {}
        self._last_sentiment_snapshot = None
        cached = self.cache.get(cache_key)
        if isinstance(cached, list):
            annotated_cached = self._annotate_reliability(cached)
            self._last_reliability_summary = self._summarize_reliability(annotated_cached)
            self._last_event_calendar = self._load_event_calendar(ticker)
            self._last_sentiment_snapshot = self._build_sentiment_snapshot(ticker, annotated_cached)
            return annotated_cached

        results = []

        # 1) Prefer finnhub-style tool when available (aligns with stream path + tests)
        finnhub_news = getattr(self.tools, "_fetch_with_finnhub_news", None)
        if finnhub_news and self.circuit_breaker.can_call("finnhub"):
            try:
                finnhub_items = finnhub_news(ticker)
                if isinstance(finnhub_items, list):
                    for item in finnhub_items:
                        if not isinstance(item, dict):
                            continue
                        item.setdefault("ticker", ticker)
                        item.setdefault("source", "finnhub")
                        results.append(item)
                    if results:
                        self.circuit_breaker.record_success("finnhub")
            except Exception as e:
                logger.info(f"[NewsAgent] _fetch_with_finnhub_news failed: {e}")
                self.circuit_breaker.record_failure("finnhub")

        # 2) Fallback to get_company_news if finnhub tool not present
        if not results and self.circuit_breaker.can_call("news_api"):
            try:
                get_news = getattr(self.tools, "get_company_news", None)
                if get_news:
                    news_data = get_news(ticker)
                    if isinstance(news_data, list):
                        for item in news_data:
                            if not isinstance(item, dict):
                                continue
                            item.setdefault("ticker", ticker)
                            results.append(item)
                        if results:
                            self.circuit_breaker.record_success("news_api")
                    elif news_data and isinstance(news_data, str) and "No " not in news_data:
                        parsed_news = self._parse_news_text(news_data, ticker)
                        if parsed_news:
                            results.extend(parsed_news)
                            self.circuit_breaker.record_success("news_api")
            except Exception as e:
                logger.info(f"[NewsAgent] get_company_news failed: {e}")
                self.circuit_breaker.record_failure("news_api")

        # 3) Secondary fallback to tavily-style tool
        if len(results) < 3 and self.circuit_breaker.can_call("tavily"):
            try:
                search_news = getattr(self.tools, "_search_company_news", None)
                if search_news:
                    t_results = search_news(f"{ticker} stock news")
                    if isinstance(t_results, list):
                        for item in t_results:
                            if not isinstance(item, dict):
                                continue
                            item.setdefault("ticker", ticker)
                            item.setdefault("source", "tavily")
                            results.append(item)
                        if t_results:
                            self.circuit_breaker.record_success("tavily")
            except Exception as e:
                logger.info(f"[NewsAgent] _search_company_news failed: {e}")
                self.circuit_breaker.record_failure("tavily")

        # 4) Legacy text search fallback
        if len(results) < 3 and self.circuit_breaker.can_call("search"):
            try:
                search_func = getattr(self.tools, "search", None)
                if search_func:
                    search_text = search_func(f"{ticker} stock news latest")
                    if search_text and isinstance(search_text, str):
                        parsed_search = self._parse_search_results(search_text, ticker)
                        if parsed_search:
                            results.extend(parsed_search)
                            self.circuit_breaker.record_success("search")
            except Exception as e:
                logger.info(f"[NewsAgent] search fallback failed: {e}")
                self.circuit_breaker.record_failure("search")

        # Deduplicate (title-level)
        normalized_results: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            cloned = dict(item)
            cloned["url"] = self._recover_original_article_url(cloned.get("url"))
            normalized_results.append(cloned)

        seen_titles = set()
        unique_results = []
        for item in normalized_results:
            title = item.get("headline", item.get("title", ""))
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_results.append(item)

        # Apply search convergence (content-level dedupe + info gain)
        try:
            from backend.agents.search_convergence import SearchConvergence
            sc = SearchConvergence()
            docs = []
            for item in unique_results:
                docs.append({
                    "url": item.get("url", ""),
                    "content": item.get("headline", item.get("title", "")),
                    "source": item.get("source", "news"),
                    "_item": item,
                })
            filtered_docs, metrics = sc.process_round(docs, previous_summary="")
            self._last_convergence = asdict(metrics)
            unique_results = [doc.get("_item") for doc in filtered_docs if doc.get("_item")]
        except Exception:
            self._last_convergence = None

        strict_sources = str(os.getenv("NEWS_STRICT_FINANCE_SOURCES", "true")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if strict_sources and self._is_finance_research_intent(query):
            authoritative = self._filter_authoritative_news(unique_results)
            if not authoritative:
                feed_tool = getattr(self.tools, "get_authoritative_media_news", None)
                if callable(feed_tool):
                    try:
                        payload = feed_tool(
                            query=f"{ticker} earnings outlook",
                            max_results=5,
                            authoritative_only=True,
                        )
                        if isinstance(payload, str):
                            try:
                                payload = json.loads(payload)
                            except Exception:
                                payload = {}
                        articles = payload.get("articles") if isinstance(payload, dict) else []
                        if isinstance(articles, list):
                            for article in articles:
                                if not isinstance(article, dict):
                                    continue
                                url = self._recover_original_article_url(article.get("url"))
                                if not url:
                                    continue
                                unique_results.append(
                                    {
                                        "headline": article.get("title") or "",
                                        "title": article.get("title") or "",
                                        "url": url,
                                        "source": article.get("source") or "authoritative_feed",
                                        "datetime": article.get("published_date"),
                                        "published_at": article.get("published_date"),
                                        "ticker": ticker,
                                        "confidence": article.get("confidence", 0.8),
                                    }
                                )
                    except Exception:
                        pass
                authoritative = self._filter_authoritative_news(unique_results)
            if authoritative:
                unique_results = authoritative

        unique_results = self._annotate_reliability(unique_results)
        self._last_reliability_summary = self._summarize_reliability(unique_results)
        self._last_event_calendar = self._load_event_calendar(ticker)
        self._last_sentiment_snapshot = self._build_sentiment_snapshot(ticker, unique_results)

        if unique_results:
            self.cache.set(cache_key, unique_results, self.CACHE_TTL)
        return unique_results

    def _parse_news_text(self, news_text: str, ticker: str) -> List[Dict[str, Any]]:
        """解析 get_company_news 返回的格式化文本为结构化数据"""
        import re
        results = []

        # 格式示例: "1. 2025-01-13 - [Title](url) - Source [Tags]"
        lines = news_text.split('\n')
        for line in lines:
            if not line.strip() or line.startswith('Latest'):
                continue

            # 提取标题和URL
            url_match = re.search(r'\[([^\]]+)\]\(([^)]+)\)', line)
            if url_match:
                title = url_match.group(1)
                url = url_match.group(2)
            else:
                # 没有URL格式，直接提取文本
                title = re.sub(r'^\d+\.\s*[\d-]*\s*-?\s*', '', line).strip()
                url = ""

            # 提取日期
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            date_str = date_match.group(1) if date_match else ""

            # 提取来源
            source_match = re.search(r'-\s+([A-Za-z0-9\s]+)\s*\[', line)
            source = source_match.group(1).strip() if source_match else "Unknown"

            if title and len(title) > 10:
                results.append({
                    "headline": title,
                    "title": title,
                    "url": url,
                    "source": source,
                    "datetime": date_str,
                    "published_at": date_str,
                    "ticker": ticker,
                    "confidence": 0.7,
                })

        return results

    def _parse_search_results(self, search_text: str, ticker: str) -> List[Dict[str, Any]]:
        """解析搜索结果为新闻格式"""
        import re
        results = []

        lines = search_text.split('\n')
        for line in lines:
            if not line.strip():
                continue

            # 提取URL
            url_match = re.search(r'https?://[^\s\)]+', line)
            url = url_match.group(0) if url_match else ""

            # 提取标题（去除URL和标点）
            title = re.sub(r'https?://[^\s]+', '', line)
            title = re.sub(r'^\d+\.\s*', '', title).strip()
            title = title[:150] if len(title) > 150 else title

            if title and len(title) > 15:
                results.append({
                    "headline": title,
                    "title": title,
                    "url": url,
                    "source": "search",
                    "published_at": None,
                    "datetime": None,
                    "ticker": ticker,
                    "confidence": 0.4,
                })

        return results[:5]  # 限制数量

    async def _first_summary(self, data: List[Any]) -> str:
        """P0-9: 输出舆情简报（确定性骨架 + LLM 观点段）"""
        if not data:
            return "未找到相关新闻。"

        snapshot = self._last_sentiment_snapshot
        snapshot_dict = asdict(snapshot) if isinstance(snapshot, NewsSentimentSnapshot) else {}

        # LLM 观点段（唯一的 LLM 依赖，失败时为 None -> 骨架照常输出）
        opinion = None
        if self.llm is not None:
            news_context_parts = []
            for item in data[:8]:
                if not isinstance(item, dict):
                    continue
                headline = item.get("headline", item.get("title", ""))
                source = item.get("source", "")
                date = item.get("datetime", item.get("published_at", ""))
                meta = f" ({source}" + (f", {date}" if date else "") + ")" if source else ""
                news_context_parts.append(f"- {headline}{meta}")
            news_context = "\n".join(news_context_parts)
            snapshot_summary = self._snapshot_text(snapshot) if isinstance(snapshot, NewsSentimentSnapshot) else ""

            opinion = await self._llm_analyze(
                f"舆情快照：{snapshot_summary}\n\n新闻列表：\n{news_context}",
                role="资深舆情分析师",
                focus=(
                    "基于舆情快照和新闻列表，输出 2-4 句核心观点：\n"
                    "1. 识别 1-2 条驱动舆情的主线事件\n"
                    "2. 说明事件对标的的影响路径\n"
                    "3. 给出短期方向判断（结合情绪与价格关系）\n"
                    "要求：连贯段落、不用列表、不复述新闻标题、中文输出。"
                ),
            )

        # 风险（来源可靠度警告）
        extra_risks: List[str] = []
        reliability_summary = self._last_reliability_summary if isinstance(self._last_reliability_summary, dict) else {}
        avg_rel = reliability_summary.get("avg_reliability")
        if isinstance(avg_rel, (int, float)) and float(avg_rel) < 0.65:
            extra_risks.append("新闻来源整体可靠度偏低，关键结论建议以官方披露为准")

        if snapshot_dict:
            return render_stock_brief(snapshot_dict, list(data), opinion, extra_risks=extra_risks)
        return self._deterministic_summary(data)

    def _deterministic_summary(self, data: List[Any]) -> str:
        """Simple headline concatenation (fallback)."""
        if not data:
            return "No recent news found."
        snapshot = self._last_sentiment_snapshot
        titles = [item.get("headline", item.get("title", "")) for item in data[:5]]
        if isinstance(snapshot, NewsSentimentSnapshot) and self._snapshot_has_aggregate_signal(snapshot):
            summary = self._snapshot_text(snapshot)
            if titles:
                summary += f" 核心新闻: {'; '.join(titles)}"
        else:
            summary = f"Recent news includes: {'; '.join(titles)}"
        calendar = self._last_event_calendar if isinstance(self._last_event_calendar, dict) else {}
        earnings_count = len(calendar.get("earnings_events") or []) if isinstance(calendar.get("earnings_events"), list) else 0
        dividend_count = len(calendar.get("dividend_events") or []) if isinstance(calendar.get("dividend_events"), list) else 0
        macro_count = len(calendar.get("macro_events") or []) if isinstance(calendar.get("macro_events"), list) else 0
        if earnings_count or dividend_count or macro_count:
            summary += (
                f" | Event calendar: earnings={earnings_count},"
                f" dividends={dividend_count}, macro={macro_count}"
            )
        return summary

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence = []
        sources = set()
        fallback_used = False
        ticker = (
            str(raw_data[0].get("ticker") or "")
            if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict)
            else str(self._current_ticker or "")
        )

        # Handle None or non-list raw_data
        if raw_data and isinstance(raw_data, list):
            for item in raw_data:
                if isinstance(item, dict):
                    source = item.get("source", "unknown")
                    sources.add(source)
                    source_reliability = item.get("source_reliability") if isinstance(item.get("source_reliability"), dict) else {}
                    rel_score = source_reliability.get("reliability_score")
                    confidence = item.get("confidence", 0.7)
                    if isinstance(rel_score, (int, float)):
                        confidence = max(0.1, min(0.95, float(rel_score)))
                    evidence.append(EvidenceItem(
                        text=item.get("headline", item.get("title", "")),
                        source=source,
                        url=item.get("url"),
                        timestamp=item.get("datetime", item.get("published_at")),
                        confidence=confidence,
                        meta={"source_reliability": source_reliability} if source_reliability else {},
                    ))
        else:
            fallback_used = True

        trace = []
        if self._last_convergence:
            try:
                from backend.orchestration.trace_schema import create_trace_event
                trace.append(create_trace_event(
                    "convergence_check",
                    agent=self.AGENT_NAME,
                    **self._last_convergence,
                ))
            except Exception:
                pass

        # Fallback observability
        fallback_reason = None
        if not evidence:
            fallback_used = True
            fallback_reason = "no_news_data"

        risks: List[str] = []
        reliability_summary = self._last_reliability_summary if isinstance(self._last_reliability_summary, dict) else {}
        avg_reliability = reliability_summary.get("avg_reliability")
        low_count = reliability_summary.get("low_reliability_count")
        if isinstance(avg_reliability, (int, float)) and float(avg_reliability) < 0.65:
            risks.append("News source reliability is low; validate key claims with primary disclosures.")
        if isinstance(low_count, int) and low_count >= 2:
            risks.append("Multiple low-reliability sources detected in this batch.")

        event_calendar = self._last_event_calendar if isinstance(self._last_event_calendar, dict) else {}
        if event_calendar:
            earnings_count = len(event_calendar.get("earnings_events") or []) if isinstance(event_calendar.get("earnings_events"), list) else 0
            dividend_count = len(event_calendar.get("dividend_events") or []) if isinstance(event_calendar.get("dividend_events"), list) else 0
            macro_count = len(event_calendar.get("macro_events") or []) if isinstance(event_calendar.get("macro_events"), list) else 0
            if earnings_count or dividend_count or macro_count:
                evidence.append(
                    EvidenceItem(
                        text=(
                            f"Event calendar snapshot: earnings={earnings_count}, "
                            f"dividends={dividend_count}, macro={macro_count}"
                        ),
                        source="event_calendar",
                        timestamp=str(event_calendar.get("as_of") or datetime.now().isoformat()),
                        meta=event_calendar,
                    )
                )
                sources.add("event_calendar")

        if self._last_sentiment_snapshot is None and isinstance(raw_data, list):
            self._last_sentiment_snapshot = self._build_sentiment_snapshot(ticker, raw_data)
        snapshot = self._last_sentiment_snapshot
        snapshot_dict: Dict[str, Any] = {}
        if isinstance(snapshot, NewsSentimentSnapshot) and self._snapshot_has_aggregate_signal(snapshot):
            snapshot_dict = asdict(snapshot)
            bias_confidence = snapshot.sentiment_bias.get("confidence")
            snapshot_confidence = float(bias_confidence) if isinstance(bias_confidence, (int, float)) else 0.55
            snapshot_confidence = max(0.55, snapshot_confidence)
            evidence.append(
                EvidenceItem(
                    text=self._snapshot_text(snapshot),
                    source="news_sentiment_snapshot",
                    timestamp=snapshot.as_of,
                    confidence=max(0.1, min(0.9, snapshot_confidence)),
                    meta={"snapshot": snapshot_dict},
                )
            )
            sources.add("news_sentiment_snapshot")

        output_confidence = 0.8 if evidence else 0.1
        if isinstance(avg_reliability, (int, float)):
            output_confidence = max(0.1, min(0.9, float(avg_reliability)))
        assign_evidence_source_ids(evidence, agent_name=self.AGENT_NAME)
        claims = self._build_native_claims(
            query=self._current_query or "",
            ticker=ticker,
            evidence=evidence,
            confidence=output_confidence,
        )

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=output_confidence,
            data_sources=list(sources) if sources else ["news"],
            as_of=datetime.now().isoformat(),
            claims=claims,
            chart_specs=build_news_sentiment_chart_specs(snapshot_dict),
            fallback_used=fallback_used,
            trace=trace,
            risks=risks,
            fallback_reason=fallback_reason,
            retryable=True,
        )

    def _build_snapshot_claims(
        self,
        *,
        query: str,
        ticker: str,
        snapshot_item: EvidenceItem,
        confidence: float,
    ) -> List[Dict[str, Any]]:
        if not isinstance(snapshot_item.meta, dict):
            return []
        source_id = str(snapshot_item.meta.get("source_id") or "").strip()
        snapshot = snapshot_item.meta.get("snapshot")
        if not source_id or not isinstance(snapshot, dict):
            return []

        ticker_value = str(snapshot.get("ticker") or ticker or "").strip()
        bias = snapshot.get("sentiment_bias") if isinstance(snapshot.get("sentiment_bias"), dict) else {}
        catalysts = snapshot.get("catalyst_events") if isinstance(snapshot.get("catalyst_events"), dict) else {}
        price = snapshot.get("price_transmission") if isinstance(snapshot.get("price_transmission"), dict) else {}

        bias_label = str(bias.get("label") or "neutral")
        stance = {"bullish": "bull", "bearish": "bear"}.get(bias_label, "neutral")
        avg_score = bias.get("average_score")
        avg_text = f"{avg_score:+.2f}" if isinstance(avg_score, (int, float)) else "N/A"
        snapshot_confidence = self._coerce_float(bias.get("confidence"))
        claim_confidence = max(0.3, min(0.9, snapshot_confidence if snapshot_confidence is not None else confidence))

        claims = [
            build_agent_claim(
                agent_name=self.AGENT_NAME,
                ticker=ticker_value,
                query=query,
                claim=(
                    f"{ticker_value} aggregate news sentiment bias is {bias_label} "
                    f"(average sentiment score {avg_text})."
                ),
                evidence_ids=[source_id],
                stance=stance,
                confidence=claim_confidence,
                limitations=["Aggregate sentiment is only as complete as the available news sentiment feed and headlines."],
                metadata={
                    "claim_type": "sentiment_bias",
                    "positive_ratio": bias.get("positive_ratio"),
                    "negative_ratio": bias.get("negative_ratio"),
                    "neutral_ratio": bias.get("neutral_ratio"),
                    "sample_size": bias.get("sample_size"),
                },
            )
        ]

        catalyst_count = int(catalysts.get("count") or 0)
        claims.append(
            build_agent_claim(
                agent_name=self.AGENT_NAME,
                ticker=ticker_value,
                query=query,
                claim=f"{ticker_value} has {catalyst_count} aggregated news/calendar catalyst events in the current sentiment window.",
                evidence_ids=[source_id],
                stance="risk" if catalyst_count else "neutral",
                confidence=min(0.85, confidence),
                limitations=["Catalyst aggregation identifies timing/attention drivers; it does not prove price direction by itself."],
                metadata={
                    "claim_type": "catalyst_events",
                    "count": catalyst_count,
                    "calendar_event_count": catalysts.get("calendar_event_count"),
                    "high_impact_news_count": catalysts.get("high_impact_news_count"),
                },
            )
        )

        price_status = str(price.get("status") or "unknown")
        price_stance = "risk" if price_status == "divergence" else stance if price_status == "resonance" else "neutral"
        claims.append(
            build_agent_claim(
                agent_name=self.AGENT_NAME,
                ticker=ticker_value,
                query=query,
                claim=(
                    f"{ticker_value} sentiment-price transmission status is {price_status}: "
                    f"{price.get('analysis') or 'insufficient price signal.'}"
                ),
                evidence_ids=[source_id],
                stance=price_stance,
                confidence=min(0.8, confidence),
                limitations=["Price transmission uses recent available price data; intraday or after-hours moves may be missing."],
                metadata={
                    "claim_type": "sentiment_price_divergence",
                    "status": price_status,
                    "price_change_pct": price.get("price_change_pct"),
                    "price_source": price.get("source"),
                    "window": price.get("window"),
                },
            )
        )
        return claims

    def _build_native_claims(
        self,
        *,
        query: str,
        ticker: str,
        evidence: List[EvidenceItem],
        confidence: float,
    ) -> List[Dict[str, Any]]:
        claims: List[Dict[str, Any]] = []
        for item in evidence:
            if item.source == "news_sentiment_snapshot":
                claims.extend(
                    self._build_snapshot_claims(
                        query=query,
                        ticker=ticker,
                        snapshot_item=item,
                        confidence=confidence,
                    )
                )
                break

        for item in evidence[:6]:
            source_id = str((item.meta or {}).get("source_id") or "").strip()
            if not source_id:
                continue
            source_name = str(item.source or "news")
            if source_name == "news_sentiment_snapshot":
                continue
            headline = str(item.text or "").strip()
            if not headline:
                continue

            if source_name == "event_calendar":
                claims.append(
                    build_agent_claim(
                        agent_name=self.AGENT_NAME,
                        ticker=ticker,
                        query=query,
                        claim=f"{ticker} has upcoming scheduled events that can change the news impact window.",
                        evidence_ids=[source_id],
                        stance="risk",
                        confidence=min(0.85, confidence),
                        limitations=["Event calendar marks timing risk; it does not prove direction by itself."],
                        metadata={"claim_type": "event_calendar"},
                    )
                )
                continue

            rel = item.meta.get("source_reliability") if isinstance(item.meta, dict) else {}
            rel_score = rel.get("reliability_score") if isinstance(rel, dict) else None
            score = float(rel_score) if isinstance(rel_score, (int, float)) else float(item.confidence or 0.5)
            lowered = headline.lower()
            is_primary_catalyst = score >= 0.85 and any(
                token in lowered
                for token in ("beat", "beats", "earnings", "revenue", "guidance", "approval", "launch")
            )
            if is_primary_catalyst:
                claim_type = "catalyst_candidate"
                stance = "bull" if any(token in lowered for token in ("beat", "beats", "strong", "upgrade")) else "neutral"
                claim_text = f"{ticker} news catalyst candidate: {headline}"
                limitations = ["Catalyst classification needs confirmation from primary filings or management commentary."]
            else:
                claim_type = "noise_or_secondary_signal"
                stance = "neutral"
                claim_text = f"{ticker} secondary news signal or potential noise: {headline}"
                limitations = ["Secondary market-media signal; avoid treating it as standalone investment evidence."]

            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=claim_text,
                    evidence_ids=[source_id],
                    stance=stance,
                    confidence=max(0.3, min(0.9, score)),
                    limitations=limitations,
                    metadata={"claim_type": claim_type, "source_reliability": round(score, 4)},
                )
            )
        return claims[:9]

    async def analyze_stream(self, query: str, ticker: str):
        """
        NewsAgent 专属流式分析
        实时显示各数据源搜索状态和新闻摘要生成
        """
        import json
        
        # 1. 通知开始
        yield json.dumps({
            "type": "agent_start",
            "agent": self.AGENT_NAME,
            "message": f"正在搜索 {ticker} 相关新闻..."
        }, ensure_ascii=False)
        
        # 2. 检查缓存
        cache_key = f"{ticker}:news:24h"
        cached = self.cache.get(cache_key)
        if cached:
            yield json.dumps({
                "type": "cache_hit",
                "agent": self.AGENT_NAME,
                "count": len(cached)
            }, ensure_ascii=False)
            results = cached
        else:
            results = []
            
            # 3. 逐个数据源搜索
            # Finnhub
            yield json.dumps({
                "type": "source_start",
                "source": "finnhub",
                "message": "正在检索 Finnhub 新闻..."
            }, ensure_ascii=False)
            
            if self.circuit_breaker.can_call("finnhub"):
                try:
                    finnhub_news = getattr(self.tools, "_fetch_with_finnhub_news", None)
                    if finnhub_news:
                        news_items = finnhub_news(ticker)
                        if news_items:
                            results.extend(news_items)
                            self.circuit_breaker.record_success("finnhub")
                            yield json.dumps({
                                "type": "source_done",
                                "source": "finnhub",
                                "count": len(news_items),
                                "status": "success"
                            }, ensure_ascii=False)
                        else:
                            yield json.dumps({
                                "type": "source_done",
                                "source": "finnhub",
                                "count": 0,
                                "status": "empty"
                            }, ensure_ascii=False)
                except Exception as e:
                    self.circuit_breaker.record_failure("finnhub")
                    yield json.dumps({
                        "type": "source_done",
                        "source": "finnhub",
                        "status": "error",
                        "message": str(e)
                    }, ensure_ascii=False)
            else:
                yield json.dumps({
                    "type": "source_done",
                    "source": "finnhub",
                    "status": "circuit_open",
                    "message": "熔断器开启，跳过"
                }, ensure_ascii=False)
            
            # Tavily
            if not results or len(results) < 3:
                yield json.dumps({
                    "type": "source_start",
                    "source": "tavily",
                    "message": "正在检索 Tavily 新闻..."
                }, ensure_ascii=False)
                
                if self.circuit_breaker.can_call("tavily"):
                    try:
                        tavily_news = getattr(self.tools, "_search_company_news", None)
                        if tavily_news:
                            t_results = tavily_news(f"{ticker} stock news")
                            if t_results:
                                results.extend(t_results)
                                self.circuit_breaker.record_success("tavily")
                                yield json.dumps({
                                    "type": "source_done",
                                    "source": "tavily",
                                    "count": len(t_results),
                                    "status": "success"
                                }, ensure_ascii=False)
                    except Exception as e:
                        self.circuit_breaker.record_failure("tavily")
                        yield json.dumps({
                            "type": "source_done",
                            "source": "tavily",
                            "status": "error"
                        }, ensure_ascii=False)
            
            # 去重并缓存
            seen_urls = set()
            unique_results = []
            for item in results:
                url = item.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_results.append(item)
            results = unique_results
            
            if results:
                self.cache.set(cache_key, results, self.CACHE_TTL)
        
        # 4. 报告搜索结果
        yield json.dumps({
            "type": "search_result",
            "agent": self.AGENT_NAME,
            "count": len(results)
        }, ensure_ascii=False)
        
        # 5. 生成摘要
        yield json.dumps({
            "type": "summary_start",
            "agent": self.AGENT_NAME
        }, ensure_ascii=False)
        
        summary_buffer = ""
        async for token in self._stream_summary(results):
            summary_buffer += token
            yield json.dumps({
                "type": "token",
                "content": token
            }, ensure_ascii=False)
        
        # 6. 完成
        output = self._format_output(summary_buffer, results)
        yield json.dumps({
            "type": "done",
            "agent": self.AGENT_NAME,
            "output": {
                "agent_name": output.agent_name,
                "summary": output.summary,
                "confidence": output.confidence,
                "evidence_count": len(output.evidence),
                "data_sources": output.data_sources,
                "as_of": output.as_of
            }
        }, ensure_ascii=False)

    async def _stream_summary(self, data: List[Any]):
        """
        流式生成新闻摘要
        如果 LLM 可用则使用流式输出，否则使用简单方法
        """
        if not data:
            yield "未找到相关新闻。"
            return
        
        # 构建新闻列表
        news_list = []
        for item in data[:5]:
            headline = item.get("headline", item.get("title", ""))
            source = item.get("source", "")
            if headline:
                news_list.append(f"- {headline} ({source})")
        
        # 如果有 LLM，尝试流式生成
        if self.llm and hasattr(self.llm, 'astream'):
            try:
                from langchain_core.messages import HumanMessage
                prompt = f"""<role>资深金融新闻分析师</role>

<task>基于以下新闻列表，输出一份专业的中文新闻摘要分析（150-250字）。</task>

<news>
{chr(10).join(news_list)}
</news>

<requirements>
- 提炼 3-5 条核心要点，每条包含：事实 + 市场影响判断
- 识别新闻间的关联性（如多条新闻指向同一趋势）
- 明确标注 1-2 个潜在风险或不确定性
- 区分短期噪音和中长期趋势信号
</requirements>

<constraints>
- 禁止复述新闻标题原文，必须提炼和解读
- 禁止开场白，直接输出分析内容
- 专业简洁，避免冗余表述
</constraints>"""
                async for chunk in self.llm.astream([HumanMessage(content=prompt)]):
                    if hasattr(chunk, 'content') and chunk.content:
                        yield chunk.content
                return
            except Exception as stream_exc:
                logger.info(f"[NewsAgent] stream summary failed, fallback to retry invoke: {stream_exc}")
                try:
                    from backend.services.llm_retry import ainvoke_with_rate_limit_retry

                    llm_factory = None
                    try:
                        from backend.llm_config import create_llm

                        provider = os.getenv("LLM_PROVIDER", "openai_compatible")
                        temperature = float(os.getenv("NEWS_LLM_TEMPERATURE", "0.3"))
                        request_timeout = int(os.getenv("NEWS_LLM_REQUEST_TIMEOUT", "600"))
                        llm_factory = lambda: create_llm(  # noqa: E731
                            provider=provider,
                            temperature=temperature,
                            request_timeout=request_timeout,
                        )
                    except Exception:
                        llm_factory = None

                    max_attempts = max(1, int(os.getenv("NEWS_LLM_MAX_ATTEMPTS", "3")))
                    resp = await ainvoke_with_rate_limit_retry(
                        self.llm,
                        [HumanMessage(content=prompt)],
                        llm_factory=llm_factory,
                        max_attempts=max_attempts,
                        acquire_token=True,
                    )
                    text = resp.content if hasattr(resp, "content") else str(resp)
                    text = str(text or "").strip()
                    if text:
                        yield text
                        return
                except Exception as invoke_exc:
                    logger.info(f"[NewsAgent] invoke summary fallback failed: {invoke_exc}")
        
        # 简单方法：直接拼接标题
        yield f"近期新闻包括：{'; '.join([item.get('headline', item.get('title', '')) for item in data[:3]])}"
