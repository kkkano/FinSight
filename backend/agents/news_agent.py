from typing import Any, List, Optional
from datetime import datetime
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

class NewsAgent(BaseFinancialAgent):
    AGENT_NAME = "NewsAgent"
    CACHE_TTL = 600  # 10 minutes

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    async def _initial_search(self, query: str, ticker: str) -> List[Any]:
        cache_key = f"{ticker}:news:24h"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        results = []

        # 1. Try Finnhub News
        if self.circuit_breaker.can_call("finnhub"):
            try:
                # Assuming tools module has this method
                finnhub_news = getattr(self.tools, "_fetch_with_finnhub_news", None)
                if finnhub_news:
                    news_items = finnhub_news(ticker)
                    if news_items:
                        results.extend(news_items)
                        self.circuit_breaker.record_success("finnhub")
            except Exception:
                self.circuit_breaker.record_failure("finnhub")

        # 2. Try Tavily Search (Fallback or Supplement)
        if not results or len(results) < 3:
             if self.circuit_breaker.can_call("tavily"):
                try:
                    tavily_news = getattr(self.tools, "_search_company_news", None)
                    if tavily_news:
                         # Tavily search for news
                         t_results = tavily_news(f"{ticker} stock news")
                         if t_results:
                             results.extend(t_results)
                             self.circuit_breaker.record_success("tavily")
                except Exception:
                    self.circuit_breaker.record_failure("tavily")

        # Deduplicate
        seen_urls = set()
        unique_results = []
        for item in results:
            url = item.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(item)

        self.cache.set(cache_key, unique_results, self.CACHE_TTL)
        return unique_results

    async def _first_summary(self, data: List[Any]) -> str:
        if not data:
            return "No recent news found."

        # Simple concatenation for MVP, real impl would use LLM
        titles = [item.get("headline", item.get("title", "")) for item in data[:5]]
        return f"Recent news includes: {'; '.join(titles)}"

    async def _identify_gaps(self, summary: str) -> List[str]:
        # MVP: If summary is too short, maybe look for more?
        # Real implementation: LLM check
        return []

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Any:
        return []

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        return summary

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence = []
        sources = set()

        for item in raw_data:
            source = item.get("source", "unknown")
            sources.add(source)
            evidence.append(EvidenceItem(
                text=item.get("headline", item.get("title", "")),
                source=source,
                url=item.get("url"),
                timestamp=item.get("datetime", item.get("published_at"))
            ))

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=0.8 if raw_data else 0.1,
            data_sources=list(sources),
            as_of=datetime.now().isoformat(),
            fallback_used=False
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
                prompt = f"""请用简洁的中文总结以下新闻要点，不超过100字：

{chr(10).join(news_list)}

总结："""
                async for chunk in self.llm.astream([HumanMessage(content=prompt)]):
                    if hasattr(chunk, 'content') and chunk.content:
                        yield chunk.content
                return
            except Exception:
                pass  # 回退到简单方法
        
        # 简单方法：直接拼接标题
        yield f"近期新闻包括：{'; '.join([item.get('headline', item.get('title', '')) for item in data[:3]])}"
