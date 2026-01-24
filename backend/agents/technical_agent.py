from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker


class TechnicalAgent(BaseFinancialAgent):
    AGENT_NAME = "technical"
    CACHE_TTL = 1800  # 30 minutes
    MIN_POINTS = 30

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

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
        if not isinstance(data, dict) or not data.get("kline_data"):
            return "Insufficient price history to compute technical indicators."

        indicators = self._compute_indicators(data.get("kline_data", []))
        if not indicators:
            return "Not enough data points to compute technical indicators."

        parts = [
            f"Technical snapshot for {data.get('ticker', 'N/A')}: close {indicators['close']:.2f}.",
            f"MA20 {indicators['ma20']:.2f}" if indicators.get("ma20") is not None else "MA20 N/A",
            f"MA50 {indicators['ma50']:.2f}" if indicators.get("ma50") is not None else "MA50 N/A",
            f"MA200 {indicators['ma200']:.2f}" if indicators.get("ma200") is not None else "MA200 N/A",
            f"RSI(14) {indicators['rsi']:.2f} ({indicators['rsi_state']}).",
            (
                f"MACD {indicators['macd']:.4f} vs signal {indicators['signal']:.4f} "
                f"({indicators['momentum']})."
            ),
            f"Trend: {indicators['trend']}.",
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

        if isinstance(raw_data, dict):
            source = raw_data.get("source", "kline")
            data_sources.append(source)
            if isinstance(source, str) and any(tag in source for tag in ("fallback", "scrape", "search")):
                fallback_used = True

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
                    text=" | ".join(ma_parts) if ma_parts else "MA data unavailable",
                    source=source,
                    timestamp=timestamp,
                ))
                evidence.append(EvidenceItem(
                    text=(
                        f"RSI(14) {indicators['rsi']:.2f} | MACD {indicators['macd']:.4f} "
                        f"| Signal {indicators['signal']:.4f}"
                    ),
                    source=source,
                    timestamp=timestamp,
                ))

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
            return ["Limited historical data for indicators."]

        indicators = self._compute_indicators(raw_data.get("kline_data", [])) if isinstance(raw_data, dict) else None
        risks = []
        if indicators:
            if indicators["rsi_state"] == "overbought":
                risks.append("RSI suggests overbought conditions; pullback risk.")
            elif indicators["rsi_state"] == "oversold":
                risks.append("RSI suggests oversold conditions; volatility risk.")
            if indicators["trend"] == "downtrend":
                risks.append("Downtrend persists; trend reversal not confirmed.")
        return risks or ["Technical signals are mixed."]
