from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime, timezone
import asyncio
import json
import os
import re
import logging
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from langchain_core.messages import HumanMessage
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.agents.search_convergence import SearchConvergence
from backend.orchestration.trace_schema import create_trace_event
from backend.security.ssrf import is_safe_url
from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class DeepSearchAgent(BaseFinancialAgent):
    """
    DeepSearchAgent - Deep research with real retrieval, PDF parsing, and Self-RAG.
    """
    AGENT_NAME = "deep_search"
    MAX_REFLECTIONS = int(os.getenv("DEEPSEARCH_MAX_REFLECTIONS", "2"))
    CACHE_TTL = 3600  # 1 hour
    MAX_RESULTS = int(os.getenv("DEEPSEARCH_MAX_RESULTS", "8"))
    MAX_DOCS = int(os.getenv("DEEPSEARCH_MAX_DOCS", "4"))
    MIN_TEXT_CHARS = int(os.getenv("DEEPSEARCH_MIN_TEXT_CHARS", "400"))
    MAX_TEXT_CHARS = int(os.getenv("DEEPSEARCH_MAX_TEXT_CHARS", "12000"))
    LLM_TOKEN_TIMEOUT_SECONDS = float(os.getenv("DEEPSEARCH_LLM_TOKEN_TIMEOUT_SECONDS", "500"))
    _POSITIVE_SIGNAL_TERMS = (
        "beat",
        "strong",
        "growth",
        "upside",
        "raised",
        "outperform",
        "bullish",
    )
    _NEGATIVE_SIGNAL_TERMS = (
        "miss",
        "weak",
        "decline",
        "downside",
        "cut",
        "underperform",
        "bearish",
        "risk",
    )
    _HIGH_RELIABILITY_SOURCE_HINTS = (
        "sec.gov",
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "investor.",
    )
    _TRUSTED_FINANCE_DOMAIN_HINTS = (
        "sec.gov",
        "investor.",
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "finance.yahoo.com",
        "marketwatch.com",
        "fool.com",
        "cnbc.com",
        "seekingalpha.com",
        "nasdaq.com",
    )
    _TRUSTED_FINANCE_DOMAINS = (
        "sec.gov",
        "www.sec.gov",
        "reuters.com",
        "www.reuters.com",
        "bloomberg.com",
        "www.bloomberg.com",
        "wsj.com",
        "www.wsj.com",
        "ft.com",
        "www.ft.com",
        "finance.yahoo.com",
        "www.finance.yahoo.com",
        "marketwatch.com",
        "www.marketwatch.com",
        "fool.com",
        "www.fool.com",
        "cnbc.com",
        "www.cnbc.com",
        "seekingalpha.com",
        "www.seekingalpha.com",
        "nasdaq.com",
        "www.nasdaq.com",
        "investor.apple.com",
        "apple.com",
        "www.apple.com",
    )
    _BLOCKED_DOMAIN_HINTS = (
        "tangxin93.com",
        "hinrijv.cc",
        "xqdyzgc.com",
        "yumiok.com",
        "playfulsoul.net",
        "mtevfryb.cc",
        "ewfvsve.cc",
        "maoyanqing.com",
    )
    _BLOCKED_TLDS = (".cc", ".xyz", ".top", ".vip", ".club", ".porn", ".sex")
    _BLOCKED_CONTENT_HINTS = (
        "成人视频",
        "乱伦",
        "群p",
        "群p",
        "porn",
        "xxx",
        "casino",
        "betting",
    )

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self._session:
            return self._session
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self._session = session
        return session

    async def research(self, query: str, ticker: str, on_event: Optional[Callable[[Dict[str, Any]], None]] = None) -> AgentOutput:
        """
        Override to merge reflection docs into evidence for Self-RAG.
        Uses SearchConvergence for info gain scoring and stop conditions.
        """
        trace: List[Dict[str, Any]] = []
        queries = self._build_queries(query, ticker)
        logger.info(f"[DeepSearch] queries: {queries}")

        def _log_event(event_type: str, details: Dict[str, Any]):
            event = self._trace_step(event_type, details)
            trace.append(event)
            if on_event:
                try:
                    on_event({
                        "event": "agent_execution",
                        "agent": self.AGENT_NAME,
                        "details": {"type": event_type, **details},
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception:
                    pass

        def _notify(msg: str):
            if on_event:
                try:
                    on_event({
                        "event": "agent_action",
                        "agent": self.AGENT_NAME,
                        "details": {"message": msg},
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception:
                    pass

        # Initialize convergence controller
        convergence = SearchConvergence()

        _notify(f"开始初始搜索 (Queries: {len(queries)})...")
        results = await self._initial_search(query, ticker, queries=queries)
        
        _notify(f"正在生成初步摘要...")
        summary = await self._first_summary(results)

        # Process initial results through convergence
        unique_results, init_metrics = convergence.process_round(results, "")
        _log_event("initial_search", {
                **self._build_trace_payload(queries, results),
                "convergence": {
                    "round": init_metrics.round_num,
                    "info_gain": init_metrics.info_gain,
                    "unique_docs": init_metrics.unique_docs_count
                }
            })
        self._log_documents(results, "initial")
        _log_event("summary", {"summary_preview": self._trim_text(summary, 400)})

        all_docs: List[Dict[str, Any]] = list(unique_results) if isinstance(unique_results, list) else []

        for i in range(self.MAX_REFLECTIONS):
            _notify(f"正在分析信息缺口 (Round {i+1})...")
            gaps = await self._identify_gaps(summary)
            _log_event("self_rag_gap_detection", {"needs_more": bool(gaps), "queries": gaps})
            if not gaps:
                break
            
            _notify(f"执行针对性搜索 (Gaps: {len(gaps)})...")
            new_data = await self._targeted_search(gaps, ticker)
            if isinstance(new_data, list) and new_data:
                # Process through convergence for dedup and gain scoring
                unique_new, metrics = convergence.process_round(new_data, summary)
                _log_event("targeted_search", {
                        **self._build_trace_payload(gaps, new_data),
                        "convergence": {
                            "round": metrics.round_num,
                            "info_gain": metrics.info_gain,
                            "unique_docs": metrics.unique_docs_count,
                            "should_stop": metrics.should_stop,
                            "reason": metrics.reason
                        }
                    })
                self._log_documents(unique_new, "targeted")
                all_docs.extend(unique_new)

                # Check convergence stop condition
                if metrics.should_stop:
                    logger.info(f"[DeepSearch] Convergence stop: {metrics.reason}")
                    break
            
            _notify(f"更新摘要整合新信息...")
            summary = await self._update_summary(summary, new_data)
            _log_event("summary_update", {"summary_preview": self._trim_text(summary, 400)})

        # Add final convergence stats to trace
        _log_event("convergence_final", convergence.get_stats())

        evidence_quality = self._compute_evidence_quality(all_docs or results)
        _log_event("evidence_quality", evidence_quality)

        output = self._format_output(
            summary,
            all_docs or results,
            trace=trace,
            evidence_quality=evidence_quality,
        )
        return output

    async def _initial_search(
        self,
        query: str,
        ticker: str,
        queries: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        cache_key = f"{ticker}:deep_search:{hash(query)}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, list) and cached:
            return cached

        queries = queries or self._build_queries(query, ticker)
        results: List[Dict[str, Any]] = []
        for q in queries:
            logger.info(f"[DeepSearch] search: {q}")
            results.extend(self._search_web(q))

        results = self._dedupe_results(results)
        results = self._filter_results(results, query=query, ticker=ticker)[:self.MAX_RESULTS]
        docs = await asyncio.to_thread(self._fetch_documents, results)
        if docs:
            sources = sorted({doc.get("source", "web") for doc in docs if isinstance(doc, dict)})
            pdf_count = sum(1 for doc in docs if doc.get("is_pdf"))
            logger.info(f"[DeepSearch] fetched docs={len(docs)} pdfs={pdf_count} sources={sources}")

        # 降级策略：如果文档抓取全部失败但搜索有结果，用搜索 snippet 构建降级文档
        if not docs and results:
            logger.warning(
                f"[DeepSearch] All {len(results)} document fetches failed, "
                "falling back to search snippets"
            )
            docs = self._build_snippet_docs(results)

        if docs:
            self.cache.set(cache_key, docs, ttl=self.CACHE_TTL)
        return docs

    async def _first_summary(self, data: List[Dict[str, Any]]) -> str:
        return await self._summarize_docs(data)

    async def _identify_gaps(self, summary: str) -> List[str]:
        if not self.llm:
            return []

        prompt = f"""<role>金融深度研究 Self-RAG 控制器</role>

<task>评估当前研究摘要的信息完整性，决定是否需要补充检索轮次。</task>

<current_summary>
{summary}
</current_summary>

<evaluation_criteria>
需要补充检索 (needs_more=true) 的情况：
- 关键财务指标缺失（营收增长率、利润率、估值 PE/PB/PS）
- 风险因素分析不完整（仅提到 1 类风险或无具体数据支撑）
- 竞争格局描述模糊（缺乏市场份额或对手对比）
- 缺乏时效性信息（无最近 1 个月的财报/公告/事件）
- 核心投资论点缺乏 2 个以上独立数据源支撑

信息充足 (needs_more=false) 的情况：
- 核心投资逻辑清晰，有数据支撑
- 至少覆盖 3 个分析维度（估值/基本面/技术面/宏观/情绪）
- 风险与机会均有实质性覆盖
- 关键数据点有来源引用
</evaluation_criteria>

<output_format>
仅返回 JSON，禁止任何解释、前言或 markdown：
{{"needs_more": true/false, "queries": ["具体检索词1", "具体检索词2"]}}

queries 要求：
- 最多 3 个，每个需具体明确
- 中英文混合以提高召回率（如"AAPL 2024年Q4财报 revenue growth"）
- 聚焦摘要中已识别的具体信息缺口
- 禁止宽泛查询（如"公司近况"），必须针对性
</output_format>"""
        raw = await self._call_llm(prompt)
        payload = self._extract_json(raw)
        if not payload or not isinstance(payload, dict):
            return []
        needs_more = payload.get("needs_more", False)
        if isinstance(needs_more, str):
            needs_more = needs_more.strip().lower() in ("true", "yes", "1")
        if not needs_more:
            return []
        queries = payload.get("queries", [])
        if not isinstance(queries, list):
            return []
        cleaned = [str(q).strip() for q in queries if str(q).strip()]
        return cleaned[:3]

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Any:
        if not gaps:
            return []
        results: List[Dict[str, Any]] = []
        for gap in gaps:
            query = f"{ticker} {gap}".strip()
            results.extend(self._search_web(query))
        results = self._dedupe_results(results)
        synthesized_query = f"{ticker} {' '.join([str(g).strip() for g in gaps if str(g).strip()])}".strip()
        results = self._filter_results(
            results,
            query=synthesized_query or ticker,
            ticker=ticker,
        )[:self.MAX_RESULTS]
        return await asyncio.to_thread(self._fetch_documents, results)

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        if not new_data:
            return summary
        return await self._summarize_docs(new_data, previous_summary=summary)

    def _format_output(
        self,
        summary: str,
        raw_data: Any,
        trace: Optional[List[Dict[str, Any]]] = None,
        evidence_quality: Optional[Dict[str, Any]] = None,
    ) -> AgentOutput:
        evidence: List[EvidenceItem] = []
        data_sources: List[str] = []
        fallback_used = False
        evidence_quality = evidence_quality or {}
        has_conflicts = bool(evidence_quality.get("has_conflicts"))
        all_degraded = True

        if isinstance(raw_data, list):
            for item in raw_data:
                source = item.get("source", "web")
                data_sources.append(source)
                title = item.get("title") or ""
                snippet = item.get("snippet") or item.get("content", "")[:240]
                degraded = bool(item.get("degraded"))
                if not degraded:
                    all_degraded = False
                doc_quality = self._doc_quality_score(item)
                evidence.append(EvidenceItem(
                    text=snippet,
                    source=source,
                    url=item.get("url"),
                    timestamp=item.get("published_date"),
                    confidence=item.get("confidence", 0.7),
                    title=title,
                    meta={
                        "is_pdf": item.get("is_pdf", False),
                        "degraded": degraded,
                        "degrade_reason": item.get("degrade_reason"),
                        "doc_quality": doc_quality,
                        "evidence_quality": {
                            "overall_score": float(evidence_quality.get("overall_score", 0.0)),
                            "source_diversity": int(evidence_quality.get("source_diversity", 0)),
                            "has_conflicts": has_conflicts,
                        },
                        "conflict_flag": has_conflicts,
                    },
                ))
        else:
            all_degraded = False

        data_sources = sorted(set(data_sources)) if data_sources else ["web"]
        if not raw_data or (isinstance(raw_data, list) and raw_data and all_degraded):
            fallback_used = True
        confidence = self._estimate_confidence(raw_data)
        risks = ["研究来源可能包含主观分析，请结合多方信息判断。"]
        if fallback_used:
            risks.append("深度研究数据源有限，结果可能不完整。")
        if has_conflicts:
            risks.append("多源证据信号存在冲突，建议核实原始财报或电话会议。")

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=data_sources,
            as_of=datetime.now().isoformat(),
            evidence_quality=evidence_quality,
            fallback_used=fallback_used,
            risks=risks,
            trace=trace or [],
        )

    def _compute_evidence_quality(self, docs: Any) -> Dict[str, Any]:
        if not isinstance(docs, list) or not docs:
            return {
                "doc_count": 0,
                "source_diversity": 0,
                "avg_doc_quality": 0.0,
                "freshness_score": 0.0,
                "has_conflicts": False,
                "overall_score": 0.0,
            }

        valid_docs = [doc for doc in docs if isinstance(doc, dict)]
        if not valid_docs:
            return {
                "doc_count": 0,
                "source_diversity": 0,
                "avg_doc_quality": 0.0,
                "freshness_score": 0.0,
                "has_conflicts": False,
                "overall_score": 0.0,
            }

        source_keys = set()
        freshness_scores: List[float] = []
        doc_scores: List[float] = []
        for doc in valid_docs:
            source_key = (doc.get("source") or self._infer_source(doc.get("url", "")) or "web").strip().lower()
            if source_key:
                source_keys.add(source_key)
            freshness_scores.append(self._freshness_score(doc.get("published_date")))
            doc_scores.append(self._doc_quality_score(doc))

        source_diversity = len(source_keys)
        diversity_score = min(1.0, source_diversity / 4.0)
        avg_doc_quality = sum(doc_scores) / max(1, len(doc_scores))
        freshness_score = sum(freshness_scores) / max(1, len(freshness_scores))
        has_conflicts = self._detect_conflicts(valid_docs)
        degraded_docs = sum(1 for doc in valid_docs if doc.get("degraded"))
        degraded_ratio = degraded_docs / max(1, len(valid_docs))

        overall = (
            avg_doc_quality * 0.45
            + freshness_score * 0.25
            + diversity_score * 0.20
            + (0.10 if not has_conflicts else 0.0)
        )
        overall -= min(0.35, degraded_ratio * 0.35)
        overall = max(0.0, min(1.0, overall))

        return {
            "doc_count": len(valid_docs),
            "source_diversity": source_diversity,
            "avg_doc_quality": round(avg_doc_quality, 4),
            "freshness_score": round(freshness_score, 4),
            "degraded_docs": degraded_docs,
            "degraded_ratio": round(degraded_ratio, 4),
            "has_conflicts": bool(has_conflicts),
            "overall_score": round(overall, 4),
        }

    def _doc_quality_score(self, doc: Dict[str, Any]) -> float:
        source_score = self._source_reliability_score(doc)
        freshness = self._freshness_score(doc.get("published_date"))
        content = str(doc.get("content") or doc.get("snippet") or "")
        depth = min(1.0, len(content) / 1200.0)
        quality = source_score * 0.5 + freshness * 0.25 + depth * 0.25
        return round(max(0.0, min(1.0, quality)), 4)

    def _source_reliability_score(self, doc: Dict[str, Any]) -> float:
        source = str(doc.get("source") or "").strip().lower()
        url = str(doc.get("url") or "").strip().lower()
        content = str(doc.get("content") or doc.get("snippet") or "")
        degraded = bool(doc.get("degraded"))
        if doc.get("is_pdf"):
            if degraded or len(content) < self.MIN_TEXT_CHARS:
                return 0.55
            return 0.9
        for hint in self._HIGH_RELIABILITY_SOURCE_HINTS:
            if hint in source or hint in url:
                return 0.9
        if source in ("tavily", "exa"):
            return 0.75
        if source in ("search", "web"):
            return 0.6
        return 0.65

    def _freshness_score(self, published_date: Any) -> float:
        text = str(published_date or "").strip()
        if not text:
            return 0.5
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hours = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0)
            if hours <= 24:
                return 1.0
            if hours <= 24 * 7:
                return 0.85
            if hours <= 24 * 30:
                return 0.7
            if hours <= 24 * 90:
                return 0.55
            return 0.4
        except Exception:
            return 0.5

    def _detect_conflicts(self, docs: List[Dict[str, Any]]) -> bool:
        positive_hits = 0
        negative_hits = 0
        for doc in docs:
            text = " ".join(
                [
                    str(doc.get("title") or ""),
                    str(doc.get("snippet") or ""),
                    str(doc.get("content") or "")[:1200],
                ]
            ).lower()
            pos = sum(1 for t in self._POSITIVE_SIGNAL_TERMS if t in text)
            neg = sum(1 for t in self._NEGATIVE_SIGNAL_TERMS if t in text)
            if pos > neg:
                positive_hits += 1
            elif neg > pos:
                negative_hits += 1
        return positive_hits > 0 and negative_hits > 0

    def _trace_step(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return create_trace_event(stage, agent=self.AGENT_NAME, **payload)

    def _build_trace_payload(self, queries: List[str], docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        items = []
        sources = set()
        pdf_count = 0
        for doc in docs:
            source = doc.get("source", "web")
            sources.add(source)
            is_pdf = bool(doc.get("is_pdf"))
            if is_pdf:
                pdf_count += 1
            items.append({
                "title": doc.get("title"),
                "url": doc.get("url"),
                "source": source,
                "published_date": doc.get("published_date"),
                "is_pdf": is_pdf,
                "content_chars": len(doc.get("content", "")),
            })
        return {
            "queries": queries,
            "documents_count": len(docs),
            "pdf_count": pdf_count,
            "sources": sorted(sources),
            "documents": items,
        }

    def _log_documents(self, docs: List[Dict[str, Any]], label: str) -> None:
        for idx, doc in enumerate(docs, 1):
            title = doc.get("title") or "Untitled"
            url = doc.get("url") or ""
            is_pdf = doc.get("is_pdf", False)
            logger.info(f"[DeepSearch] {label} doc {idx}: {title} | {url} | pdf={is_pdf}")

    def _build_queries(self, query: str, ticker: str) -> List[str]:
        base = query.strip()
        if ticker and ticker not in base:
            base = f"{ticker} {base}".strip()

        query_lower = query.lower()
        if self._is_finance_research_intent(query):
            filing_queries = [
                f"site:sec.gov {ticker} 10-K annual report",
                f"site:sec.gov {ticker} 10-Q quarterly report",
                f"{ticker} earnings call transcript Reuters Bloomberg",
            ]
            return [q.strip() for q in filing_queries if q.strip()][:3]

        enable_pdf_bias = os.getenv("DEEPSEARCH_ENABLE_PDF_QUERY_BIAS", "0").strip().lower() in (
            "1", "true", "yes", "on"
        )
        topics: List[str] = []
        if any(k in query_lower for k in ["risk", "downside", "bear", "风险", "利空"]):
            topics.append("risk factors")
        if any(k in query_lower for k in ["valuation", "估值", "multiple", "dcf", "pe"]):
            topics.append("valuation model")
        if any(k in query_lower for k in ["competition", "competitor", "竞争", "对手"]):
            topics.append("competitive landscape")
        if any(k in query_lower for k in ["earnings", "财报", "业绩", "guidance", "指引"]):
            topics.append("earnings transcript")
        if any(k in query_lower for k in ["industry", "sector", "产业", "行业"]):
            topics.append("industry report")

        if not topics:
            # 混合策略：1 条 HTML 倾向 + 1 条中性 + 1 条 PDF 倾向（如果 pypdf 可用）
            topics = [
                "latest analysis report",
                "earnings analysis outlook",
            ]
            if PdfReader is not None and enable_pdf_bias:
                topics.append("investment thesis filetype:pdf")
            else:
                topics.append("investment thesis")
        else:
            if "latest analysis report" not in topics:
                topics.append("latest analysis report")

        seen: set[str] = set()
        queries: List[str] = []
        for topic in topics:
            if topic in seen:
                continue
            seen.add(topic)
            queries.append(f"{base} {topic}".strip())
        return queries[:3]

    def _search_web(self, query: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        tavily_key = getattr(self.tools, "TAVILY_API_KEY", "") if self.tools else ""
        tavily_available = bool(getattr(self.tools, "TAVILY_AVAILABLE", False))
        exa_key = getattr(self.tools, "EXA_API_KEY", "") if self.tools else ""
        exa_available = bool(getattr(self.tools, "EXA_AVAILABLE", False))

        if tavily_key and tavily_available:
            try:
                from tavily import TavilyClient

                client = TavilyClient(api_key=tavily_key)
                response = client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=8,
                    include_answer=False,
                    include_raw_content=False,
                )
                for item in response.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                        "source": "tavily",
                        "published_date": item.get("published_date") or item.get("published_at"),
                        "score": item.get("score"),
                    })
            except Exception as exc:
                logger.info(f"[DeepSearch] Tavily search failed: {exc}")

        if not results and exa_key and exa_available:
            try:
                from exa_py import Exa

                exa = Exa(api_key=exa_key)
                response = exa.search_and_contents(
                    query=query,
                    type="neural",
                    num_results=8,
                    text=True,
                    highlights=True,
                )
                for item in response.results or []:
                    content = ""
                    if getattr(item, "highlights", None):
                        content = " ".join(item.highlights[:2])
                    elif getattr(item, "text", None):
                        content = item.text[:300]
                    results.append({
                        "title": item.title or "",
                        "url": item.url or "",
                        "snippet": content,
                        "source": "exa",
                        "published_date": getattr(item, "published_date", None),
                    })
            except Exception as exc:
                logger.info(f"[DeepSearch] Exa search failed: {exc}")

        if not results and self.tools and hasattr(self.tools, "search"):
            try:
                raw = self.tools.search(query)
                results = self._parse_search_text(raw)
            except Exception as exc:
                logger.info(f"[DeepSearch] Search fallback failed: {exc}")

        trusted_count = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            domain = self._normalized_domain_from_url(item.get("url") or "")
            if self._is_trusted_finance_domain(domain):
                trusted_count += 1

        if trusted_count < 2:
            try:
                from backend.tools.authoritative_feeds import search_authoritative_feeds

                feed_items = search_authoritative_feeds(query, max_results=5, authoritative_only=True)
                existing_urls = {
                    str(item.get("url") or "").strip()
                    for item in results
                    if isinstance(item, dict) and str(item.get("url") or "").strip()
                }
                for item in feed_items:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url or url in existing_urls:
                        continue
                    existing_urls.add(url)
                    results.append(
                        {
                            "title": item.get("title", ""),
                            "url": url,
                            "snippet": item.get("snippet") or item.get("title") or "",
                            "source": "authoritative_feed",
                            "published_date": item.get("published_date"),
                        }
                    )
            except Exception as exc:
                logger.info(f"[DeepSearch] Authoritative feed supplement failed: {exc}")

        return results

    def _is_finance_research_intent(self, query: str) -> bool:
        q = str(query or "").lower()
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
        return any(token in q for token in signals)

    def _normalized_domain_from_url(self, url: str) -> str:
        try:
            host = urlparse(str(url or "").strip().lower()).netloc
        except Exception:
            host = ""
        return host.lstrip("www.")

    def _is_trusted_finance_domain(self, domain: str) -> bool:
        host = str(domain or "").strip().lower().lstrip("www.")
        if not host:
            return False
        trusted_exact = {d.lower().lstrip("www.") for d in self._TRUSTED_FINANCE_DOMAINS}
        if host in trusted_exact:
            return True
        if any(hint in host for hint in self._TRUSTED_FINANCE_DOMAIN_HINTS):
            return True
        return False

    def _is_blocked_result(self, item: Dict[str, Any]) -> bool:
        url = str(item.get("url") or "").strip().lower()
        title = str(item.get("title") or "").strip().lower()
        snippet = str(item.get("snippet") or "").strip().lower()
        domain = self._normalized_domain_from_url(url)
        parsed = urlparse(url) if url else None
        path = parsed.path.lower() if parsed else ""
        if not url.startswith(("http://", "https://")):
            return True
        if domain == "finnhub.io" and path.startswith("/api/news"):
            return True
        if domain and any(domain.endswith(suffix) for suffix in self._BLOCKED_TLDS):
            if not self._is_trusted_finance_domain(domain):
                return True
        if any(hint in url for hint in self._BLOCKED_DOMAIN_HINTS):
            return True
        text = " ".join((url, title, snippet))
        return any(token in text for token in self._BLOCKED_CONTENT_HINTS)

    def _result_relevance_score(self, item: Dict[str, Any], *, query: str, ticker: str) -> float:
        url = str(item.get("url") or "").strip().lower()
        title = str(item.get("title") or "").strip().lower()
        snippet = str(item.get("snippet") or "").strip().lower()
        domain = self._normalized_domain_from_url(url)
        text = f"{title} {snippet} {url}"
        score = 0.0

        if self._is_trusted_finance_domain(domain):
            score += 4.0
        if "sec.gov" in url:
            score += 2.0
        if ".pdf" in url:
            score += 0.8

        ticker_lower = str(ticker or "").strip().lower()
        if ticker_lower and ticker_lower in text:
            score += 1.5

        query_tokens = [
            token.strip().lower()
            for token in re.findall(r"[A-Za-z0-9\-\._]{3,}", str(query or ""))
            if token.strip()
        ]
        for token in query_tokens[:8]:
            if token in text:
                score += 0.4

        return score

    def _filter_results(self, results: List[Dict[str, Any]], *, query: str, ticker: str) -> List[Dict[str, Any]]:
        if not isinstance(results, list) or not results:
            return []

        finance_intent = self._is_finance_research_intent(query)
        strict_finance_sources = str(
            os.getenv("DEEPSEARCH_STRICT_FINANCE_SOURCES", "true")
        ).strip().lower() in {"1", "true", "yes", "on"}
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            if self._is_blocked_result(item):
                continue
            domain = self._normalized_domain_from_url(item.get("url") or "")
            if finance_intent and strict_finance_sources and not self._is_trusted_finance_domain(domain):
                continue
            score = self._result_relevance_score(item, query=query, ticker=ticker)
            if finance_intent and score < 2.4:
                continue
            scored.append((score, item))

        if not scored:
            return []

        scored.sort(key=lambda pair: pair[0], reverse=True)
        output: List[Dict[str, Any]] = []
        for _, item in scored:
            output.append(item)
        return output

    def _parse_search_text(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return []
        url_pattern = re.compile(r"https?://[^\s)]+")
        results: List[Dict[str, Any]] = []
        for line in text.splitlines():
            urls = url_pattern.findall(line)
            if not urls:
                continue
            title = line.strip()[:160]
            for url in urls:
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": line.strip(),
                    "source": "search",
                })
        return results

    def _dedupe_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        deduped = []
        for item in results:
            url = item.get("url", "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(item)
        return deduped

    def _build_snippet_docs(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """当文档抓取全部失败时，从搜索 snippet 构建降级文档。"""
        docs: List[Dict[str, Any]] = []
        for item in results[: self.MAX_DOCS]:
            snippet = str(item.get("snippet") or "").strip()
            title = str(item.get("title") or "").strip()
            if not snippet and not title:
                continue
            content = f"{title}\n{snippet}" if title else snippet
            docs.append({
                "title": title,
                "url": item.get("url", ""),
                "snippet": snippet,
                "content": content,
                "source": item.get("source", "web"),
                "published_date": item.get("published_date"),
                "is_pdf": False,
                "confidence": 0.5,  # 降级文档置信度较低
                "degraded": True,
                "degrade_reason": "snippet_only",
            })
        return docs

    def _fetch_documents(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        degraded_docs: List[Dict[str, Any]] = []
        for item in results[: self.MAX_DOCS]:
            doc = self._fetch_document(item)
            if not doc:
                continue

            content = str(doc.get("content") or "").strip()
            if len(content) < self.MIN_TEXT_CHARS:
                snippet = str(doc.get("snippet") or item.get("snippet") or "").strip()
                title = str(doc.get("title") or item.get("title") or "").strip()

                if doc.get("is_pdf") and (snippet or title):
                    fallback_text = f"{title}\n{snippet}".strip() if title else snippet
                    if fallback_text:
                        degraded_doc = dict(doc)
                        degraded_doc["content"] = fallback_text
                        degraded_doc["snippet"] = snippet or fallback_text[:240]
                        degraded_doc["confidence"] = min(float(doc.get("confidence", 0.7)), 0.45)
                        degraded_doc["degraded"] = True
                        degraded_doc["degrade_reason"] = "pdf_parse_or_short_content"
                        degraded_docs.append(degraded_doc)
                continue

            docs.append(doc)

        if docs:
            return docs

        if degraded_docs:
            return degraded_docs

        if results:
            return self._build_snippet_docs(results)

        return docs

    def _fetch_document(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = item.get("url", "")
        if not url:
            return None
        if not is_safe_url(url):
            logger.info(f"[DeepSearch] Blocked unsafe url: {url}")
            return None
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; FinSightBot/0.1)",
        }
        try:
            session = self._get_session()
            response = session.get(url, headers=headers, timeout=30, allow_redirects=True)
            if response.url and not is_safe_url(response.url):
                logger.info(f"[DeepSearch] Blocked unsafe redirect: {response.url}")
                return None
            response.raise_for_status()
        except Exception as exc:
            logger.info(f"[DeepSearch] Fetch failed: {exc}")
            return None

        content_type = response.headers.get("Content-Type", "").lower()
        is_pdf = url.lower().endswith(".pdf") or "application/pdf" in content_type
        text = ""
        used_snippet_fallback = False
        if is_pdf:
            text = self._extract_pdf_text(response.content)
        else:
            text = self._extract_html_text(response.text)

        text = self._trim_text(text)
        domain = self._normalized_domain_from_url(url)

        enable_jina_fallback = str(os.getenv("DEEPSEARCH_ENABLE_JINA_FALLBACK", "true")).strip().lower() in {"1", "true", "yes", "on"}
        if (
            enable_jina_fallback
            and not is_pdf
            and len(text) < self.MIN_TEXT_CHARS
            and domain != "news.google.com"
            and self._is_trusted_finance_domain(domain)
        ):
            try:
                from backend.tools.jina_reader import fetch_via_jina

                jina_text = fetch_via_jina(url)
                if jina_text and len(jina_text) > len(text):
                    text = self._trim_text(jina_text)
                    logger.info("[DeepSearch] Jina fallback: %s (%d chars)", url, len(text))
            except Exception:
                pass

        enable_wayback_fallback = str(os.getenv("DEEPSEARCH_ENABLE_WAYBACK_FALLBACK", "true")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if (
            enable_wayback_fallback
            and not is_pdf
            and len(text) < self.MIN_TEXT_CHARS
            and domain != "news.google.com"
            and self._is_trusted_finance_domain(domain)
        ):
            try:
                from backend.tools.wayback import fetch_via_wayback

                wayback_text = fetch_via_wayback(url)
                if wayback_text and len(wayback_text) > len(text):
                    text = self._trim_text(wayback_text)
                    logger.info("[DeepSearch] Wayback fallback: %s (%d chars)", url, len(text))
            except Exception:
                pass

        title = item.get("title") or self._infer_title(url)
        snippet = str(item.get("snippet") or "").strip()

        if not text and snippet:
            text = f"{title}\n{snippet}".strip()
            used_snippet_fallback = True

        if not snippet:
            snippet = text[:240]

        confidence = 0.85 if is_pdf else 0.7
        if used_snippet_fallback:
            confidence = min(confidence, 0.45)

        return {
            "title": title,
            "url": url,
            "snippet": snippet,
            "content": text,
            "source": item.get("source", self._infer_source(url)),
            "published_date": item.get("published_date"),
            "is_pdf": is_pdf,
            "confidence": confidence,
            "degraded": used_snippet_fallback,
            "degrade_reason": "empty_content_use_snippet" if used_snippet_fallback else None,
        }

    def _extract_pdf_text(self, data: bytes) -> str:
        if not PdfReader:
            return ""
        try:
            from io import BytesIO

            reader = PdfReader(BytesIO(data))
            pages = []
            for page in reader.pages[:8]:
                pages.append(page.extract_text() or "")
            return "\n".join(pages)
        except Exception as exc:
            logger.info(f"[DeepSearch] PDF parse failed: {exc}")
            return ""

    def _extract_html_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        return re.sub(r"\s+", " ", text).strip()

    def _trim_text(self, text: str, max_len: int = None) -> str:
        if not text:
            return ""
        limit = max_len if max_len else self.MAX_TEXT_CHARS
        if len(text) > limit:
            return text[:limit]
        return text

    def _infer_title(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or "web"

    def _infer_source(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or "web"

    async def _summarize_docs(self, docs: List[Dict[str, Any]], previous_summary: Optional[str] = None) -> str:
        if not docs:
            return "未找到深度研究数据源。"

        chunks = []
        for idx, doc in enumerate(docs, 1):
            content = doc.get("content", "")
            snippet = content[:800] if content else doc.get("snippet", "")
            chunks.append(
                f"[{idx}] {doc.get('title', '')}\nURL: {doc.get('url', '')}\n{snippet}"
            )
        bundle = "\n\n".join(chunks)

        if not self.llm:
            titles = ", ".join([doc.get("title", "") for doc in docs[:3]])
            return f"已检索到深度研究来源: {titles}。"

        prev_section = f"\n<previous_summary>\n{previous_summary}\n</previous_summary>" if previous_summary else ""
        prompt = f"""<role>资深金融研究分析师 — 深度研究备忘录撰写</role>

<task>基于多源检索结果撰写结构化深度研究备忘录，提供可操作的投资洞察。</task>
{prev_section}
<sources>
{bundle}
</sources>

<requirements>
- 语言：简体中文
- 输出 4-6 条核心洞察，每条包含：
  · 事实发现（含具体数据点）
  · 影响判断（对标的/行业的潜在影响）
  · 来源引用 [1]、[2]（对应源编号）
- 标注 1-2 条不确定性或风险点，附置信度评估
- 明确标注信息缺口（如有），指明还需要什么数据
- 若有前次摘要，需与新信息交叉验证，标注一致/冲突
</requirements>

<output_format>
## 核心发现
1. [发现] — [影响判断] [1]
2. ...

## 影响与解读
[2-3 句综合解读，强调跨源信息的交叉印证，以及对投资决策的具体含义]

## 风险提示
- [风险描述] [置信度: High/Medium/Low]

## 信息缺口
[尚需补充的具体信息，无则写"暂无明显缺口"]
</output_format>

<constraints>
- 禁止开场白、寒暄、总结性陈述
- 直接输出结构化内容
- 专业商务语气，避免口语化表达
- 数据冲突时必须标注并说明哪个更可信
</constraints>"""

        result = await self._call_llm(prompt)
        if result and result.strip():
            return result.strip()
        # Degraded fallback: build summary from doc titles and snippets
        return self._build_degraded_summary(docs)

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM with outer retry layer for DeepSearch resilience.

        DeepSearch runs after other agents in the concurrent pipeline, so
        external rate-limit windows may already be hot.  The outer retry
        gives endpoints extra time to recover.
        """
        max_outer_retries = 3
        for outer in range(max_outer_retries):
            try:
                from backend.services.rate_limiter import acquire_llm_token
                token_timeout = max(1.0, float(self.LLM_TOKEN_TIMEOUT_SECONDS))
                if not await acquire_llm_token(timeout=token_timeout, agent_name=self.AGENT_NAME):
                    logger.warning(
                        "[DeepSearch] Rate limit timeout after %.1fs, skipping LLM call",
                        token_timeout,
                    )
                    return ""

                message = HumanMessage(content=prompt)
                if hasattr(self.llm, "ainvoke"):
                    from backend.services.llm_retry import ainvoke_with_rate_limit_retry
                    from backend.llm_config import create_llm

                    _temp = getattr(self.llm, "temperature", 0.3)
                    llm_factory = lambda: create_llm(temperature=_temp)

                    response = await ainvoke_with_rate_limit_retry(
                        self.llm,
                        [message],
                        acquire_token=False,
                        llm_factory=llm_factory,
                    )
                else:
                    response = await asyncio.to_thread(self.llm.invoke, [message])
                return getattr(response, "content", "") if response is not None else ""
            except Exception as exc:
                logger.warning(
                    "[DeepSearch] LLM call attempt %d/%d failed (%s): %s",
                    outer + 1, max_outer_retries, type(exc).__name__, exc,
                )
                if outer < max_outer_retries - 1:
                    backoff = 5.0 * (outer + 1)
                    logger.info("[DeepSearch] Waiting %.1fs before outer retry...", backoff)
                    await asyncio.sleep(backoff)
                else:
                    logger.error("[DeepSearch] All %d outer retries exhausted", max_outer_retries)
        return ""

    def _extract_json(self, text: str) -> Dict[str, Any]:
        if not text:
            return {}
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    def _clean_degraded_text(self, text: str) -> str:
        cleaned = str(text or "")
        cleaned = re.sub(r"https?://\S+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        noise_tokens = (
            "SummaryRatingsFinancialsTechnicals",
            "MarketWatch",
            "Privacy Policy",
            "Terms of Use",
            "Cookie",
            "Subscribe",
            "Sign in",
            "Login",
            "注册",
            "登录",
            "免责声明",
        )
        for token in noise_tokens:
            cleaned = cleaned.replace(token, " ")
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

    def _low_signal_text(self, text: str) -> bool:
        if not text:
            return True
        stripped = text.strip()
        if len(stripped) < 20:
            return True
        alpha_num = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", stripped))
        if alpha_num < 15:
            return True
        if re.search(r"[A-Za-z]{25,}", stripped):
            return True
        return False

    def _degraded_fact_from_doc(self, doc: Dict[str, Any]) -> str:
        title = self._clean_degraded_text(str(doc.get("title") or "")).strip()
        snippet = self._clean_degraded_text(str(doc.get("snippet") or doc.get("content") or "")).strip()
        if not snippet:
            snippet = self._clean_degraded_text(str(doc.get("content") or "")).strip()
        if self._low_signal_text(snippet):
            return ""

        if len(snippet) > 140:
            snippet = snippet[:140].rstrip(" ,.;，。；") + "…"

        idx_ref = doc.get("_idx_ref")
        ref = f"[{idx_ref}]" if idx_ref else ""
        if title:
            return f"- {title}：{snippet} {ref}".strip()
        return f"- {snippet} {ref}".strip()

    def _build_degraded_summary(self, docs: List[Dict[str, Any]]) -> str:
        """Build a degraded summary from doc titles/snippets when LLM is unavailable."""
        if not docs:
            return "未找到深度研究数据源。"
        lines: List[str] = ["## 核心发现"]

        facts: List[str] = []
        for idx, raw_doc in enumerate(docs[:8], 1):
            doc = dict(raw_doc)
            doc["_idx_ref"] = idx
            fact = self._degraded_fact_from_doc(doc)
            if fact:
                facts.append(fact)
            if len(facts) >= 4:
                break

        if not facts:
            titles = [self._clean_degraded_text(str(doc.get("title") or "")) for doc in docs[:4]]
            titles = [title for title in titles if title]
            if titles:
                facts = [f"- 来源覆盖：{'、'.join(titles[:3])}。"]
            else:
                facts = ["- 当前仅获得低质量检索片段，缺少可验证正文数据。"]

        lines.extend(facts)

        degraded_ratio = (
            sum(1 for d in docs if d.get("degraded")) / max(1, len(docs))
            if isinstance(docs, list) else 1.0
        )

        lines.append("")
        lines.append("## 风险提示")
        if degraded_ratio >= 0.8:
            lines.append("- 证据以降级片段为主，结论可靠性偏低，建议优先补充可解析原文/PDF。")
        else:
            lines.append("- 存在部分降级来源，建议结合财报、公告或权威媒体原文复核关键结论。")

        lines.append("")
        lines.append("## 信息缺口")
        lines.append("- 当前为降级摘要模式（LLM/正文抽取受限），缺少可核验的结构化财务明细与上下文。")
        lines.append("- 建议补充：最新财报原文、业绩会纪要、估值模型假设与可追溯数据表。")
        return "\n".join(lines)

    def _estimate_confidence(self, docs: Any) -> float:
        if not isinstance(docs, list) or not docs:
            return 0.2
        source_set = {
            str(doc.get("source") or self._infer_source(str(doc.get("url") or "")) or "web").strip().lower()
            for doc in docs if isinstance(doc, dict)
        }
        source_set.discard("")
        source_diversity = len(source_set)

        degraded_count = sum(1 for doc in docs if isinstance(doc, dict) and doc.get("degraded"))
        degraded_ratio = degraded_count / max(1, len(docs))

        base = 0.55
        doc_bonus = min(len(docs), 4) * 0.07
        diversity_bonus = min(0.18, source_diversity * 0.06)
        score = base + doc_bonus + diversity_bonus
        score -= min(0.45, degraded_ratio * 0.45)

        if degraded_ratio >= 0.99:
            score = min(score, 0.5)
        elif degraded_ratio >= 0.8:
            score = min(score, 0.58)

        return round(max(0.2, min(0.95, score)), 4)
