from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime, timezone
import asyncio
import hashlib
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

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.agents.chart_specs_extra import build_deepsearch_chart_specs
from backend.orchestration.trace_schema import create_trace_event
from backend.security.ssrf import is_safe_url
from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class DeepSearchAgent(BaseFinancialAgent):
    """单轮真实检索、文档解析和证据质量评估 collector。"""

    AGENT_NAME = "deep_search"
    CACHE_TTL = 3600  # 1 hour
    MAX_RESULTS = int(os.getenv("DEEPSEARCH_MAX_RESULTS", "8"))
    MAX_DOCS = int(os.getenv("DEEPSEARCH_MAX_DOCS", "4"))
    MIN_TEXT_CHARS = int(os.getenv("DEEPSEARCH_MIN_TEXT_CHARS", "400"))
    MAX_TEXT_CHARS = int(os.getenv("DEEPSEARCH_MAX_TEXT_CHARS", "12000"))
    HTTP_RETRIES = max(0, int(os.getenv("DEEPSEARCH_HTTP_RETRIES", "0")))
    FETCH_TIMEOUT_SECONDS = max(2.0, float(os.getenv("DEEPSEARCH_FETCH_TIMEOUT_SECONDS", "10")))
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
        super().__init__(llm, cache, tools_module, circuit_breaker)
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self._session:
            return self._session
        retry = Retry(
            total=self.HTTP_RETRIES,
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

    def _reject_unsafe_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        safe_results: List[Dict[str, Any]] = []
        for item in results:
            url = str((item or {}).get("url") or "").strip()
            if url and not is_safe_url(url):
                logger.info(f"[DeepSearch] Blocked unsafe search result before fetch: {url}")
                continue
            safe_results.append(item)
        return safe_results

    async def research(
        self,
        query: str,
        ticker: str,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        time_scope: dict | None = None,
        financial_metrics: list[str] | None = None,
        company_name: str = "",
        documents: list[dict] | None = None,
    ) -> AgentOutput:
        """执行一次安全检索和确定性证据整理。"""

        self._current_query = query
        self._current_ticker = ticker
        trace: List[Dict[str, Any]] = []

        def emit(event_type: str, details: Dict[str, Any]) -> None:
            trace.append(self._trace_step(event_type, details))
            if not on_event:
                return
            try:
                on_event(
                    {
                        "event": "agent_execution",
                        "agent": self.AGENT_NAME,
                        "details": {"type": event_type, **details},
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except Exception:
                logger.debug("[DeepSearch] on_event callback failed", exc_info=True)

        queries = self._build_queries(query, ticker)
        emit("search_start", {"queries": queries})
        remaining_extraction = sum("financial_extraction" in doc for doc in documents or []) < 2
        docs = await self._initial_search(query, ticker, queries=queries, time_scope=time_scope,
                                          full_document=bool(financial_metrics) and remaining_extraction, documents=documents)
        docs = self._mark_document_time(docs, time_scope)
        if financial_metrics:
            docs = await asyncio.to_thread(self._extract_document_facts, docs, ticker,
                                           financial_metrics, time_scope, company_name)
        self._log_documents(docs, "initial")
        emit("search_result", self._build_trace_payload(queries, docs))

        summary = await self._first_summary(docs)
        emit("summary", {"summary_preview": self._trim_text(summary, 400)})

        evidence_quality = self._compute_evidence_quality(docs)
        emit("evidence_quality", evidence_quality)

        rag_observability = await self._record_rag_observability(
            query=query,
            ticker=ticker,
            docs=docs,
        )
        if rag_observability:
            emit("rag_observability", rag_observability)

        output = self._format_output(
            summary,
            docs,
            trace=trace,
            evidence_quality=evidence_quality,
            query=query,
            ticker=ticker,
        )
        try:
            from backend.research.agent_quality_contract import apply_agent_quality_contract
            from backend.research.agent_research_loop import apply_agent_self_check

            output = apply_agent_quality_contract(output, query=query, ticker=ticker)
            output = apply_agent_self_check(output, query=query, ticker=ticker)
        except Exception as exc:
            logger.debug("[DeepSearch] agent quality contract failed: %s", exc)
        return output

    async def _initial_search(
        self,
        query: str,
        ticker: str,
        queries: Optional[List[str]] = None,
        time_scope: dict | None = None,
        full_document: bool = False,
        documents: list[dict] | None = None,
    ) -> List[Dict[str, Any]]:
        already_read = [{**doc, "url": doc.get("url") or doc.get("filing_url"),
                         "published_date": doc.get("published_date") or doc.get("filing_date"),
                         "degraded": False} for doc in documents or [] if doc.get("content_read") and doc.get("content")]
        read_urls = {doc["url"] for doc in already_read}
        cache_key = f"{ticker}:deep_search:{hash(query)}:{time_scope!r}:{full_document}:{sorted(read_urls)!r}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, list) and cached:
            return cached

        queries = queries or self._build_queries(query, ticker)
        results: List[Dict[str, Any]] = []
        for q in queries:
            logger.info(f"[DeepSearch] search: {q}")
            search_results = await asyncio.to_thread(self._search_web, q)
            for rank, item in enumerate(search_results, 1):
                enriched = dict(item or {})
                enriched["search_query"] = q
                enriched["search_rank"] = rank
                results.append(enriched)

        results = self._dedupe_results(results)
        results = [result for result in results if result.get("url") not in read_urls]
        results = self._reject_unsafe_results(results)
        results = self._filter_results(results, query=query, ticker=ticker, time_scope=time_scope)[:self.MAX_RESULTS]
        fetch_options = {"full_document": True} if full_document else {}
        docs = await asyncio.to_thread(self._fetch_documents, results, **fetch_options)
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
            docs = [*already_read, *docs]
            self.cache.set(cache_key, docs, ttl=self.CACHE_TTL)
        return docs or already_read

    @staticmethod
    def _publication_date(text: str) -> str | None:
        from backend.tools.local_disclosure import _extract_date
        from dateutil.parser import parse
        date_expression = r"(?:20\d{2}(?:[-/.]\d{1,2}[-/.]\d{1,2}|年\d{1,2}月\d{1,2}日)|\d{1,2}\s+[A-Za-z]+\s+20\d{2}|[A-Za-z]+\s+\d{1,2},?\s+20\d{2})"
        candidates, explicit = set(), set()
        for line in str(text or "")[:1500].splitlines():
            for match in re.finditer(date_expression, line):
                before, after = line[max(0, match.start() - 24):match.start()], line[match.end():match.end() + 12]
                if re.search(r"(?:截至|截止|期末|period\s+end(?:ed|ing)?|as\s+of)\s*$", before, re.IGNORECASE) or re.match(r"\s*期末", after):
                    continue
                value = match.group(0)
                numeric = _extract_date(value)
                if not numeric:
                    try:
                        numeric = parse(value, fuzzy=False).date().isoformat()
                    except ValueError:
                        continue
                candidates.add(numeric)
                if re.search(r"(?:发布日期|发布时间|出版日期|Published(?:\s+on)?|Issued(?:\s+on)?)\s*[:：]?\s*$", before, re.IGNORECASE):
                    explicit.add(numeric)
        dates = explicit or candidates
        return next(iter(dates)) if len(dates) == 1 else None

    @classmethod
    def _mark_document_time(cls, docs: list[dict], time_scope: dict | None) -> list[dict]:
        scope = time_scope or {}
        reference = str(scope.get("as_of") or datetime.now(timezone.utc).date().isoformat())[:10]
        output = []
        for original in docs:
            doc = dict(original)
            published = doc.get("published_date") or cls._publication_date(str(doc.get("content") or ""))
            doc["published_date"] = doc["published_at"] = published
            doc["source_time_status"] = "provided" if published else "unknown"
            if published and scope.get("selection") in {"latest", "latest_complete"}:
                try:
                    age = (datetime.fromisoformat(reference) - datetime.fromisoformat(str(published)[:10])).days
                    if age > 365:
                        doc["temporal_role"] = "historical"
                except ValueError:
                    pass
            output.append(doc)
        return output

    def _extract_document_facts(self, docs: list[dict], ticker: str, metrics: list[str],
                                time_scope: dict | None, company_name: str) -> list[dict]:
        from backend.tools.disclosure_financial_facts import _METRICS, extract_financial_facts
        from backend.tools.local_disclosure import _document_title, verified_disclosure_document

        documents = [dict(doc) for doc in docs]
        metrics = [metric for metric in metrics if metric in _METRICS]
        if not metrics:
            return documents
        attempts = sum("financial_extraction" in doc for doc in documents)
        obtained = {fact["metric"] for doc in documents for fact in doc.get("financial_facts") or []}
        for doc in documents:
            body, url = str(doc.get("content") or ""), str(doc.get("url") or "")
            identity = None if doc.get("degraded") else verified_disclosure_document(body, url, ticker, company_name)
            if not identity:
                continue
            doc.update(issuer_verified=True, issuer_ticker=ticker,
                       title=_document_title(body, str(doc.get("title") or url)))
            if attempts >= 2 or "financial_extraction" in doc or set(metrics).issubset(obtained):
                continue
            attempts += 1
            diagnostics: dict = {}
            facts = extract_financial_facts(body, ticker, url, metrics,
                time_scope=time_scope, diagnostics=diagnostics)
            for fact in facts:
                fact["published_at"] = doc.get("published_date")
                fact["filed"] = doc.get("published_date")
            doc["financial_facts"], doc["financial_extraction"] = facts, diagnostics
            obtained.update(fact["metric"] for fact in facts)
            if set(metrics).issubset(obtained):
                break
        return documents

    async def _first_summary(self, data: List[Dict[str, Any]]) -> str:
        return self._build_degraded_summary(data)

    def _format_output(
        self,
        summary: str,
        raw_data: Any,
        trace: Optional[List[Dict[str, Any]]] = None,
        evidence_quality: Optional[Dict[str, Any]] = None,
        query: str | None = None,
        ticker: str | None = None,
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
                        "shared_document": True,
                        "subject_binding": "body_verified" if item.get("issuer_verified") else "document_context",
                        "subject": item.get("issuer_ticker") if item.get("issuer_verified") else None,
                        "subject_refs": [item["issuer_ticker"]] if item.get("issuer_verified") else [],
                        "source_time_status": "provided" if item.get("published_date") else "unknown",
                        "published_at": item.get("published_at") or item.get("published_date"),
                        "temporal_role": item.get("temporal_role"),
                        "fetched_at": item.get("fetched_at"),
                        "financial_extraction": item.get("financial_extraction"),
                        "is_pdf": item.get("is_pdf", False),
                        "degraded": degraded,
                        "degrade_reason": item.get("degrade_reason"),
                        "usage": "raw" if degraded else "fact",
                        "content_read": not degraded and bool(item.get("content")),
                        "document_body": item.get("content", "") if not degraded else "",
                        "doc_quality": doc_quality,
                        "evidence_quality": {
                            "overall_score": float(evidence_quality.get("overall_score", 0.0)),
                            "source_diversity": int(evidence_quality.get("source_diversity", 0)),
                            "has_conflicts": has_conflicts,
                        },
                        "conflict_flag": has_conflicts,
                    },
                ))
                for fact in item.get("financial_facts") or []:
                    evidence.append(EvidenceItem(
                        text=str(fact.get("quote") or ""), source=source, url=fact.get("source_url"),
                        timestamp=item.get("published_date"), title=f"{fact['metric']} ({fact['period_end']})",
                        meta={**fact, "kind": "capital_allocation" if fact["metric"] in {
                            "operating_cash_flow", "capital_expenditure", "dividends_paid", "repurchases_paid"
                        } else "fundamental_snapshot", "issuer_verified": True,
                              "subject_binding": "body_verified", "usage": "fact",
                              "temporal_role": item.get("temporal_role"),
                              "source_time_status": "provided" if item.get("published_date") else "unknown"},
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

        # 深度搜索图表：时间分布(bar) + 来源分布(pie)，数据不足时为空列表
        chart_specs = build_deepsearch_chart_specs(
            raw_data if isinstance(raw_data, list) else None,
            query or "",
        )

        output = AgentOutput(
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
            chart_specs=chart_specs,
        )
        from backend.research.agent_quality_contract import assign_evidence_source_ids

        assign_evidence_source_ids(evidence, agent_name=self.AGENT_NAME)
        self._attach_evidence_ledger(output, query=query or summary, ticker=ticker)
        return output

    def _attach_evidence_ledger(self, output: AgentOutput, *, query: str, ticker: str | None = None) -> None:
        try:
            from backend.research.claim_extractor import extract_claims_from_agent_output
            from backend.research.evidence_ledger import from_agent_output
        except Exception as exc:
            logger.info("[DeepSearch] Evidence ledger unavailable: %s", exc)
            return

        subject = {"ticker": ticker} if str(ticker or "").strip() else {}
        payload = {
            "agent_name": output.agent_name,
            "summary": output.summary,
            "evidence": output.evidence,
            "confidence": output.confidence,
            "data_sources": output.data_sources,
            "as_of": output.as_of,
            "claims": output.claims,
            "evidence_quality": output.evidence_quality,
            "fallback_used": output.fallback_used,
            "risks": output.risks,
            "conflict_flags": output.conflict_flags,
            "conflicting_claims": output.conflicting_claims,
        }
        output.claims = extract_claims_from_agent_output(payload, query=query, ticker=ticker or "")
        ledger = from_agent_output(output, query=query, subject=subject, task_ids=[])
        output.claims = [claim.model_dump(mode="json") for claim in ledger.claims]
        output.ledger = ledger.model_dump(mode="json")

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
        if ticker and ticker.upper() not in {"N/A", "UNKNOWN"} and ticker.casefold() not in base.casefold():
            base = f"{ticker} {base}".strip()
        # 开放检索保留已绑定主体与原始范围；市场专用取数由执行合同安排。
        return [base] if base else []

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
            "competitive landscape",
            "analyst rating",
            "price target",
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
            score += 2.0
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

    def _filter_results(self, results: List[Dict[str, Any]], *, query: str, ticker: str,
                        time_scope: dict | None = None) -> List[Dict[str, Any]]:
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
            scope = time_scope or {}
            period_end = str(scope.get("period_end") or "")[:10]
            if period_end:
                years = set(re.findall(r"\b20\d{2}\b", str(item.get("title") or "") + " " + str(item.get("snippet") or "")))
                score += 3.0 if period_end[:4] in years else -2.0 if years else 0.0
            published = str(item.get("published_date") or "")[:10]
            cutoff = str(scope.get("as_of") or "")[:10]
            if cutoff and published and published > cutoff:
                continue
            if scope.get("selection") == "latest_complete" and published:
                reference = cutoff or datetime.now(timezone.utc).date().isoformat()
                try:
                    age = (datetime.fromisoformat(reference) - datetime.fromisoformat(published)).days
                    score += max(-2.0, 2.0 - max(age, 0) / 365.0)
                except ValueError:
                    pass
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
        deduped_by_url: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for item in results:
            url = item.get("url", "").strip()
            if not url:
                continue
            if url not in deduped_by_url:
                merged = dict(item)
                merged["search_queries"] = self._merge_unique_strings([], [item.get("search_query")])
                deduped_by_url[url] = merged
                order.append(url)
                continue

            merged = deduped_by_url[url]
            merged["search_queries"] = self._merge_unique_strings(merged.get("search_queries") or [], [item.get("search_query")])
            merged["search_rank"] = min(
                int(merged.get("search_rank") or 10**9),
                int(item.get("search_rank") or 10**9),
            )
        return [deduped_by_url[url] for url in order]

    def _merge_unique_strings(self, existing: List[Any], incoming: List[Any]) -> List[str]:
        values: List[str] = []
        for raw in list(existing or []) + list(incoming or []):
            value = str(raw or "").strip()
            if not value or value in values:
                continue
            values.append(value)
        return values

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
                "search_query": item.get("search_query"),
                "search_queries": item.get("search_queries") or [],
                "search_rank": item.get("search_rank"),
                "confidence": 0.5,  # 降级文档置信度较低
                "degraded": True,
                "degrade_reason": "snippet_only",
            })
        return docs

    def _fetch_documents(self, results: List[Dict[str, Any]], *, full_document: bool = False) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        degraded_docs: List[Dict[str, Any]] = []
        for item in results[: self.MAX_DOCS]:
            doc = self._fetch_document(item, full_document=True) if full_document else self._fetch_document(item)
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

    def _fetch_document(self, item: Dict[str, Any], *, full_document: bool = False) -> Optional[Dict[str, Any]]:
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
            response = session.get(
                url,
                headers=headers,
                timeout=self.FETCH_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
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
            text = self._extract_pdf_text(response.content, full_document=True) if full_document else self._extract_pdf_text(response.content)
        else:
            text = self._extract_html_text(response.text)

        text = self._trim_text(text, 600_000 if full_document else None)
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
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "is_pdf": is_pdf,
            "search_query": item.get("search_query"),
            "search_queries": item.get("search_queries") or [],
            "search_rank": item.get("search_rank"),
            "confidence": confidence,
            "degraded": used_snippet_fallback,
            "degrade_reason": "empty_content_use_snippet" if used_snippet_fallback else None,
        }

    async def _record_rag_observability(self, *, query: str, ticker: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not docs:
            return {}
        try:
            from backend.rag import RAGDocument, get_rag_service
        except Exception as exc:
            logger.info("[DeepSearch] RAG observability unavailable: %s", exc)
            return {"enabled": False, "error": str(exc)}

        collection = self._build_rag_collection(query=query, ticker=ticker)
        rag_docs: List[Any] = []
        for index, item in enumerate(docs, 1):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip() or None
            source = str(item.get("source") or self._infer_source(url) or "web").strip() or "web"
            seed = url or f"{title or 'doc'}::{content[:120]}::{index}"
            source_id = f"deepsearch:{hashlib.md5(seed.encode('utf-8')).hexdigest()}"
            metadata = {
                "origin": "deep_search_agent",
                "ticker": ticker,
                "search_query": item.get("search_query"),
                "search_queries": item.get("search_queries") or [],
                "search_rank": item.get("search_rank"),
                "is_pdf": bool(item.get("is_pdf")),
                "published_date": item.get("published_date"),
                "confidence": item.get("confidence"),
                "degraded": bool(item.get("degraded")),
                "degrade_reason": item.get("degrade_reason"),
                "doc_index": index,
            }
            rag_docs.append(
                RAGDocument(
                    collection=collection,
                    scope="deepsearch",
                    source_id=source_id,
                    content=content,
                    title=title,
                    url=url or None,
                    source=source,
                    metadata=metadata,
                )
            )

        if not rag_docs:
            return {}

        def _sync_record() -> Dict[str, Any]:
            rag_service = get_rag_service()
            ingest_stats = rag_service.ingest_documents(rag_docs)
            hits = rag_service.hybrid_search(query, collection=collection, top_k=min(8, len(rag_docs)))
            return {
                "enabled": True,
                "collection": collection,
                "backend": str(getattr(rag_service, "backend_name", "unknown") or "unknown"),
                "embedding_model": str(getattr(rag_service, "embedding_model", "unknown") or "unknown"),
                "vector_dim": int(getattr(rag_service, "vector_dim", 0) or 0),
                "ingest_stats": ingest_stats if isinstance(ingest_stats, dict) else {"result": ingest_stats},
                "hit_count": len(hits),
                "top_hits": [
                    {
                        "title": hit.get("title"),
                        "url": hit.get("url"),
                        "dense_score": hit.get("dense_score"),
                        "sparse_score": hit.get("sparse_score"),
                        "rrf_score": hit.get("rrf_score"),
                    }
                    for hit in (hits or [])[:5]
                ],
            }

        try:
            return await asyncio.to_thread(_sync_record)
        except Exception as exc:
            logger.exception("[DeepSearch] Failed to record RAG observability: %s", exc)
            return {"enabled": False, "collection": collection, "error": str(exc)}

    def _build_rag_collection(self, *, query: str, ticker: str) -> str:
        from backend.rag.layering import (
            build_deepsearch_working_set_collection,
            build_thread_working_set_collection,
        )

        thread_id = (
            getattr(self, "thread_id", None)
            or getattr(self, "_thread_id", None)
            or getattr(self, "current_thread_id", None)
            or getattr(self, "_current_thread_id", None)
        )
        if str(thread_id or "").strip():
            return build_thread_working_set_collection(str(thread_id))
        return build_deepsearch_working_set_collection(query=query, ticker=ticker)

    def _extract_pdf_text(self, data: bytes, *, full_document: bool = False) -> str:
        if not PdfReader:
            return ""
        try:
            from io import BytesIO

            if full_document and len(data) > 15_000_000:
                return ""
            reader = PdfReader(BytesIO(data))
            pages = []
            size = 0
            for number, page in enumerate(reader.pages[:400 if full_document else 8], 1):
                body = page.extract_text() or ""
                size += len(body)
                if size > 600_000:
                    break
                pages.append(f"[Page {number}]\n{body}")
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
        """从文档标题和片段构建不越过证据边界的确定性摘要。"""
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
        lines.append("- 当前检索证据缺少可核验的结构化财务明细与完整上下文。")
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
