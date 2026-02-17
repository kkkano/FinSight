from typing import Any, Optional
import os
from datetime import datetime

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker


class AllSourcesFailedError(Exception):
    pass


class PriceAgent(BaseFinancialAgent):
    AGENT_NAME = "PriceAgent"
    CACHE_TTL = 30  # 30 seconds for real-time price
    MAX_REFLECTIONS = 1  # Enable one reflection round for gap-filling

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        if circuit_breaker is None:
            circuit_breaker = CircuitBreaker(
                failure_threshold=int(os.getenv("PRICE_CB_FAILURE_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("PRICE_CB_RECOVERY_TIMEOUT", "60")),
                half_open_success_threshold=int(os.getenv("PRICE_CB_HALF_OPEN_SUCCESS", "1")),
            )
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module
        self._last_option_metrics: dict[str, Any] = {}

    def _get_tool_registry(self) -> dict:
        """PriceAgent tool registry: quote + options side signals."""
        registry = {}
        tools = self.tools
        if not tools:
            return registry

        search_fn = getattr(tools, "search", None)
        if search_fn:
            registry["search"] = {
                "func": search_fn,
                "description": "搜索价格补充信息（波动、催化事件、异常交易）",
                "call_with": "query",
            }

        option_metrics_fn = getattr(tools, "get_option_chain_metrics", None)
        if option_metrics_fn:
            registry["get_option_chain_metrics"] = {
                "func": option_metrics_fn,
                "description": "获取期权链衍生指标（IV、PCR、Skew）",
                "call_with": "ticker",
            }
        return registry

    async def _initial_search(self, query: str, ticker: str) -> Any:
        del query
        cache_key = f"{ticker}:price:realtime"
        option_cache_key = f"{ticker}:price:option_metrics"
        self._last_option_metrics = {}

        option_metrics_fn = getattr(self.tools, "get_option_chain_metrics", None)

        def _load_option_metrics() -> None:
            if not option_metrics_fn:
                return
            cached_option = self.cache.get(option_cache_key)
            if isinstance(cached_option, dict):
                self._last_option_metrics = cached_option
                return
            try:
                payload = option_metrics_fn(ticker)
                if isinstance(payload, dict):
                    self._last_option_metrics = payload
                    self.cache.set(option_cache_key, payload, 300)
            except Exception:
                self._last_option_metrics = {}

        cached = self.cache.get(cache_key)
        if cached:
            _load_option_metrics()
            return cached

        sources = ["yfinance", "finnhub", "alpha_vantage", "tavily"]
        last_error = None

        for source in sources:
            if self.circuit_breaker.can_call(source):
                try:
                    result = await self._fetch_from_source(source, ticker)
                    if result:
                        self.circuit_breaker.record_success(source)
                        self.cache.set(cache_key, result, self.CACHE_TTL)
                        _load_option_metrics()
                        return result
                except Exception as e:
                    last_error = e
                    self.circuit_breaker.record_failure(source)

        try:
            fallback_result = await self._fetch_from_source("search", ticker)
            if fallback_result:
                _load_option_metrics()
                return fallback_result
        except Exception:
            pass

        raise AllSourcesFailedError(f"All sources failed for {ticker}. Last error: {last_error}")

    async def _fetch_from_source(self, source: str, ticker: str) -> Any:
        tool_func = None
        if source == "yfinance":
            tool_func = getattr(self.tools, "_fetch_with_yfinance", None)
        elif source == "finnhub":
            tool_func = getattr(self.tools, "_fetch_with_finnhub", None)
        elif source == "alpha_vantage":
            tool_func = getattr(self.tools, "_fetch_with_alpha_vantage", None)
        elif source in {"tavily", "search"}:
            tool_func = getattr(self.tools, "_search_for_price", None)

        if tool_func:
            return tool_func(ticker)
        return None

    async def _first_summary(self, data: Any) -> str:
        deterministic = self._deterministic_summary(data)
        analysis = await self._llm_analyze(
            deterministic,
            role="资深量化交易分析师",
            focus="解读当前价格与日内变动，并结合期权IV/PCR/Skew判断短线风险偏好和交易拥挤度。",
        )
        return analysis if analysis else deterministic

    def _deterministic_summary(self, data: Any) -> str:
        """Build a human-readable price snapshot from raw data (fallback)."""
        if isinstance(data, dict):
            ticker = data.get("ticker", "N/A")
            price = data.get("price", "N/A")
            currency = data.get("currency", "USD")
            change_pct = data.get("change_percent") or data.get("change_pct")
            text = f"{ticker} 当前价格: {currency} {price}"
            if change_pct is not None:
                try:
                    pct = float(change_pct)
                    direction = "上涨" if pct >= 0 else "下跌"
                    text += f"，日内{direction} {pct:+.2f}%"
                except (TypeError, ValueError):
                    pass

            option_metrics = self._last_option_metrics if isinstance(self._last_option_metrics, dict) else {}
            if option_metrics and not option_metrics.get("error"):
                snippets = []
                iv_atm = option_metrics.get("iv_atm")
                pcr = option_metrics.get("put_call_ratio_oi") or option_metrics.get("put_call_ratio_volume")
                skew = option_metrics.get("iv_skew_25d")
                if isinstance(iv_atm, (int, float)):
                    snippets.append(f"ATM IV {float(iv_atm):.2%}")
                if isinstance(pcr, (int, float)):
                    snippets.append(f"PCR {float(pcr):.2f}")
                if isinstance(skew, (int, float)):
                    snippets.append(f"Skew {float(skew):+.2%}")
                if snippets:
                    text += "；" + "，".join(snippets)
            return text + "。"
        elif isinstance(data, str) and data:
            return data
        return str(data)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        if isinstance(raw_data, dict):
            price = raw_data.get("price", "N/A")
            currency = raw_data.get("currency", "USD")
            ticker = raw_data.get("ticker", "UNKNOWN")
            source = raw_data.get("source", "yfinance")
            as_of = raw_data.get("as_of", datetime.now().isoformat())
            fallback_used = raw_data.get("fallback_used", False)
            change = raw_data.get("change")
            change_percent = raw_data.get("change_percent")
            if change is None:
                change = raw_data.get("change_abs")
            if change_percent is None:
                change_percent = raw_data.get("change_pct")
            if change_percent is not None:
                try:
                    change_percent = float(change_percent)
                except Exception:
                    change_percent = None
            summary_text = f"{ticker} 当前价格: {currency} {price}。"
            if change_percent is not None:
                direction = "上涨" if change_percent >= 0 else "下跌"
                summary_text += f" 日内变动 {change_percent:+.2f}%（{direction}）。"
            evidence_text = str(raw_data)
            if isinstance(summary, str) and len(summary) > 150:
                summary_text = summary
        elif isinstance(raw_data, str) and raw_data:
            summary_text = raw_data
            source = "yfinance"
            as_of = datetime.now().isoformat()
            fallback_used = False
            evidence_text = raw_data
            try:
                import re

                match = re.search(r"Change:\s*\$[+-]?[0-9.]+\s*\(\s*([+-]?[0-9.]+)%\s*\)", raw_data)
                if match:
                    pct = float(match.group(1))
                    direction = "上涨" if pct >= 0 else "下跌"
                    summary_text = f"{raw_data}。日内变动 {pct:+.2f}%（{direction}）。"
            except Exception:
                pass
        else:
            summary_text = summary or "价格数据获取失败"
            source = "unknown"
            as_of = datetime.now().isoformat()
            fallback_used = True
            evidence_text = str(raw_data) if raw_data else "暂无数据"

        evidence = [
            EvidenceItem(
                text=evidence_text,
                source=source,
                timestamp=as_of,
            )
        ]
        data_sources = [source]

        option_metrics = self._last_option_metrics if isinstance(self._last_option_metrics, dict) else {}
        if option_metrics and not option_metrics.get("error"):
            option_source = str(option_metrics.get("source") or "yfinance_options")
            option_as_of = str(option_metrics.get("as_of") or as_of)
            pcr = option_metrics.get("put_call_ratio_oi") or option_metrics.get("put_call_ratio_volume")
            iv_atm = option_metrics.get("iv_atm")
            skew = option_metrics.get("iv_skew_25d")
            option_bits = []
            if isinstance(iv_atm, (int, float)):
                option_bits.append(f"ATM IV {float(iv_atm):.2%}")
            if isinstance(pcr, (int, float)):
                option_bits.append(f"PCR {float(pcr):.2f}")
            if isinstance(skew, (int, float)):
                option_bits.append(f"Skew {float(skew):+.2%}")
            option_text = "Option metrics: " + ", ".join(option_bits) if option_bits else "Option metrics available."
            evidence.append(
                EvidenceItem(
                    text=option_text,
                    source=option_source,
                    timestamp=option_as_of,
                    meta=option_metrics,
                )
            )
            if option_source not in data_sources:
                data_sources.append(option_source)

        fallback_reason = None
        if fallback_used:
            if isinstance(raw_data, dict):
                fallback_reason = str(raw_data.get("fallback_detail") or raw_data.get("error") or "primary_source_unavailable")
            else:
                fallback_reason = "no_structured_data"

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary_text,
            evidence=evidence,
            confidence=1.0 if not fallback_used else 0.5,
            data_sources=data_sources,
            as_of=as_of,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            retryable=True,
        )
