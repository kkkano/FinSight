from typing import Any, Dict, List, Optional
import os
import logging
import json
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

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

    def _score_reliability_for_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        scorer = getattr(self.tools, "score_news_source_reliability", None)
        if not scorer:
            return {"reliability_score": 0.55, "reliability_tier": "medium", "reason": "default"}
        try:
            payload = scorer(source=item.get("source", ""), url=item.get("url", ""))
            if isinstance(payload, dict):
                score = payload.get("reliability_score")
                if isinstance(score, (int, float)):
                    return payload
        except Exception:
            pass
        return {"reliability_score": 0.55, "reliability_tier": "medium", "reason": "default"}

    def _annotate_reliability(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        annotated: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rel = self._score_reliability_for_item(item)
            cloned = dict(item)
            cloned["source_reliability"] = rel
            score = rel.get("reliability_score")
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

    async def _initial_search(self, query: str, ticker: str) -> List[Any]:
        cache_key = f"{ticker}:news:24h"
        self._last_event_calendar = {}
        self._last_reliability_summary = {}
        cached = self.cache.get(cache_key)
        if isinstance(cached, list):
            annotated_cached = self._annotate_reliability(cached)
            self._last_reliability_summary = self._summarize_reliability(annotated_cached)
            self._last_event_calendar = self._load_event_calendar(ticker)
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
            from dataclasses import asdict
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
        deterministic = self._deterministic_summary(data)
        if not data:
            return deterministic

        # Build rich context for LLM ReAct-style analysis
        news_context_parts = []
        for item in data[:8]:
            if not isinstance(item, dict):
                continue
            headline = item.get("headline", item.get("title", ""))
            source = item.get("source", "")
            date = item.get("datetime", item.get("published_at", ""))
            url = item.get("url", "")
            meta = f" ({source}" + (f", {date}" if date else "") + ")" if source else ""
            news_context_parts.append(f"- {headline}{meta}")
        news_context = "\n".join(news_context_parts)

        analysis = await self._llm_analyze(
            f"新闻列表：\n{news_context}",
            role="资深金融新闻分析师（ReAct 推理模式）",
            focus=(
                "按 ReAct 模式分析：\n"
                "1. Observe（观察）：从新闻标题中识别 2-4 个核心主题/事件\n"
                "2. Reason（推理）：分析事件间的关联性、情绪倾向、对标的资产的影响路径\n"
                "3. Assess（评估）：区分短期噪音 vs 中长期趋势信号\n"
                "4. Risk（风险）：标注 1-2 个关键不确定性或信息缺口\n"
                "输出一段连贯的分析文本，不要使用编号列表。"
            ),
        )
        return analysis if analysis else deterministic

    def _deterministic_summary(self, data: List[Any]) -> str:
        """Simple headline concatenation (fallback)."""
        if not data:
            return "No recent news found."
        titles = [item.get("headline", item.get("title", "")) for item in data[:5]]
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

        output_confidence = 0.8 if evidence else 0.1
        if isinstance(avg_reliability, (int, float)):
            output_confidence = max(0.1, min(0.9, float(avg_reliability)))

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=output_confidence,
            data_sources=list(sources) if sources else ["news"],
            as_of=datetime.now().isoformat(),
            fallback_used=fallback_used,
            trace=trace,
            risks=risks,
            fallback_reason=fallback_reason,
            retryable=True,
        )

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
