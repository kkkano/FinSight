from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse
import ipaddress
import socket
import asyncio
import json
import os
import re

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
from backend.services.circuit_breaker import CircuitBreaker


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    lowered = host.lower()
    if lowered in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return False
    if lowered.endswith(".local") or lowered.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(lowered)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
        return True
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
    except Exception:
        return False
    return True


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

    async def research(self, query: str, ticker: str) -> AgentOutput:
        """
        Override to merge reflection docs into evidence for Self-RAG.
        """
        trace: List[Dict[str, Any]] = []
        queries = self._build_queries(query, ticker)
        print(f"[DeepSearch] queries: {queries}")

        results = await self._initial_search(query, ticker, queries=queries)
        summary = await self._first_summary(results)

        trace.append(self._trace_step(
            stage="initial_search",
            payload=self._build_trace_payload(queries, results),
        ))
        self._log_documents(results, "initial")
        trace.append(self._trace_step(
            stage="summary",
            payload={"summary_preview": self._trim_text(summary, 400)},
        ))

        all_docs: List[Dict[str, Any]] = list(results) if isinstance(results, list) else []

        for _ in range(self.MAX_REFLECTIONS):
            gaps = await self._identify_gaps(summary)
            trace.append(self._trace_step(
                stage="self_rag_gap_detection",
                payload={"needs_more": bool(gaps), "queries": gaps},
            ))
            if not gaps:
                break
            new_data = await self._targeted_search(gaps, ticker)
            if isinstance(new_data, list) and new_data:
                all_docs.extend(new_data)
                trace.append(self._trace_step(
                    stage="targeted_search",
                    payload=self._build_trace_payload(gaps, new_data),
                ))
                self._log_documents(new_data, "targeted")
            summary = await self._update_summary(summary, new_data)
            trace.append(self._trace_step(
                stage="summary_update",
                payload={"summary_preview": self._trim_text(summary, 400)},
            ))

        if all_docs:
            all_docs = self._dedupe_results(all_docs)
        output = self._format_output(summary, all_docs or results, trace=trace)
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
            print(f"[DeepSearch] search: {q}")
            results.extend(self._search_web(q))
            if len(results) >= self.MAX_RESULTS:
                break

        results = self._dedupe_results(results)[:self.MAX_RESULTS]
        docs = await asyncio.to_thread(self._fetch_documents, results)
        if docs:
            sources = sorted({doc.get("source", "web") for doc in docs if isinstance(doc, dict)})
            pdf_count = sum(1 for doc in docs if doc.get("is_pdf"))
            print(f"[DeepSearch] fetched docs={len(docs)} pdfs={pdf_count} sources={sources}")
        if docs:
            self.cache.set(cache_key, docs, ttl=self.CACHE_TTL)
        return docs

    async def _first_summary(self, data: List[Dict[str, Any]]) -> str:
        return await self._summarize_docs(data)

    async def _identify_gaps(self, summary: str) -> List[str]:
        if not self.llm:
            return []

        prompt = (
            "You are a Self-RAG controller for financial deep research.\n"
            "Given the current summary, decide if more retrieval is needed.\n"
            "Return JSON only: {\"needs_more\": true/false, \"queries\": [\"query1\", \"query2\"]}\n\n"
            f"Summary:\n{summary}\n"
        )
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
            if len(results) >= self.MAX_RESULTS:
                break
        results = self._dedupe_results(results)[:self.MAX_RESULTS]
        return await asyncio.to_thread(self._fetch_documents, results)

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        if not new_data:
            return summary
        return await self._summarize_docs(new_data, previous_summary=summary)

    def _format_output(self, summary: str, raw_data: Any, trace: Optional[List[Dict[str, Any]]] = None) -> AgentOutput:
        evidence: List[EvidenceItem] = []
        data_sources: List[str] = []
        fallback_used = False

        if isinstance(raw_data, list):
            for item in raw_data:
                source = item.get("source", "web")
                data_sources.append(source)
                title = item.get("title") or ""
                snippet = item.get("snippet") or item.get("content", "")[:240]
                evidence.append(EvidenceItem(
                    text=snippet,
                    source=source,
                    url=item.get("url"),
                    timestamp=item.get("published_date"),
                    confidence=item.get("confidence", 0.7),
                    title=title,
                    meta={"is_pdf": item.get("is_pdf", False)},
                ))

        data_sources = sorted(set(data_sources)) if data_sources else ["web"]
        if not raw_data:
            fallback_used = True
        confidence = self._estimate_confidence(raw_data)
        risks = ["Sources may contain subjective analysis."]
        if fallback_used:
            risks.append("Limited deep research sources; results may be incomplete.")

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=data_sources,
            as_of=datetime.now().isoformat(),
            fallback_used=fallback_used,
            risks=risks,
            trace=trace or [],
        )

    def _trace_step(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stage": stage,
            "timestamp": datetime.now().isoformat(),
            "data": payload,
        }

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
            print(f"[DeepSearch] {label} doc {idx}: {title} | {url} | pdf={is_pdf}")

    def _build_queries(self, query: str, ticker: str) -> List[str]:
        base = query.strip()
        if ticker and ticker not in base:
            base = f"{ticker} {base}".strip()

        query_lower = query.lower()
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
            topics = [
                "investment thesis pdf",
                "earnings transcript analysis",
                "competitive landscape risks",
            ]
        else:
            if "investment thesis pdf" not in topics:
                topics.append("investment thesis pdf")

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
                print(f"[DeepSearch] Tavily search failed: {exc}")

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
                print(f"[DeepSearch] Exa search failed: {exc}")

        if not results and self.tools and hasattr(self.tools, "search"):
            try:
                raw = self.tools.search(query)
                results = self._parse_search_text(raw)
            except Exception as exc:
                print(f"[DeepSearch] Search fallback failed: {exc}")

        return results

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

    def _fetch_documents(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        for item in results[: self.MAX_DOCS]:
            doc = self._fetch_document(item)
            if not doc:
                continue
            if len(doc.get("content", "")) < self.MIN_TEXT_CHARS:
                continue
            docs.append(doc)
        return docs

    def _fetch_document(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = item.get("url", "")
        if not url:
            return None
        if not _is_safe_url(url):
            print(f"[DeepSearch] Blocked unsafe url: {url}")
            return None
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; FinSightBot/0.1)",
        }
        try:
            session = self._get_session()
            response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
            if response.url and not _is_safe_url(response.url):
                print(f"[DeepSearch] Blocked unsafe redirect: {response.url}")
                return None
            response.raise_for_status()
        except Exception as exc:
            print(f"[DeepSearch] Fetch failed: {exc}")
            return None

        content_type = response.headers.get("Content-Type", "").lower()
        is_pdf = url.lower().endswith(".pdf") or "application/pdf" in content_type
        text = ""
        if is_pdf:
            text = self._extract_pdf_text(response.content)
        else:
            text = self._extract_html_text(response.text)

        text = self._trim_text(text)
        snippet = item.get("snippet") or text[:240]
        return {
            "title": item.get("title") or self._infer_title(url),
            "url": url,
            "snippet": snippet,
            "content": text,
            "source": item.get("source", self._infer_source(url)),
            "published_date": item.get("published_date"),
            "is_pdf": is_pdf,
            "confidence": 0.85 if is_pdf else 0.7,
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
            print(f"[DeepSearch] PDF parse failed: {exc}")
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
            return "No deep research sources found."

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
            return f"Deep research sources found: {titles}."

        prompt_parts = [
            "You are a financial research analyst. Summarize the sources into a concise deep research memo.",
            "Include 3-5 key insights and cite sources using [1], [2] style.",
            "Call out any missing info explicitly.",
        ]
        if previous_summary:
            prompt_parts.append(f"Previous summary:\n{previous_summary}")
        prompt_parts.append(f"Sources:\n{bundle}")
        prompt = "\n\n".join(prompt_parts)

        result = await self._call_llm(prompt)
        return result.strip() if result else "Summary unavailable."

    async def _call_llm(self, prompt: str) -> str:
        try:
            message = HumanMessage(content=prompt)
            if hasattr(self.llm, "ainvoke"):
                response = await self.llm.ainvoke([message])
            else:
                response = await asyncio.to_thread(self.llm.invoke, [message])
            return getattr(response, "content", "") if response is not None else ""
        except Exception as exc:
            print(f"[DeepSearch] LLM call failed: {exc}")
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

    def _estimate_confidence(self, docs: Any) -> float:
        if not isinstance(docs, list) or not docs:
            return 0.2
        base = 0.6
        bonus = min(len(docs), 3) * 0.1
        pdf_bonus = 0.1 if any(doc.get("is_pdf") for doc in docs) else 0.0
        return min(0.95, base + bonus + pdf_bonus)
