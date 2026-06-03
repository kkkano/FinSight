from dataclasses import asdict, dataclass, field
from math import sqrt
from typing import Any, Optional
import os
import re
from datetime import datetime

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.agents.chart_specs import build_price_behavior_chart_specs
from backend.research.agent_quality_contract import assign_evidence_source_ids, build_agent_claim
from backend.services.circuit_breaker import CircuitBreaker


# 价格行为枚举 → 中文（用户可见 claim 中文化，B 类固定模板）
_PRICE_DIRECTION_CN: dict[str, str] = {
    "positive": "偏强",
    "negative": "偏弱",
    "mixed": "分化",
    "neutral": "中性",
    "up": "上行",
    "down": "下行",
    "flat": "走平",
    "bullish": "偏多",
    "bearish": "偏空",
}

# 量价确认信号枚举 → 中文
_VOLUME_SIGNAL_CN: dict[str, str] = {
    "price_up_volume_confirmed": "价涨量增确认",
    "price_down_distribution": "价跌放量派发",
    "low_volume_move": "缩量波动",
    "available": "数据已获取",
}


def _price_direction_cn(value: str) -> str:
    """价格方向/状态枚举映射为中文，未知值原样返回。"""
    return _PRICE_DIRECTION_CN.get(str(value or "").strip().lower(), str(value or ""))


def _volume_signal_cn(value: str) -> str:
    """量价信号枚举映射为中文，未知值原样返回。"""
    return _VOLUME_SIGNAL_CN.get(str(value or "").strip().lower(), str(value or ""))


class AllSourcesFailedError(Exception):
    pass


