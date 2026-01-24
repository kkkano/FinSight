from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime
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
            logger.info(f"[DeepSearch] search: {q}")
            results.extend(self._search_web(q))
            if len(results) >= self.MAX_RESULTS:
                break

        results = self._dedupe_results(results)[:self.MAX_RESULTS]
        docs = await asyncio.to_thread(self._fetch_documents, results)
        if docs:
            sources = sorted({doc.get("source", "web") for doc in docs if isinstance(doc, dict)})
            pdf_count = sum(1 for doc in docs if doc.get("is_pdf"))
            logger.info(f"[DeepSearch] fetched docs={len(docs)} pdfs={pdf_count} sources={sources}")
        if docs:
            self.cache.set(cache_key, docs, ttl=self.CACHE_TTL)
        return docs

    async def _first_summary(self, data: List[Dict[str, Any]]) -> str:
        return await self._summarize_docs(data)

    async def _identify_gaps(self, summary: str) -> List[str]:
        if not self.llm:
            return []

        prompt = f"""<role>金融深度研究Self-RAG控制器</role>

<task>评估当前摘要的信息完整性，决定是否需要补充检索</task>

<current_summary>
{summary}
</current_summary>

<evaluation_criteria>
需要补充检索的情况（needs_more=true）：
- 关键财务数据缺失（营收、利润、估值指标）
- 风险因素分析不完整
- 竞争格局描述模糊
- 缺乏时效性信息（最新财报、公告）
- 论点缺乏数据支撑

信息充足的情况（needs_more=false）：
- 核心投资逻辑清晰
- 关键数据点完整
- 风险与机会均有覆盖
</evaluation_criteria>

<output_format>
仅返回JSON，禁止任何解释或前言：
{{"needs_more": true/false, "queries": ["具体检索词1", "具体检索词2"]}}

queries要求：
- 最多3个，每个需具体明确
- 使用中英文混合检索词提高召回
- 聚焦摘要中明确缺失的信息点
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
        if not is_safe_url(url):
            logger.info(f"[DeepSearch] Blocked unsafe url: {url}")
            return None
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; FinSightBot/0.1)",
        }
        try:
            session = self._get_session()
            response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
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

        prev_section = f"\n<previous_summary>\n{previous_summary}\n</previous_summary>" if previous_summary else ""
        prompt = f"""<role>资深金融研究分析师</role>

<task>基于检索源撰写深度研究备忘录</task>
{prev_section}
<sources>
{bundle}
</sources>

<requirements>
- 语言：简体中文
- 输出4-6条核心洞察（事实+影响），每条需有数据或来源支撑
- 引用格式：[1]、[2]（对应源编号）
- 标注1-2条不确定性/风险点
- 明确标注信息缺口（如有）
</requirements>

<output_format>
## 核心发现
[编号要点列表，每条含数据引用与一句影响判断]

## 影响与解读
[2-3句综合解读，强调对标的/行业的潜在影响]

## 风险提示
[关键风险因素]

## 信息缺口
[尚需补充的信息，无则写“暂无”]
</output_format>

<constraints>
- 禁止开场白、寒暄、总结性陈述
- 直接输出结构化内容
- 专业商务语气
</constraints>"""

        result = await self._call_llm(prompt)
        return result.strip() if result else "Summary unavailable."

    async def _call_llm(self, prompt: str) -> str:
        try:
            # 获取速率限制令牌
            from backend.services.rate_limiter import acquire_llm_token
            if not await acquire_llm_token(timeout=60.0):
                logger.warning("[DeepSearch] Rate limit timeout, skipping LLM call")
                return ""
            
            message = HumanMessage(content=prompt)
            if hasattr(self.llm, "ainvoke"):
                response = await self.llm.ainvoke([message])
            else:
                response = await asyncio.to_thread(self.llm.invoke, [message])
            return getattr(response, "content", "") if response is not None else ""
        except Exception as exc:
            logger.info(f"[DeepSearch] LLM call failed: {exc}")
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
