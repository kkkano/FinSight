from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, ConflictClaim, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker


class TechnicalAgent(BaseFinancialAgent):
    AGENT_NAME = "technical"
    CACHE_TTL = 1800  # 30 minutes
    MIN_POINTS = 30
    MAX_REFLECTIONS = 1  # Signal Confluence: one reflection to re-check pattern interpretation

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    def _get_tool_registry(self) -> dict:
        """TechnicalAgent tool registry: K-line data + search for confluence reflection."""
        registry = {}
        tools = self.tools
        if not tools:
            return registry
        search_fn = getattr(tools, "search", None)
        if search_fn:
            registry["search"] = {
                "func": search_fn,
                "description": "搜索技术分析观点、形态解读",
                "call_with": "query",
            }
        kline_fn = getattr(tools, "get_stock_historical_data", None)
        if kline_fn:
            registry["get_stock_historical_data"] = {
                "func": lambda ticker: kline_fn(ticker, period="6mo", interval="1d"),
                "description": "获取K线历史数据(ticker)，用于计算技术指标",
                "call_with": "ticker",
            }
        return registry

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        cache_key = f"{ticker}:technical:kline"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        fetch = getattr(self.tools, "get_stock_historical_data", None)
        if not fetch:
            return {"error": "missing_kline_tool", "ticker": ticker}

        data = fetch(ticker, period="6mo", interval="1d")
        if isinstance(data, dict):
            data.setdefault("ticker", ticker)
            if data.get("kline_data"):
                self.cache.set(cache_key, data, self.CACHE_TTL)
        return data

    async def _first_summary(self, data: Any) -> str:
        deterministic = self._deterministic_summary(data)
        if not isinstance(data, dict) or not data.get("kline_data"):
            return deterministic

        analysis = await self._llm_analyze(
            deterministic,
            role="资深技术分析师（信号共振分析模式）",
            focus=(
                "从多维度技术信号进行共振分析：\n"
                "1. 趋势判断：均线排列（MA20/50/200）暗示的中短期方向，价格与均线的偏离程度\n"
                "2. 动量评估：RSI 位置与 MACD 方向是否一致？是否存在动量背离信号？\n"
                "3. 关键价位：基于均线和近期走势，识别关键支撑位和压力位\n"
                "4. 信号共振：多个指标是否指向同一方向？共振强度如何？\n"
                "5. 交易含义：当前技术格局对短期（1-2周）和中期（1-3月）的操作含义\n"
                "输出一段连贯的技术分析文本，强调信号间的逻辑关系。"
            ),
        )
        return analysis if analysis else deterministic

    def _deterministic_summary(self, data: Any) -> str:
        """Deterministic indicator-based summary (fallback)."""
        if not isinstance(data, dict) or not data.get("kline_data"):
            return "历史价格数据不足，无法计算技术指标。"

        indicators = self._compute_indicators(data.get("kline_data", []))
        if not indicators:
            return "数据点不足，无法计算技术指标。"

        rsi_state_cn = {"overbought": "超买", "oversold": "超卖", "neutral": "中性"}.get(indicators['rsi_state'], indicators['rsi_state'])
        momentum_cn = {"bullish": "多头", "bearish": "空头"}.get(indicators['momentum'], indicators['momentum'])
        trend_cn = {"uptrend": "上升趋势", "downtrend": "下降趋势", "sideways": "横盘震荡"}.get(indicators['trend'], indicators['trend'])

        parts = [
            f"{data.get('ticker', 'N/A')} 技术快照: 收盘价 {indicators['close']:.2f}。",
            f"MA20 {indicators['ma20']:.2f}" if indicators.get("ma20") is not None else "MA20 暂无",
            f"MA50 {indicators['ma50']:.2f}" if indicators.get("ma50") is not None else "MA50 暂无",
            f"MA200 {indicators['ma200']:.2f}" if indicators.get("ma200") is not None else "MA200 暂无",
            f"RSI(14) {indicators['rsi']:.2f}（{rsi_state_cn}）。",
            (
                f"MACD {indicators['macd']:.4f} vs 信号线 {indicators['signal']:.4f}"
                f"（{momentum_cn}）。"
            ),
            f"趋势: {trend_cn}。",
        ]
        interpretation = []
        if indicators.get("rsi_state") == "overbought":
            interpretation.append("RSI进入超买区，短期回撤风险上升。")
        elif indicators.get("rsi_state") == "oversold":
            interpretation.append("RSI进入超卖区，存在技术性反弹空间。")
        if indicators.get("trend") == "uptrend":
            interpretation.append("均线呈多头排列，趋势偏强。")
        elif indicators.get("trend") == "downtrend":
            interpretation.append("均线呈空头排列，趋势偏弱。")

        return " ".join(parts + interpretation)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence: List[EvidenceItem] = []
        data_sources: List[str] = []
        fallback_used = False
        fallback_reason: Optional[str] = None
        conflict_flags: List[str] = []
        conflicting_claims: List[ConflictClaim] = []

        if isinstance(raw_data, dict):
            source = raw_data.get("source", "kline")
            data_sources.append(source)
            if isinstance(source, str) and any(tag in source for tag in ("fallback", "scrape", "search")):
                fallback_used = True
                fallback_reason = f"primary_kline_unavailable, used_{source}"

            # 构造 Yahoo Finance 历史数据页面 URL，供证据池可点击跳转
            _ticker = str(raw_data.get("ticker") or "").strip().upper()
            _yf_history_url = f"https://finance.yahoo.com/quote/{_ticker}/history/" if _ticker else None

            indicators = self._compute_indicators(raw_data.get("kline_data", []))
            if indicators:
                timestamp = indicators.get("last_time")
                ma_parts = []
                if indicators.get("ma20") is not None:
                    ma_parts.append(f"MA20 {indicators['ma20']:.2f}")
                if indicators.get("ma50") is not None:
                    ma_parts.append(f"MA50 {indicators['ma50']:.2f}")
                if indicators.get("ma200") is not None:
                    ma_parts.append(f"MA200 {indicators['ma200']:.2f}")
                evidence.append(EvidenceItem(
                    text=" | ".join(ma_parts) if ma_parts else "均线数据暂无",
                    source=source,
                    url=_yf_history_url,  # Yahoo Finance 历史数据页面，供证据池点击跳转
                    timestamp=timestamp,
                ))
                evidence.append(EvidenceItem(
                    text=(
                        f"RSI(14) {indicators['rsi']:.2f} | MACD {indicators['macd']:.4f} "
                        f"| 信号线 {indicators['signal']:.4f}"
                    ),
                    source=source,
                    url=_yf_history_url,  # Yahoo Finance 历史数据页面，供证据池点击跳转
                    timestamp=timestamp,
                ))

                # --- Signal Confluence: detect inter-indicator conflicts ---
                rsi_state = indicators.get("rsi_state", "neutral")
                momentum = indicators.get("momentum", "bullish")
                trend = indicators.get("trend", "sideways")
                rsi_val = indicators.get("rsi", 0.0)
                macd_val = indicators.get("macd", 0.0)
                signal_val = indicators.get("signal", 0.0)

                # RSI vs MACD direction conflict
                if rsi_state == "overbought" and momentum == "bullish":
                    conflict_flags.append("RSI超买 vs MACD多头")
                    conflicting_claims.append(ConflictClaim(
                        claim="短期动量方向",
                        source_a="RSI(14)",
                        value_a=f"{rsi_val:.2f} (超买>70)",
                        source_b="MACD",
                        value_b=f"{macd_val:.4f} > 信号线{signal_val:.4f} (多头)",
                        severity="medium",
                    ))
                elif rsi_state == "oversold" and momentum == "bearish":
                    conflict_flags.append("RSI超卖 vs MACD空头")
                    conflicting_claims.append(ConflictClaim(
                        claim="短期动量方向",
                        source_a="RSI(14)",
                        value_a=f"{rsi_val:.2f} (超卖<30)",
                        source_b="MACD",
                        value_b=f"{macd_val:.4f} < 信号线{signal_val:.4f} (空头)",
                        severity="medium",
                    ))

                # Trend vs Momentum conflict
                if trend == "uptrend" and momentum == "bearish":
                    conflict_flags.append("均线多头排列 vs MACD空头")
                    conflicting_claims.append(ConflictClaim(
                        claim="中期趋势一致性",
                        source_a="均线趋势",
                        value_a="上升趋势(价格>MA20>MA50)",
                        source_b="MACD",
                        value_b=f"空头({macd_val:.4f}<{signal_val:.4f})",
                        severity="low",
                    ))
                elif trend == "downtrend" and momentum == "bullish":
                    conflict_flags.append("均线空头排列 vs MACD多头")
                    conflicting_claims.append(ConflictClaim(
                        claim="中期趋势一致性",
                        source_a="均线趋势",
                        value_a="下降趋势(价格<MA20<MA50)",
                        source_b="MACD",
                        value_b=f"多头({macd_val:.4f}>{signal_val:.4f})",
                        severity="low",
                    ))
        else:
            fallback_reason = "no_kline_data"

        confidence = 0.85 if evidence else 0.3
        risks = self._build_risks(raw_data, evidence)

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=data_sources or ["kline"],
            as_of=datetime.now().isoformat(),
            fallback_used=fallback_used,
            risks=risks,
            conflict_flags=conflict_flags,
            conflicting_claims=conflicting_claims,
            fallback_reason=fallback_reason,
            retryable=not fallback_used,
        )

    def _compute_indicators(self, kline_data: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        series, last_time = self._build_close_series(kline_data)
        if series is None or len(series) < self.MIN_POINTS:
            return None

        close = float(series.iloc[-1])
        ma20 = self._calc_ma(series, 20)
        ma50 = self._calc_ma(series, 50)
        ma200 = self._calc_ma(series, 200)
        rsi = self._calc_rsi(series, 14)
        macd, signal, hist = self._calc_macd(series)

        trend = "sideways"
        if ma20 is not None and ma50 is not None:
            if close > ma20 > ma50:
                trend = "uptrend"
            elif close < ma20 < ma50:
                trend = "downtrend"

        rsi_state = "neutral"
        if rsi is not None:
            if rsi >= 70:
                rsi_state = "overbought"
            elif rsi <= 30:
                rsi_state = "oversold"

        momentum = "bullish" if macd is not None and signal is not None and macd > signal else "bearish"

        return {
            "close": close,
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "rsi": rsi if rsi is not None else 0.0,
            "rsi_state": rsi_state,
            "macd": macd if macd is not None else 0.0,
            "signal": signal if signal is not None else 0.0,
            "hist": hist if hist is not None else 0.0,
            "trend": trend,
            "momentum": momentum,
            "last_time": last_time,
        }

    def _build_close_series(self, kline_data: List[Dict[str, Any]]) -> Tuple[Optional[pd.Series], Optional[str]]:
        closes = []
        last_time = None
        for item in kline_data:
            close = item.get("close")
            if close is None:
                continue
            closes.append(float(close))
            last_time = item.get("time") or last_time

        if not closes:
            return None, None
        return pd.Series(closes), last_time

    def _calc_ma(self, series: pd.Series, window: int) -> Optional[float]:
        if len(series) < window:
            return None
        return float(series.rolling(window=window).mean().iloc[-1])

    def _calc_rsi(self, series: pd.Series, window: int) -> Optional[float]:
        if len(series) < window + 1:
            return None
        delta = series.diff()
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        avg_gain = gains.rolling(window=window, min_periods=window).mean()
        avg_loss = losses.rolling(window=window, min_periods=window).mean()
        last_gain = float(avg_gain.iloc[-1]) if not pd.isna(avg_gain.iloc[-1]) else 0.0
        last_loss = float(avg_loss.iloc[-1]) if not pd.isna(avg_loss.iloc[-1]) else 0.0
        if last_loss == 0:
            return 100.0
        rs = last_gain / last_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_macd(self, series: pd.Series) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if len(series) < 26:
            return None, None, None
        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd_series = ema12 - ema26
        signal_series = macd_series.ewm(span=9, adjust=False).mean()
        macd = float(macd_series.iloc[-1])
        signal = float(signal_series.iloc[-1])
        return macd, signal, macd - signal

    def _build_risks(self, raw_data: Any, evidence: List[EvidenceItem]) -> List[str]:
        if not evidence:
            return ["历史数据不足，技术指标可靠性有限。"]

        indicators = self._compute_indicators(raw_data.get("kline_data", [])) if isinstance(raw_data, dict) else None
        risks = []
        if indicators:
            if indicators["rsi_state"] == "overbought":
                risks.append("RSI 进入超买区间，短期存在回调风险。")
            elif indicators["rsi_state"] == "oversold":
                risks.append("RSI 进入超卖区间，波动性风险较高。")
            if indicators["trend"] == "downtrend":
                risks.append("下跌趋势延续，趋势反转尚未确认。")
        return risks or ["技术信号暂无明显风险。"]