@dataclass
class PriceBehaviorSnapshot:
    ticker: str
    as_of: str
    quote: dict[str, Any] = field(default_factory=dict)
    trend: dict[str, Any] = field(default_factory=dict)
    momentum: dict[str, Any] = field(default_factory=dict)
    volume_price: dict[str, Any] = field(default_factory=dict)
    relative_strength: dict[str, Any] = field(default_factory=dict)
    volatility_structure: dict[str, Any] = field(default_factory=dict)
    key_levels: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    event_explanation: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    missing_tool_todos: list[str] = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    source: str = "price_behavior_snapshot"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        quote = payload.get("quote") if isinstance(payload.get("quote"), dict) else {}
        payload["snapshot_type"] = "PriceBehaviorSnapshot"
        payload["price"] = quote.get("price")
        payload["currency"] = quote.get("currency", "USD")
        payload["change"] = quote.get("change")
        payload["change_percent"] = quote.get("change_percent")
        payload["source"] = quote.get("source") or payload.get("source")
        payload["data_sources"] = list(payload.get("sources") or [])
        return payload


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
        """PriceAgent tool registry: quote + price-behavior side signals."""
        registry = {}
        tools = self.tools
        if not tools:
            return registry

        search_fn = getattr(tools, "search", None)
        if search_fn:
            registry["search"] = {
                "func": search_fn,
                "description": "搜索价格补充信息、价格异动新闻和催化事件。TODO: 当前没有专门的价格异动归因工具，search 仅作兜底。",
                "call_with": "query",
            }

        quote_fn = getattr(tools, "get_stock_price", None)
        if quote_fn:
            registry["get_stock_price"] = {
                "func": quote_fn,
                "description": "获取当前报价、涨跌幅和时间戳，校准价格判断。",
                "call_with": "ticker",
            }

        history_fn = getattr(tools, "get_stock_historical_data", None)
        if history_fn:
            registry["get_stock_historical_data"] = {
                "func": lambda ticker: self._load_history_payload(ticker, period="1y", interval="1d"),
                "description": "获取多周期历史价（日线），用于计算1周/1月/3月/6月/1年收益、动量、量价、ATR和回撤。",
                "call_with": "ticker",
            }
            registry["get_market_benchmark_history"] = {
                "func": lambda _ticker: self._load_benchmark_histories(),
                "description": "获取 SPY/QQQ 大盘 benchmark 历史价，用于相对强弱 RS。TODO: 当前没有自动同行发现工具。",
                "call_with": "ticker",
            }
            registry["get_relative_strength"] = {
                "func": lambda ticker: self._build_relative_strength_snapshot(ticker),
                "description": "基于现有历史价工具计算目标相对 SPY/QQQ 的1月/3月相对强弱。",
                "call_with": "ticker",
            }

        drawdown_fn = getattr(tools, "analyze_historical_drawdowns", None)
        if drawdown_fn:
            registry["analyze_historical_drawdowns"] = {
                "func": drawdown_fn,
                "description": "获取历史最大回撤文本摘要，补充波动率/回撤结构。",
                "call_with": "ticker",
            }

        performance_fn = getattr(tools, "get_performance_comparison", None)
        if performance_fn:
            registry["get_performance_comparison"] = {
                "func": lambda ticker: performance_fn({"target": ticker, "SPY": "SPY", "QQQ": "QQQ"}),
                "description": "获取目标与 SPY/QQQ 的区间表现对比文本，作为 RS 交叉验证。",
                "call_with": "ticker",
            }

        option_metrics_fn = getattr(tools, "get_option_chain_metrics", None)
        if option_metrics_fn:
            registry["get_option_chain_metrics"] = {
                "func": option_metrics_fn,
                "description": "获取期权链衍生指标（ATM IV、PCR、25D Skew）。TODO: 当前工具未提供 IV rank 和完整期限结构。",
                "call_with": "ticker",
            }
        return registry

    async def _initial_search(self, query: str, ticker: str) -> Any:
        cache_key = f"{ticker}:price:realtime"
        self._last_option_metrics = {}

        cached = self.cache.get(cache_key)
        if cached and self._is_supported_payload(cached):
            quote_payload = cached
        else:
            quote_payload = await self._fetch_realtime_quote(ticker)
            self.cache.set(cache_key, quote_payload, self.CACHE_TTL)

        option_metrics = self._load_option_metrics(ticker)
        history_payload = self._load_history_payload(ticker, period="1y", interval="1d")
        benchmark_histories = self._load_benchmark_histories()
        drawdown_summary = self._load_drawdown_summary(ticker)
        event_explanation = self._load_event_explanation(query, ticker, quote_payload)

        snapshot = self._build_price_behavior_snapshot(
            ticker=ticker,
            quote_payload=quote_payload,
            history_payload=history_payload,
            benchmark_histories=benchmark_histories,
            option_metrics=option_metrics,
            drawdown_summary=drawdown_summary,
            event_explanation=event_explanation,
        )
        return snapshot.to_dict()

    async def _fetch_realtime_quote(self, ticker: str) -> Any:
        sources = ["yfinance", "finnhub", "alpha_vantage", "tavily"]
        last_error = None

        for source in sources:
            if self.circuit_breaker.can_call(source):
                try:
                    result = await self._fetch_from_source(source, ticker)
                    if self._is_quote_success(result):
                        self.circuit_breaker.record_success(source)
                        return result
                except Exception as e:
                    last_error = e
                    self.circuit_breaker.record_failure(source)

        try:
            fallback_result = await self._fetch_from_source("search", ticker)
            if self._is_quote_success(fallback_result):
                return fallback_result
        except Exception:
            pass

        raise AllSourcesFailedError(f"All sources failed for {ticker}. Last error: {last_error}")

    def _is_supported_payload(self, payload: Any) -> bool:
        return isinstance(payload, (dict, list, str))

    def _is_quote_success(self, payload: Any) -> bool:
        if not self._is_supported_payload(payload):
            return False
        if isinstance(payload, dict):
            if payload.get("error"):
                return False
            return self._safe_float(payload.get("price") or payload.get("current_price") or payload.get("regularMarketPrice")) is not None
        if isinstance(payload, str):
            text = payload.strip()
            return bool(text) and not text.lower().startswith("error:")
        return False

    def _call_optional_tool(self, tool_name: str, *args, **kwargs) -> Any:
        tool_fn = getattr(self.tools, tool_name, None) if self.tools else None
        if not callable(tool_fn):
            return None
        try:
            payload = tool_fn(*args, **kwargs)
        except Exception:
            return None
        if isinstance(payload, str):
            stripped = payload.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    import json

                    return json.loads(stripped)
                except Exception:
                    return payload
        return payload if self._is_supported_payload(payload) else None

    def _load_option_metrics(self, ticker: str) -> dict[str, Any]:
        option_cache_key = f"{ticker}:price:option_metrics"
        cached_option = self.cache.get(option_cache_key)
        if isinstance(cached_option, dict):
            self._last_option_metrics = cached_option
            return cached_option

        payload = self._call_optional_tool("get_option_chain_metrics", ticker)
        if isinstance(payload, dict):
            self._last_option_metrics = payload
            self.cache.set(option_cache_key, payload, 300)
            return payload

        self._last_option_metrics = {}
        return {}

    def _load_history_payload(self, ticker: str, period: str = "1y", interval: str = "1d") -> dict[str, Any]:
        history_cache_key = f"{ticker}:price:history:{period}:{interval}"
        cached_history = self.cache.get(history_cache_key)
        if isinstance(cached_history, dict):
            return cached_history

        payload = self._call_optional_tool("get_stock_historical_data", ticker, period=period, interval=interval)
        if isinstance(payload, dict):
            if payload.get("kline_data"):
                self.cache.set(history_cache_key, payload, 900)
            return payload
        return {}

    def _load_benchmark_histories(self) -> dict[str, dict[str, Any]]:
        if not callable(getattr(self.tools, "get_stock_historical_data", None)):
            return {}
        histories: dict[str, dict[str, Any]] = {}
        for benchmark in ("SPY", "QQQ"):
            payload = self._load_history_payload(benchmark, period="1y", interval="1d")
            if isinstance(payload, dict) and payload.get("kline_data"):
                histories[benchmark] = payload
        return histories

    def _load_drawdown_summary(self, ticker: str) -> Any:
        return self._call_optional_tool("analyze_historical_drawdowns", ticker)

    def _load_event_explanation(self, query: str, ticker: str, quote_payload: Any) -> dict[str, Any]:
        quote = self._normalize_quote(ticker, quote_payload)
        change_pct = self._safe_float(quote.get("change_percent"))
        if change_pct is None or abs(change_pct) < 3:
            return {}
        search_fn = getattr(self.tools, "search", None) if self.tools else None
        if not callable(search_fn):
            return {
                "trigger": "large_price_move",
                "change_percent": change_pct,
                "summary": None,
                "todo": "TODO: 缺少专门的价格异动事件解释工具，且 search 不可用。",
            }
        event_cache_key = f"{ticker}:price:event_explanation:{round(change_pct, 1)}"
        cached_event = self.cache.get(event_cache_key)
        if isinstance(cached_event, dict):
            return cached_event
        search_query = f"{ticker} stock price move today reason {query}".strip()
        try:
            payload = search_fn(search_query)
        except Exception:
            return {
                "trigger": "large_price_move",
                "change_percent": change_pct,
                "summary": None,
                "todo": "TODO: search 兜底解释价格异动失败，需要专门事件归因工具。",
            }
        result = {
            "trigger": "large_price_move",
            "change_percent": change_pct,
            "summary": str(payload)[:1200] if payload else None,
            "source": "search",
        }
        self.cache.set(event_cache_key, result, 300)
        return result

    def _build_relative_strength_snapshot(self, ticker: str) -> dict[str, Any]:
        history_payload = self._load_history_payload(ticker, period="1y", interval="1d")
        return self._build_relative_strength(
            history_payload,
            self._load_benchmark_histories(),
        )

    def _build_price_behavior_snapshot(
        self,
        *,
        ticker: str,
        quote_payload: Any,
        history_payload: dict[str, Any],
        benchmark_histories: dict[str, dict[str, Any]],
        option_metrics: dict[str, Any],
        drawdown_summary: Any,
        event_explanation: dict[str, Any],
    ) -> PriceBehaviorSnapshot:
        quote = self._normalize_quote(ticker, quote_payload)
        rows = self._extract_kline_rows(history_payload)
        trend = self._build_trend(rows, history_payload)
        momentum = self._build_momentum(rows)
        volume_price = self._build_volume_price(rows)
        volatility = self._build_volatility_structure(rows, option_metrics, drawdown_summary)
        key_levels = self._build_key_levels(rows)
        relative_strength = self._build_relative_strength(history_payload, benchmark_histories)
        options = self._normalize_option_metrics(option_metrics)

        sources = []
        for source in (
            quote.get("source"),
            history_payload.get("source") if isinstance(history_payload, dict) else None,
            options.get("source"),
            event_explanation.get("source") if isinstance(event_explanation, dict) else None,
        ):
            if source and source not in sources:
                sources.append(str(source))
        for benchmark, payload in benchmark_histories.items():
            source = payload.get("source") if isinstance(payload, dict) else None
            benchmark_source = f"{benchmark}:{source or 'history'}"
            if benchmark_source not in sources:
                sources.append(benchmark_source)

        fallback_used = bool(quote.get("fallback_used")) or not bool(quote.get("price"))
        fallback_reason = quote.get("fallback_reason")
        if not rows:
            fallback_reason = fallback_reason or "historical_price_unavailable"

        return PriceBehaviorSnapshot(
            ticker=ticker,
            as_of=str(quote.get("as_of") or datetime.now().isoformat()),
            quote=quote,
            trend=trend,
            momentum=momentum,
            volume_price=volume_price,
            relative_strength=relative_strength,
            volatility_structure=volatility,
            key_levels=key_levels,
            options=options,
            event_explanation=event_explanation or {},
            raw={
                "quote": quote_payload,
                "history": history_payload,
                "benchmarks": benchmark_histories,
                "options": option_metrics,
                "drawdown_summary": drawdown_summary,
            },
            sources=sources,
            missing_tool_todos=self._missing_tool_todos(),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    def _normalize_quote(self, ticker: str, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            price = self._safe_float(
                payload.get("price")
                or payload.get("current_price")
                or payload.get("regularMarketPrice")
                or payload.get("last")
            )
            change = self._safe_float(payload.get("change") if payload.get("change") is not None else payload.get("change_abs"))
            change_percent = self._safe_float(
                payload.get("change_percent")
                if payload.get("change_percent") is not None
                else payload.get("change_pct")
            )
            source = str(payload.get("source") or "quote")
            return {
                "ticker": str(payload.get("ticker") or ticker),
                "price": price,
                "currency": payload.get("currency") or "USD",
                "change": change,
                "change_percent": change_percent,
                "source": source,
                "as_of": payload.get("as_of") or datetime.now().isoformat(),
                "fallback_used": bool(payload.get("fallback_used")) or source in {"search", "tavily"},
                "fallback_reason": payload.get("fallback_detail") or payload.get("error"),
                "raw": payload,
            }
        if isinstance(payload, str):
            price = None
            change = None
            change_percent = None
            price_match = re.search(r"Current Price(?: \(via search\))?:\s*\$?([0-9,]+(?:\.[0-9]+)?)", payload, re.IGNORECASE)
            if price_match:
                price = self._safe_float(price_match.group(1))
            change_match = re.search(
                r"Change:\s*\$?([+-]?[0-9,]+(?:\.[0-9]+)?)\s*\(\s*([+-]?[0-9.]+)%\s*\)",
                payload,
                re.IGNORECASE,
            )
            if change_match:
                change = self._safe_float(change_match.group(1))
                change_percent = self._safe_float(change_match.group(2))
            source = "search" if "via search" in payload.lower() else "quote"
            return {
                "ticker": ticker,
                "price": price,
                "currency": "USD",
                "change": change,
                "change_percent": change_percent,
                "source": source,
                "as_of": datetime.now().isoformat(),
                "fallback_used": source == "search",
                "fallback_reason": None if price is not None else "unparsed_quote",
                "raw": payload,
            }
        return {
            "ticker": ticker,
            "price": None,
            "currency": "USD",
            "change": None,
            "change_percent": None,
            "source": "unknown",
            "as_of": datetime.now().isoformat(),
            "fallback_used": True,
            "fallback_reason": "unsupported_quote_payload",
            "raw": payload,
        }

    def _normalize_option_metrics(self, option_metrics: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(option_metrics, dict) or not option_metrics or option_metrics.get("error"):
            return {}
        pcr = option_metrics.get("put_call_ratio_oi")
        if pcr is None:
            pcr = option_metrics.get("put_call_ratio_volume")
        return {
            "source": option_metrics.get("source") or "options",
            "as_of": option_metrics.get("as_of"),
            "expiry": option_metrics.get("expiry"),
            "iv_atm": self._safe_float(option_metrics.get("iv_atm")),
            "put_call_ratio": self._safe_float(pcr),
            "put_call_ratio_oi": self._safe_float(option_metrics.get("put_call_ratio_oi")),
            "put_call_ratio_volume": self._safe_float(option_metrics.get("put_call_ratio_volume")),
            "iv_skew_25d": self._safe_float(option_metrics.get("iv_skew_25d")),
            "iv_rank": None,
            "term_structure": None,
            "todo": "TODO: get_option_chain_metrics 当前未提供 IV rank / term structure，仅透传 ATM IV、PCR、Skew。",
        }

    def _extract_kline_rows(self, history_payload: Any) -> list[dict[str, Any]]:
        if not isinstance(history_payload, dict):
            return []
        rows = history_payload.get("kline_data")
        if not isinstance(rows, list):
            return []
        clean_rows = []
        for row in rows:
            if isinstance(row, dict) and self._safe_float(row.get("close")) is not None:
                clean_rows.append(row)
        return clean_rows

    def _build_trend(self, rows: list[dict[str, Any]], history_payload: dict[str, Any]) -> dict[str, Any]:
        closes = self._series(rows, "close")
        returns = {
            "1d": self._period_return(closes, 1),
            "1w": self._period_return(closes, 5),
            "1mo": self._period_return(closes, 21),
            "3mo": self._period_return(closes, 63),
            "6mo": self._period_return(closes, 126),
            "1y": self._period_return(closes, 252),
        }
        direction = "insufficient_data"
        if returns.get("1mo") is not None and returns.get("3mo") is not None:
            if returns["1mo"] > 0 and returns["3mo"] > 0:
                direction = "uptrend"
            elif returns["1mo"] < 0 and returns["3mo"] < 0:
                direction = "downtrend"
            else:
                direction = "mixed"
        return {
            "returns": returns,
            "direction": direction,
            "history_points": len(closes),
            "period": history_payload.get("period") if isinstance(history_payload, dict) else None,
            "interval": history_payload.get("interval") if isinstance(history_payload, dict) else None,
        }

    def _build_momentum(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        closes = self._series(rows, "close")
        close = closes[-1] if closes else None
        sma20 = self._sma(closes, 20)
        sma50 = self._sma(closes, 50)
        rsi14 = self._rsi(closes, 14)
        macd, signal, hist = self._macd(closes)
        close_vs_sma20_pct = self._pct_diff(close, sma20)
        close_vs_sma50_pct = self._pct_diff(close, sma50)
        state = "insufficient_data"
        if close_vs_sma20_pct is not None and rsi14 is not None:
            if close_vs_sma20_pct > 0 and rsi14 >= 55:
                state = "positive"
            elif close_vs_sma20_pct < 0 and rsi14 <= 45:
                state = "negative"
            else:
                state = "mixed"
        return {
            "state": state,
            "last_close": self._round(close),
            "sma20": self._round(sma20),
            "sma50": self._round(sma50),
            "close_vs_sma20_pct": self._round(close_vs_sma20_pct),
            "close_vs_sma50_pct": self._round(close_vs_sma50_pct),
            "rsi14": self._round(rsi14),
            "macd": self._round(macd),
            "macd_signal": self._round(signal),
            "macd_hist": self._round(hist),
        }

    def _build_volume_price(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        closes = self._series(rows, "close")
        volumes = self._series(rows, "volume")
        latest_volume = volumes[-1] if volumes else None
        avg_volume20 = self._sma(volumes, 20)
        volume_ratio20 = (
            latest_volume / avg_volume20
            if latest_volume is not None and avg_volume20 not in (None, 0)
            else None
        )
        price_change_1d = self._period_return(closes, 1)
        signal = "insufficient_data"
        if price_change_1d is not None and volume_ratio20 is not None:
            if price_change_1d > 0 and volume_ratio20 >= 1.2:
                signal = "price_up_volume_confirmed"
            elif price_change_1d < 0 and volume_ratio20 >= 1.2:
                signal = "price_down_distribution"
            elif volume_ratio20 < 0.8:
                signal = "low_volume_move"
            else:
                signal = "normal_volume"
        return {
            "latest_volume": self._round(latest_volume),
            "avg_volume20": self._round(avg_volume20),
            "volume_ratio20": self._round(volume_ratio20),
            "price_change_1d": self._round(price_change_1d),
            "signal": signal,
        }

    def _build_volatility_structure(
        self,
        rows: list[dict[str, Any]],
        option_metrics: dict[str, Any],
        drawdown_summary: Any,
    ) -> dict[str, Any]:
        closes = self._series(rows, "close")
        daily_returns = self._daily_returns(closes)
        atr14 = self._atr(rows, 14)
        latest_close = closes[-1] if closes else None
        atr14_pct = (atr14 / latest_close * 100.0) if atr14 is not None and latest_close else None
        options = self._normalize_option_metrics(option_metrics)
        return {
            "realized_volatility": {
                "20d": self._round(self._annualized_volatility(daily_returns[-20:])),
                "60d": self._round(self._annualized_volatility(daily_returns[-60:])),
            },
            "atr14": self._round(atr14),
            "atr14_pct": self._round(atr14_pct),
            "max_drawdown": self._round(self._max_drawdown(closes)),
            "drawdown_from_high": self._round(self._drawdown_from_high(closes)),
            "option_iv_atm": options.get("iv_atm"),
            "option_iv_skew_25d": options.get("iv_skew_25d"),
            "option_put_call_ratio": options.get("put_call_ratio"),
            "drawdown_summary": drawdown_summary if isinstance(drawdown_summary, str) else None,
        }

    def _build_key_levels(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        closes = self._series(rows, "close")
        highs = self._series(rows, "high")
        lows = self._series(rows, "low")
        latest_close = closes[-1] if closes else None
        support_20d = min(lows[-20:]) if len(lows) >= 1 else None
        resistance_20d = max(highs[-20:]) if len(highs) >= 1 else None
        support_60d = min(lows[-60:]) if len(lows) >= 1 else None
        resistance_60d = max(highs[-60:]) if len(highs) >= 1 else None
        high_52w = max(highs[-252:]) if highs else None
        low_52w = min(lows[-252:]) if lows else None
        return {
            "last_close": self._round(latest_close),
            "support_20d": self._round(support_20d),
            "resistance_20d": self._round(resistance_20d),
            "support_60d": self._round(support_60d),
            "resistance_60d": self._round(resistance_60d),
            "high_52w": self._round(high_52w),
            "low_52w": self._round(low_52w),
            "distance_to_support_20d_pct": self._round(self._pct_diff(latest_close, support_20d)),
            "distance_to_resistance_20d_pct": self._round(self._pct_diff(latest_close, resistance_20d)),
        }

    def _build_relative_strength(
        self,
        history_payload: dict[str, Any],
        benchmark_histories: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        target_closes = self._series(self._extract_kline_rows(history_payload), "close")
        target_returns = {
            "1mo": self._period_return(target_closes, 21),
            "3mo": self._period_return(target_closes, 63),
        }
        benchmarks: dict[str, Any] = {}
        for benchmark, payload in benchmark_histories.items():
            benchmark_closes = self._series(self._extract_kline_rows(payload), "close")
            benchmark_returns = {
                "1mo": self._period_return(benchmark_closes, 21),
                "3mo": self._period_return(benchmark_closes, 63),
            }
            benchmarks[benchmark] = {
                "ticker_returns": target_returns,
                "benchmark_returns": benchmark_returns,
                "rs_1mo": self._round(self._subtract(target_returns.get("1mo"), benchmark_returns.get("1mo"))),
                "rs_3mo": self._round(self._subtract(target_returns.get("3mo"), benchmark_returns.get("3mo"))),
            }
        return {
            "benchmarks": benchmarks,
            "peer_relative_strength": None,
            "todo": "TODO: 当前没有同行自动发现/同行历史价批量工具，暂只计算 SPY/QQQ benchmark RS。",
        }

    def _missing_tool_todos(self) -> list[str]:
        todos = [
            "TODO: 缺少同行自动发现与同行 RS 工具，当前仅用 SPY/QQQ 做 benchmark 相对强弱。",
            "TODO: get_option_chain_metrics 未提供 IV rank 与完整 term structure，当前只保留 ATM IV/PCR/Skew。",
            "TODO: 缺少专门价格异动事件归因工具，当前仅在大幅波动时用 search 兜底。",
        ]
        if not callable(getattr(self.tools, "get_stock_historical_data", None)):
            todos.append("TODO: 缺少 get_stock_historical_data，无法构建趋势/动量/量价/ATR/回撤 snapshot。")
        return todos

    def _series(self, rows: list[dict[str, Any]], key: str) -> list[float]:
        values = []
        for row in rows:
            value = self._safe_float(row.get(key))
            if value is not None:
                values.append(value)
        return values

    def _period_return(self, values: list[float], lookback: int) -> Optional[float]:
        if len(values) < 2:
            return None
        if len(values) <= lookback:
            start = values[0]
        else:
            start = values[-lookback - 1]
        end = values[-1]
        if start in (None, 0):
            return None
        return self._round((end - start) / start * 100.0)

    def _sma(self, values: list[float], window: int) -> Optional[float]:
        if len(values) < window:
            return None
        return sum(values[-window:]) / float(window)

    def _rsi(self, values: list[float], window: int) -> Optional[float]:
        if len(values) < window + 1:
            return None
        changes = [values[i] - values[i - 1] for i in range(1, len(values))]
        recent = changes[-window:]
        gains = [change for change in recent if change > 0]
        losses = [-change for change in recent if change < 0]
        avg_gain = sum(gains) / float(window)
        avg_loss = sum(losses) / float(window)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _macd(self, values: list[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
        if len(values) < 35:
            return None, None, None
        ema12 = self._ema(values, 12)
        ema26 = self._ema(values, 26)
        if not ema12 or not ema26:
            return None, None, None
        macd_series = [short - long for short, long in zip(ema12[-len(ema26):], ema26)]
        signal_series = self._ema(macd_series, 9)
        if not signal_series:
            return None, None, None
        macd = macd_series[-1]
        signal = signal_series[-1]
        return macd, signal, macd - signal

    def _ema(self, values: list[float], span: int) -> list[float]:
        if not values:
            return []
        alpha = 2.0 / (span + 1.0)
        ema_values = [values[0]]
        for value in values[1:]:
            ema_values.append((value * alpha) + (ema_values[-1] * (1.0 - alpha)))
        return ema_values

    def _daily_returns(self, closes: list[float]) -> list[float]:
        returns = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            if prev:
                returns.append((closes[i] - prev) / prev)
        return returns

    def _annualized_volatility(self, returns: list[float]) -> Optional[float]:
        if len(returns) < 2:
            return None
        mean = sum(returns) / float(len(returns))
        variance = sum((item - mean) ** 2 for item in returns) / float(len(returns) - 1)
        return sqrt(variance) * sqrt(252.0) * 100.0

    def _atr(self, rows: list[dict[str, Any]], window: int) -> Optional[float]:
        if len(rows) < window + 1:
            return None
        true_ranges = []
        for index in range(1, len(rows)):
            high = self._safe_float(rows[index].get("high"))
            low = self._safe_float(rows[index].get("low"))
            prev_close = self._safe_float(rows[index - 1].get("close"))
            if high is None or low is None or prev_close is None:
                continue
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        if len(true_ranges) < window:
            return None
        return sum(true_ranges[-window:]) / float(window)

    def _max_drawdown(self, closes: list[float]) -> Optional[float]:
        if len(closes) < 2:
            return None
        peak = closes[0]
        max_drawdown = 0.0
        for close in closes:
            if close > peak:
                peak = close
            if peak:
                drawdown = (close - peak) / peak * 100.0
                if drawdown < max_drawdown:
                    max_drawdown = drawdown
        return max_drawdown

    def _drawdown_from_high(self, closes: list[float]) -> Optional[float]:
        if not closes:
            return None
        high = max(closes)
        if not high:
            return None
        return (closes[-1] - high) / high * 100.0

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace("$", "").replace(",", "").replace("%", "")
            if not cleaned:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    def _round(self, value: Optional[float], digits: int = 4) -> Optional[float]:
        if value is None:
            return None
        return round(float(value), digits)

    def _pct_diff(self, current: Optional[float], base: Optional[float]) -> Optional[float]:
        if current is None or base in (None, 0):
            return None
        return (current - base) / base * 100.0

    def _subtract(self, left: Optional[float], right: Optional[float]) -> Optional[float]:
        if left is None or right is None:
            return None
        return left - right

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
        if isinstance(data, dict) and data.get("snapshot_type") == "PriceBehaviorSnapshot":
            return deterministic
        analysis = await self._llm_analyze(
            deterministic,
            role="资深量化交易分析师",
            focus="解读当前价格与日内变动，并结合期权IV/PCR/Skew判断短线风险偏好和交易拥挤度。",
        )
        return analysis if analysis else deterministic

    def _deterministic_summary(self, data: Any) -> str:
        """Build a human-readable price snapshot from raw data (fallback)."""
        if isinstance(data, dict):
            if data.get("snapshot_type") == "PriceBehaviorSnapshot":
                ticker = data.get("ticker", "N/A")
                quote = data.get("quote") if isinstance(data.get("quote"), dict) else {}
                price = quote.get("price", data.get("price"))
                currency = quote.get("currency", data.get("currency", "USD"))
                change = quote.get("change", data.get("change"))
                change_pct = quote.get("change_percent", data.get("change_percent"))
                trend = data.get("trend") if isinstance(data.get("trend"), dict) else {}
                returns = trend.get("returns") if isinstance(trend.get("returns"), dict) else {}
                momentum = data.get("momentum") if isinstance(data.get("momentum"), dict) else {}
                volume_price = data.get("volume_price") if isinstance(data.get("volume_price"), dict) else {}
                relative_strength = data.get("relative_strength") if isinstance(data.get("relative_strength"), dict) else {}
                benchmarks = relative_strength.get("benchmarks") if isinstance(relative_strength.get("benchmarks"), dict) else {}
                volatility = data.get("volatility_structure") if isinstance(data.get("volatility_structure"), dict) else {}
                key_levels = data.get("key_levels") if isinstance(data.get("key_levels"), dict) else {}
                options = data.get("options") if isinstance(data.get("options"), dict) else {}

                def fmt_num(value: Any, digits: int = 2) -> Optional[str]:
                    parsed = self._safe_float(value)
                    if parsed is None:
                        return None
                    return f"{parsed:.{digits}f}"

                def fmt_pct(value: Any, *, signed: bool = True) -> Optional[str]:
                    parsed = self._safe_float(value)
                    if parsed is None:
                        return None
                    prefix = "+" if signed else ""
                    return f"{parsed:{prefix}.2f}%"

                def fmt_decimal_pct(value: Any, *, signed: bool = False) -> Optional[str]:
                    parsed = self._safe_float(value)
                    if parsed is None:
                        return None
                    prefix = "+" if signed else ""
                    return f"{parsed:{prefix}.2%}"

                def add_section(sections: list[str], heading: str, bits: list[str]) -> None:
                    clean_bits = [bit for bit in bits if bit]
                    if clean_bits:
                        sections.append(f"【{heading}】" + "；".join(clean_bits) + "。")

                sections: list[str] = []

                price_bits = []
                if price is not None:
                    price_bits.append(f"{ticker} 当前价格: {currency} {price}")
                else:
                    price_bits.append(f"{ticker} 当前价格暂缺")
                pct_text = fmt_pct(change_pct)
                if pct_text:
                    pct = self._safe_float(change_pct)
                    direction = "上涨" if pct is not None and pct >= 0 else "下跌"
                    change_text = fmt_num(change)
                    if change_text:
                        price_bits.append(f"日内{direction} {pct_text}（变动 {change_text}）")
                    else:
                        price_bits.append(f"日内{direction} {pct_text}")
                if quote.get("source"):
                    price_bits.append(f"来源 {quote.get('source')}")
                if quote.get("as_of") or data.get("as_of"):
                    price_bits.append(f"时间 {quote.get('as_of') or data.get('as_of')}")
                add_section(sections, "价格状态", price_bits)

                trend_bits = []
                return_bits = []
                for label in ("1d", "1w", "1mo", "3mo", "6mo", "1y"):
                    pct = fmt_pct(returns.get(label))
                    if pct:
                        return_bits.append(f"{label} {pct}")
                if return_bits:
                    trend_bits.append("区间收益 " + " / ".join(return_bits))
                if trend.get("direction"):
                    trend_bits.append(f"趋势方向 {trend.get('direction')}")
                if momentum.get("state"):
                    trend_bits.append(f"动量状态 {momentum.get('state')}")
                sma20_gap = fmt_pct(momentum.get("close_vs_sma20_pct"))
                if sma20_gap:
                    trend_bits.append(f"相对SMA20 {sma20_gap}")
                sma50_gap = fmt_pct(momentum.get("close_vs_sma50_pct"))
                if sma50_gap:
                    trend_bits.append(f"相对SMA50 {sma50_gap}")
                add_section(sections, "趋势与动量", trend_bits)

                volume_bits = []
                price_change_1d = fmt_pct(volume_price.get("price_change_1d"))
                if price_change_1d:
                    volume_bits.append(f"1日价格变动 {price_change_1d}")
                ratio = fmt_num(volume_price.get("volume_ratio20"))
                if ratio:
                    volume_bits.append(f"成交量为20日均量 {ratio}x")
                latest_volume = fmt_num(volume_price.get("latest_volume"), digits=0)
                avg_volume20 = fmt_num(volume_price.get("avg_volume20"), digits=0)
                if latest_volume:
                    volume_bits.append(f"最新成交量 {latest_volume}")
                if avg_volume20:
                    volume_bits.append(f"20日均量 {avg_volume20}")
                if volume_price.get("signal"):
                    volume_bits.append(f"量价信号 {volume_price.get('signal')}")
                add_section(sections, "量价关系", volume_bits)

                rs_bits = []
                for benchmark in ("SPY", "QQQ"):
                    payload = benchmarks.get(benchmark) if isinstance(benchmarks.get(benchmark), dict) else {}
                    rs_1mo = fmt_pct(payload.get("rs_1mo"))
                    rs_3mo = fmt_pct(payload.get("rs_3mo"))
                    parts = []
                    if rs_1mo:
                        parts.append(f"1mo {rs_1mo.replace('%', 'pct')}")
                    if rs_3mo:
                        parts.append(f"3mo {rs_3mo.replace('%', 'pct')}")
                    if parts:
                        rs_bits.append(f"{benchmark}: " + " / ".join(parts))
                peer_rs = relative_strength.get("peer_relative_strength")
                if peer_rs:
                    rs_bits.append(f"同行RS {peer_rs}")
                add_section(sections, "相对强弱RS", rs_bits)

                vol_bits = []
                realized_vol = volatility.get("realized_volatility") if isinstance(volatility.get("realized_volatility"), dict) else {}
                for label in ("20d", "60d"):
                    value = fmt_pct(realized_vol.get(label), signed=False)
                    if value:
                        vol_bits.append(f"实现波动率{label} {value}")
                atr_pct = fmt_pct(volatility.get("atr14_pct"), signed=False)
                if atr_pct:
                    vol_bits.append(f"ATR14 {atr_pct}")
                max_drawdown = fmt_pct(volatility.get("max_drawdown"))
                if max_drawdown:
                    vol_bits.append(f"最大回撤 {max_drawdown}")
                drawdown_from_high = fmt_pct(volatility.get("drawdown_from_high"))
                if drawdown_from_high:
                    vol_bits.append(f"距高点回撤 {drawdown_from_high}")
                iv = fmt_decimal_pct(options.get("iv_atm"), signed=False)
                if iv:
                    vol_bits.append(f"ATM IV {iv}")
                pcr = fmt_num(options.get("put_call_ratio"))
                if pcr:
                    vol_bits.append(f"PCR {pcr}")
                skew = fmt_decimal_pct(options.get("iv_skew_25d"), signed=True)
                if skew:
                    vol_bits.append(f"25D Skew {skew}")
                add_section(sections, "波动率与期权结构", vol_bits)

                level_bits = []
                for label, cn_label in (
                    ("support_20d", "20日支撑"),
                    ("resistance_20d", "20日压力"),
                    ("support_60d", "60日支撑"),
                    ("resistance_60d", "60日压力"),
                    ("high_52w", "52周高点"),
                    ("low_52w", "52周低点"),
                ):
                    value = fmt_num(key_levels.get(label))
                    if value:
                        level_bits.append(f"{cn_label} {value}")
                distance_support = fmt_pct(key_levels.get("distance_to_support_20d_pct"))
                if distance_support:
                    level_bits.append(f"距20日支撑 {distance_support}")
                distance_resistance = fmt_pct(key_levels.get("distance_to_resistance_20d_pct"))
                if distance_resistance:
                    level_bits.append(f"距20日压力 {distance_resistance}")
                add_section(sections, "关键价位", level_bits)

                add_section(sections, "风险提示", self._build_snapshot_risks(data))
                return "\n".join(sections) if sections else str(data)

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

    def _build_snapshot_risks(self, raw_data: dict[str, Any]) -> list[str]:
        risks: list[str] = []
        if raw_data.get("fallback_used"):
            reason = raw_data.get("fallback_reason") or "primary_source_unavailable"
            risks.append(f"价格数据使用兜底路径，原因: {reason}")

        volume_price = raw_data.get("volume_price") if isinstance(raw_data.get("volume_price"), dict) else {}
        volume_signal = str(volume_price.get("signal") or "")
        volume_ratio = self._safe_float(volume_price.get("volume_ratio20"))
        if volume_signal == "price_down_distribution":
            ratio_text = f"{volume_ratio:.2f}x" if volume_ratio is not None else "高于均量"
            risks.append(f"放量下跌信号，成交量约为20日均量 {ratio_text}")
        elif volume_signal == "low_volume_move":
            ratio_text = f"{volume_ratio:.2f}x" if volume_ratio is not None else "低于均量"
            risks.append(f"价格变动缺少量能确认，成交量约为20日均量 {ratio_text}")

        volatility = raw_data.get("volatility_structure") if isinstance(raw_data.get("volatility_structure"), dict) else {}
        atr_pct = self._safe_float(volatility.get("atr14_pct"))
        if atr_pct is not None and atr_pct >= 4:
            risks.append(f"ATR14 达 {atr_pct:.2f}%，短线波动风险偏高")
        drawdown_from_high = self._safe_float(volatility.get("drawdown_from_high"))
        if drawdown_from_high is not None and drawdown_from_high <= -8:
            risks.append(f"当前较阶段高点回撤 {drawdown_from_high:+.2f}%，趋势修复仍需确认")
        max_drawdown = self._safe_float(volatility.get("max_drawdown"))
        if max_drawdown is not None and max_drawdown <= -20:
            risks.append(f"历史区间最大回撤 {max_drawdown:+.2f}%，下行尾部风险不可忽视")

        options = raw_data.get("options") if isinstance(raw_data.get("options"), dict) else {}
        pcr = self._safe_float(options.get("put_call_ratio"))
        if pcr is not None and pcr >= 1.2:
            risks.append(f"Put/Call Ratio {pcr:.2f} 偏高，期权端防守需求较强")
        skew = self._safe_float(options.get("iv_skew_25d"))
        if skew is not None and skew < -0.03:
            risks.append(f"25D Skew {skew:+.2%} 偏负，左尾保护溢价上升")

        key_levels = raw_data.get("key_levels") if isinstance(raw_data.get("key_levels"), dict) else {}
        distance_support = self._safe_float(key_levels.get("distance_to_support_20d_pct"))
        if distance_support is not None and 0 <= distance_support <= 3:
            risks.append(f"价格距20日支撑仅 {distance_support:+.2f}%，跌破后可能触发止损压力")
        distance_resistance = self._safe_float(key_levels.get("distance_to_resistance_20d_pct"))
        if distance_resistance is not None and -3 <= distance_resistance <= 0:
            risks.append(f"价格距20日压力 {distance_resistance:+.2f}%，上攻失败可能形成短线抛压")

        event = raw_data.get("event_explanation") if isinstance(raw_data.get("event_explanation"), dict) else {}
        if event.get("summary"):
            risks.append(f"价格异动需结合事件验证: {str(event.get('summary'))[:180]}")
        elif event.get("todo"):
            risks.append(str(event.get("todo")))

        return risks

    def _build_native_claims(
        self,
        *,
        raw_data: dict[str, Any],
        evidence: list[EvidenceItem],
        confidence: float,
    ) -> list[dict[str, Any]]:
        ticker = str(raw_data.get("ticker") or self._current_ticker or "").strip().upper()
        query = self._current_query or ""
        if not ticker:
            return []

        evidence_by_metric = {
            str((item.meta or {}).get("metric_key") or ""): str((item.meta or {}).get("source_id") or "")
            for item in evidence
            if str((item.meta or {}).get("metric_key") or "") and str((item.meta or {}).get("source_id") or "")
        }

        def evidence_id(metric_key: str) -> Optional[str]:
            value = evidence_by_metric.get(metric_key)
            return value if value else None

        def fmt_pct(value: Any) -> str:
            parsed = self._safe_float(value)
            return f"{parsed:+.2f}%" if parsed is not None else "暂无数据"

        claims: list[dict[str, Any]] = []
        trend = raw_data.get("trend") if isinstance(raw_data.get("trend"), dict) else {}
        returns = trend.get("returns") if isinstance(trend.get("returns"), dict) else {}
        momentum = raw_data.get("momentum") if isinstance(raw_data.get("momentum"), dict) else {}
        momentum_source = evidence_id("price_momentum")
        if momentum_source:
            one_month = self._safe_float(returns.get("1mo"))
            three_month = self._safe_float(returns.get("3mo"))
            state = str(momentum.get("state") or trend.get("direction") or "mixed")
            if (one_month is not None and one_month > 0) and (three_month is None or three_month >= 0):
                stance = "bull"
                direction = "positive"
            elif (one_month is not None and one_month < 0) and (three_month is None or three_month <= 0):
                stance = "bear"
                direction = "negative"
            else:
                stance = "neutral"
                direction = state
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=(
                        f"{ticker} 价格动量{_price_direction_cn(direction)}："
                        f"近 1 月 {fmt_pct(one_month)}，近 3 月 {fmt_pct(three_month)}，状态 {_price_direction_cn(state)}。"
                    ),
                    evidence_ids=[momentum_source],
                    stance=stance,
                    confidence=confidence,
                    limitations=["价格动量基于历史收益率，不应视为预测。"],
                    metadata={"claim_type": "price_momentum"},
                )
            )

        relative_strength = raw_data.get("relative_strength") if isinstance(raw_data.get("relative_strength"), dict) else {}
        benchmarks = relative_strength.get("benchmarks") if isinstance(relative_strength.get("benchmarks"), dict) else {}
        rs_source = evidence_id("relative_strength")
        if rs_source and benchmarks:
            benchmark_name = "SPY" if isinstance(benchmarks.get("SPY"), dict) else next(iter(benchmarks))
            benchmark = benchmarks.get(benchmark_name) if isinstance(benchmarks.get(benchmark_name), dict) else {}
            rs_1mo = self._safe_float(benchmark.get("rs_1mo"))
            rs_3mo = self._safe_float(benchmark.get("rs_3mo"))
            stance = "bull" if rs_1mo is not None and rs_1mo > 0 else ("bear" if rs_1mo is not None and rs_1mo < 0 else "neutral")
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=(
                        f"{ticker} 相对 {benchmark_name} 的相对强度："
                        f"近 1 月 {fmt_pct(rs_1mo)}，近 3 月 {fmt_pct(rs_3mo)}。"
                    ),
                    evidence_ids=[rs_source],
                    stance=stance,
                    confidence=confidence,
                    limitations=["相对强度当前基于基准 ETF，同业相对强度需要单独的同业样本集。"],
                    metadata={"claim_type": "relative_strength", "benchmark": benchmark_name},
                )
            )

        volume_price = raw_data.get("volume_price") if isinstance(raw_data.get("volume_price"), dict) else {}
        volume_source = evidence_id("volume_confirmation")
        if volume_source:
            signal = str(volume_price.get("signal") or "available")
            ratio = self._safe_float(volume_price.get("volume_ratio20"))
            if signal == "price_up_volume_confirmed":
                stance = "bull"
            elif signal == "price_down_distribution":
                stance = "bear"
            elif signal == "low_volume_move":
                stance = "neutral"
            else:
                stance = "neutral"
            ratio_text = f"{ratio:.2f}x" if ratio is not None else "暂无数据"
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=f"{ticker} 量价确认为{_volume_signal_cn(signal)}；最新成交量为 20 日均量的 {ratio_text}。",
                    evidence_ids=[volume_source],
                    stance=stance,
                    confidence=confidence,
                    limitations=["量价确认是短周期行为信号，可能快速反转。"],
                    metadata={"claim_type": "volume_confirmation", "signal": signal},
                )
            )

        volatility = raw_data.get("volatility_structure") if isinstance(raw_data.get("volatility_structure"), dict) else {}
        options = raw_data.get("options") if isinstance(raw_data.get("options"), dict) else {}
        vol_source = evidence_id("volatility_regime")
        if vol_source:
            atr_pct = self._safe_float(volatility.get("atr14_pct"))
            iv_atm = self._safe_float(options.get("iv_atm") if options else volatility.get("option_iv_atm"))
            pcr = self._safe_float(options.get("put_call_ratio") if options else volatility.get("option_put_call_ratio"))
            stance = "risk" if (atr_pct is not None and atr_pct >= 4) or (iv_atm is not None and iv_atm >= 0.45) else "neutral"
            iv_text = f"{iv_atm:.2%}" if iv_atm is not None else "暂无数据"
            pcr_text = f"{pcr:.2f}" if pcr is not None else "暂无数据"
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=f"{ticker} 波动率状态显示 ATR14 {fmt_pct(atr_pct)}，ATM IV {iv_text}，PCR {pcr_text}。",
                    evidence_ids=[vol_source],
                    stance=stance,
                    confidence=confidence,
                    limitations=["当工具未提供时，期权字段可能缺失 IV rank 与完整期限结构。"],
                    metadata={"claim_type": "volatility_regime"},
                )
            )

        key_levels = raw_data.get("key_levels") if isinstance(raw_data.get("key_levels"), dict) else {}
        level_source = evidence_id("key_level_risk")
        if level_source:
            support = self._safe_float(key_levels.get("support_20d"))
            resistance = self._safe_float(key_levels.get("resistance_20d"))
            distance_support = self._safe_float(key_levels.get("distance_to_support_20d_pct"))
            distance_resistance = self._safe_float(key_levels.get("distance_to_resistance_20d_pct"))
            near_support = distance_support is not None and 0 <= distance_support <= 3
            near_resistance = distance_resistance is not None and -3 <= distance_resistance <= 0
            stance = "risk" if near_support or near_resistance else "neutral"
            support_text = f"{support:.2f}" if support is not None else "数据已获取"
            resistance_text = f"{resistance:.2f}" if resistance is not None else "数据已获取"
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=(
                        f"{ticker} 关键价位风险集中于 20 日支撑 {support_text} "
                        f"与 20 日压力 {resistance_text}。"
                    ),
                    evidence_ids=[level_source],
                    stance=stance,
                    confidence=confidence,
                    limitations=["关键价位由近期价格区间推导，并非完整技术形态模型。"],
                    metadata={
                        "claim_type": "key_level_risk",
                        "distance_to_support_20d_pct": distance_support,
                        "distance_to_resistance_20d_pct": distance_resistance,
                    },
                )
            )

        return claims

    def _resolve_tool_fallback(
        self,
        ticker: str,
        *,
        fallback_used: bool,
        fallback_reason: Optional[str],
    ) -> tuple[bool, Optional[str]]:
        """查询 tool 层（get_stock_price）最近一次取数的降级信息，传播到 AgentOutput。

        当 tool 层用了非首选源（is_degraded=True 且 source 非 None）时，置 fallback_used=True，
        并补充降级原因。若 AgentOutput 已因其他原因带有 fallback_reason，则保留已有原因（已有优先）。
        """
        get_info = getattr(self.tools, "get_last_fetch_info", None) if self.tools else None
        if not callable(get_info) or not ticker:
            return fallback_used, fallback_reason
        try:
            info = get_info(ticker)
        except Exception:
            return fallback_used, fallback_reason
        if not isinstance(info, dict):
            return fallback_used, fallback_reason

        source = info.get("source")
        if info.get("is_degraded") and source:
            attempt = info.get("attempt")
            tool_reason = f"主数据源不可用，已降级到备用源 {source}（第{attempt}优先级）"
            # 已有 fallback_reason 优先，不覆盖
            return True, fallback_reason or tool_reason
        return fallback_used, fallback_reason

    def _format_snapshot_output(self, summary: str, raw_data: dict[str, Any]) -> AgentOutput:
        quote = raw_data.get("quote") if isinstance(raw_data.get("quote"), dict) else {}
        source = str(quote.get("source") or raw_data.get("source") or "price_behavior_snapshot")
        as_of = str(quote.get("as_of") or raw_data.get("as_of") or datetime.now().isoformat())
        fallback_used = bool(raw_data.get("fallback_used"))
        data_sources = list(raw_data.get("data_sources") or raw_data.get("sources") or [source])
        if source not in data_sources:
            data_sources.insert(0, source)
        ticker = str(raw_data.get("ticker") or quote.get("ticker") or self._current_ticker or "").strip().upper()
        summary_text = self._deterministic_summary(raw_data) or summary

        evidence: list[EvidenceItem] = []

        def add_source(source_name: str) -> None:
            if source_name and source_name not in data_sources:
                data_sources.append(source_name)

        def add_evidence(
            *,
            metric_key: str,
            text: str,
            source_name: str,
            meta: dict[str, Any],
            timestamp: str = as_of,
            include_data_source: bool = True,
        ) -> None:
            if not text:
                return
            payload = dict(meta)
            payload["metric_key"] = metric_key
            payload.setdefault("ticker", ticker)
            payload.setdefault("as_of", timestamp)
            evidence.append(
                EvidenceItem(
                    text=text,
                    source=source_name,
                    timestamp=timestamp,
                    meta=payload,
                )
            )
            if include_data_source:
                add_source(source_name)

        add_evidence(
            metric_key="price_behavior_snapshot",
            text=f"PriceBehaviorSnapshot for {ticker or raw_data.get('ticker', 'UNKNOWN')}",
            source_name="price_behavior_snapshot",
            meta={
                "snapshot_type": raw_data.get("snapshot_type"),
                "snapshot": raw_data,
            },
            include_data_source=False,
        )

        price = quote.get("price", raw_data.get("price"))
        currency = quote.get("currency", raw_data.get("currency", "USD"))
        change_pct = quote.get("change_percent", raw_data.get("change_percent"))
        quote_bits = [f"Current quote: {currency} {price}" if price is not None else "Current quote unavailable"]
        if change_pct is not None:
            try:
                quote_bits.append(f"intraday {float(change_pct):+.2f}%")
            except Exception:
                pass
        add_evidence(
            metric_key="price_quote",
            text=", ".join(quote_bits),
            source_name=source,
            meta=quote or {"price": price, "currency": currency, "change_percent": change_pct},
        )

        trend = raw_data.get("trend") if isinstance(raw_data.get("trend"), dict) else {}
        momentum = raw_data.get("momentum") if isinstance(raw_data.get("momentum"), dict) else {}
        volume_price = raw_data.get("volume_price") if isinstance(raw_data.get("volume_price"), dict) else {}
        relative_strength = raw_data.get("relative_strength") if isinstance(raw_data.get("relative_strength"), dict) else {}
        volatility = raw_data.get("volatility_structure") if isinstance(raw_data.get("volatility_structure"), dict) else {}
        key_levels = raw_data.get("key_levels") if isinstance(raw_data.get("key_levels"), dict) else {}

        trend_bits = []
        returns = trend.get("returns") if isinstance(trend.get("returns"), dict) else {}
        for label in ("1w", "1mo", "3mo", "6mo", "1y"):
            value = returns.get(label)
            if value is not None:
                trend_bits.append(f"{label} {float(value):+.2f}%")
        if trend_bits:
            momentum_meta = {
                "trend": trend,
                "momentum": momentum,
            }
            add_evidence(
                metric_key="price_momentum",
                text="Price momentum: " + ", ".join(trend_bits),
                source_name="price_history",
                meta=momentum_meta,
                include_data_source=False,
            )

        volume_has_values = any(
            volume_price.get(key) is not None
            for key in ("latest_volume", "avg_volume20", "volume_ratio20", "price_change_1d")
        )
        if volume_has_values:
            add_evidence(
                metric_key="volume_confirmation",
                text=(
                    f"Volume-price: latest={volume_price.get('latest_volume')}, "
                    f"avg20={volume_price.get('avg_volume20')}, "
                    f"ratio20={volume_price.get('volume_ratio20')}, "
                    f"signal={volume_price.get('signal')}"
                ),
                source_name="price_history",
                meta=volume_price,
                include_data_source=False,
            )

        benchmarks = relative_strength.get("benchmarks") if isinstance(relative_strength.get("benchmarks"), dict) else {}
        if benchmarks:
            add_evidence(
                metric_key="relative_strength",
                text=f"Relative strength vs benchmarks: {benchmarks}",
                source_name="benchmark_history",
                meta=relative_strength,
            )

        option_metrics = raw_data.get("options") if isinstance(raw_data.get("options"), dict) else {}
        realized_vol = volatility.get("realized_volatility") if isinstance(volatility.get("realized_volatility"), dict) else {}
        volatility_has_values = any(realized_vol.get(key) is not None for key in ("20d", "60d")) or any(
            volatility.get(key) is not None
            for key in (
                "atr14",
                "atr14_pct",
                "max_drawdown",
                "drawdown_from_high",
                "option_iv_atm",
                "option_iv_skew_25d",
                "option_put_call_ratio",
            )
        )
        if volatility_has_values or option_metrics:
            option_bits = []
            if option_metrics.get("iv_atm") is not None:
                option_bits.append(f"ATM IV {float(option_metrics['iv_atm']):.2%}")
            if option_metrics.get("put_call_ratio") is not None:
                option_bits.append(f"PCR {float(option_metrics['put_call_ratio']):.2f}")
            if option_metrics.get("iv_skew_25d") is not None:
                option_bits.append(f"Skew {float(option_metrics['iv_skew_25d']):+.2%}")
            add_evidence(
                metric_key="volatility_regime",
                text=(
                    f"Volatility regime: ATR14={volatility.get('atr14')}, "
                    f"ATR14%={volatility.get('atr14_pct')}, "
                    f"max_drawdown={volatility.get('max_drawdown')}, "
                    f"options={', '.join(option_bits) if option_bits else 'available'}"
                ),
                source_name=str(option_metrics.get("source") or "price_history"),
                timestamp=str(option_metrics.get("as_of") or as_of),
                meta={"volatility_structure": volatility, "options": option_metrics},
                include_data_source=bool(option_metrics),
            )

        key_level_has_values = any(
            key_levels.get(key) is not None
            for key in (
                "support_20d",
                "resistance_20d",
                "support_60d",
                "resistance_60d",
                "high_52w",
                "low_52w",
                "distance_to_support_20d_pct",
                "distance_to_resistance_20d_pct",
            )
        )
        if key_level_has_values:
            add_evidence(
                metric_key="key_level_risk",
                text=(
                    f"Key levels: support20={key_levels.get('support_20d')}, "
                    f"resistance20={key_levels.get('resistance_20d')}, "
                    f"distance_support20={key_levels.get('distance_to_support_20d_pct')}, "
                    f"distance_resistance20={key_levels.get('distance_to_resistance_20d_pct')}"
                ),
                source_name="price_history",
                meta=key_levels,
                include_data_source=False,
            )

        if option_metrics:
            option_source = str(option_metrics.get("source") or "options")
            add_source(option_source)

        event = raw_data.get("event_explanation") if isinstance(raw_data.get("event_explanation"), dict) else {}
        if event:
            add_evidence(
                metric_key="event_price_mapping",
                text=f"Event-price mapping: {event.get('summary') or event.get('todo') or event}",
                source_name=str(event.get("source") or "event_price_mapping"),
                meta=event,
            )

        fallback_reason = raw_data.get("fallback_reason") if fallback_used else None
        # 传播 tool 层（get_stock_price）多源降级信息（已有 reason 优先）
        fallback_used, fallback_reason = self._resolve_tool_fallback(
            ticker, fallback_used=fallback_used, fallback_reason=fallback_reason
        )
        confidence = 1.0 if not fallback_used else 0.5
        assign_evidence_source_ids(evidence, agent_name=self.AGENT_NAME)
        claims = self._build_native_claims(raw_data=raw_data, evidence=evidence, confidence=confidence)
        risks = self._build_snapshot_risks(raw_data)

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary_text,
            evidence=evidence,
            confidence=confidence,
            data_sources=list(dict.fromkeys(data_sources)),
            as_of=as_of,
            claims=claims,
            chart_specs=build_price_behavior_chart_specs(raw_data),
            fallback_used=fallback_used,
            risks=risks,
            fallback_reason=str(fallback_reason) if fallback_reason else None,
            retryable=True,
        )

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        if isinstance(raw_data, dict) and raw_data.get("snapshot_type") == "PriceBehaviorSnapshot":
            return self._format_snapshot_output(summary, raw_data)

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
            if isinstance(summary, str) and summary.strip():
                summary_text = summary.strip()
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

        # 传播 tool 层（get_stock_price）多源降级信息（已有 reason 优先）
        fallback_ticker = str(
            (raw_data.get("ticker") if isinstance(raw_data, dict) else None)
            or self._current_ticker
            or ""
        ).strip().upper()
        fallback_used, fallback_reason = self._resolve_tool_fallback(
            fallback_ticker, fallback_used=fallback_used, fallback_reason=fallback_reason
        )

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
