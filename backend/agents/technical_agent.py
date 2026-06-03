from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import os
import pandas as pd

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, ConflictClaim, EvidenceItem
from backend.agents.chart_specs_extra import build_technical_chart_specs
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
        """TechnicalAgent tool registry: K-line indicators with side-signal calibration.

        价格行为、RS、量价和期权波动率主分析归 PriceAgent；这里的 quote/options 仅用于校准 MA/RSI/MACD 等技术形态所处的位置。
        """
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
        quote_fn = getattr(tools, "get_stock_price", None)
        if quote_fn:
            registry["get_stock_price"] = {
                "func": quote_fn,
                "description": "获取当前报价与日内涨跌幅，用于校准技术快照的实时位置",
                "call_with": "ticker",
            }
        option_metrics_fn = getattr(tools, "get_option_chain_metrics", None)
        if option_metrics_fn:
            registry["get_option_chain_metrics"] = {
                "func": option_metrics_fn,
                "description": "获取期权隐含波动率、Put/Call Ratio 与 Skew，辅助判断短线拥挤度",
                "call_with": "ticker",
            }
        sentiment_fn = getattr(tools, "get_market_sentiment", None)
        if sentiment_fn:
            registry["get_market_sentiment"] = {
                "func": sentiment_fn,
                "description": "获取市场整体情绪，用于判断技术信号是否处在风险偏好顺风或逆风中",
                "call_with": "none",
            }
        return registry

    def _call_optional_tool(self, tool_name: str, *args, **kwargs) -> Any:
        tool_fn = getattr(self.tools, tool_name, None)
        if not tool_fn:
            return None
        try:
            payload = tool_fn(*args, **kwargs)
        except Exception:
            return None
        return payload if isinstance(payload, (dict, list, str)) else None

    def _llm_summary_enabled(self) -> bool:
        value = os.getenv("TECHNICAL_AGENT_LLM_SUMMARY_ENABLED", "0")
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _enrich_with_side_signals(self, data: Dict[str, Any], ticker: str) -> Dict[str, Any]:
        enriched = dict(data)
        # 分工说明：TechnicalAgent 保留 quote/options 作为指标形态的旁证校准，不在这里生成价格行为结论。
        price_snapshot = self._call_optional_tool("get_stock_price", ticker)
        if price_snapshot:
            enriched["price_snapshot"] = price_snapshot
        option_metrics = self._call_optional_tool("get_option_chain_metrics", ticker)
        if option_metrics:
            enriched["option_metrics"] = option_metrics
        market_sentiment = self._call_optional_tool("get_market_sentiment")
        if market_sentiment:
            enriched["market_sentiment"] = market_sentiment
        return enriched

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        cache_key = f"{ticker}:technical:kline"
        cached = self.cache.get(cache_key)
        if isinstance(cached, dict):
            return self._enrich_with_side_signals(cached, ticker)

        fetch = getattr(self.tools, "get_stock_historical_data", None)
        if not fetch:
            return {"error": "missing_kline_tool", "ticker": ticker}

        data = fetch(ticker, period="6mo", interval="1d")
        if isinstance(data, dict):
            data.setdefault("ticker", ticker)
            if data.get("kline_data"):
                self.cache.set(cache_key, data, self.CACHE_TTL)
            return self._enrich_with_side_signals(data, ticker)
        return data

    async def _first_summary(self, data: Any) -> str:
        deterministic = self._deterministic_summary(data)
        if not isinstance(data, dict) or not data.get("kline_data"):
            return deterministic
        if not self._llm_summary_enabled():
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
        if indicators.get("pct_from_ma20") is not None:
            parts.append(f"价格相对MA20偏离 {indicators['pct_from_ma20']:+.2f}%。")
        if indicators.get("support") is not None or indicators.get("resistance") is not None:
            support_text = f"{indicators['support']:.2f}" if indicators.get("support") is not None else "暂无"
            resistance_text = f"{indicators['resistance']:.2f}" if indicators.get("resistance") is not None else "暂无"
            parts.append(f"关键价位: 支撑 {support_text}，阻力 {resistance_text}。")
        if indicators.get("latest_volume") is not None:
            volume_text = f"成交量: 最新 {indicators['latest_volume']:.0f}"
            if indicators.get("avg_volume20") is not None:
                volume_text += f"，20日均量 {indicators['avg_volume20']:.0f}"
            if indicators.get("volume_ratio20") is not None:
                volume_text += f"，量能为均量 {indicators['volume_ratio20']:.2f}倍"
            parts.append(volume_text + "。")
        price_snapshot = data.get("price_snapshot")
        if isinstance(price_snapshot, dict):
            price = price_snapshot.get("price")
            currency = price_snapshot.get("currency") or "USD"
            change_pct = price_snapshot.get("change_percent") or price_snapshot.get("change_pct")
            if price is not None:
                quote = f"实时位置: {currency} {price}"
                if change_pct is not None:
                    try:
                        quote += f"（日内 {float(change_pct):+.2f}%）"
                    except Exception:
                        pass
                parts.append(quote + "。")
        option_metrics = data.get("option_metrics")
        if isinstance(option_metrics, dict):
            option_bits = []
            iv_atm = option_metrics.get("iv_atm")
            pcr = option_metrics.get("put_call_ratio_oi") or option_metrics.get("put_call_ratio_volume")
            skew = option_metrics.get("iv_skew_25d")
            if isinstance(iv_atm, (int, float)):
                option_bits.append(f"ATM IV {float(iv_atm):.2%}")
            if isinstance(pcr, (int, float)):
                option_bits.append(f"PCR {float(pcr):.2f}")
            if isinstance(skew, (int, float)):
                option_bits.append(f"Skew {float(skew):+.2%}")
            if option_bits:
                parts.append("期权情绪: " + "，".join(option_bits) + "。")
        market_sentiment = data.get("market_sentiment")
        if isinstance(market_sentiment, str) and market_sentiment.strip():
            parts.append(f"市场情绪参考: {market_sentiment.strip()[:160]}。")
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
                support_text = (
                    f"支撑 {indicators['support']:.2f}"
                    if indicators.get("support") is not None
                    else "支撑 暂无"
                )
                resistance_text = (
                    f"阻力 {indicators['resistance']:.2f}"
                    if indicators.get("resistance") is not None
                    else "阻力 暂无"
                )
                volume_bits = []
                if indicators.get("latest_volume") is not None:
                    volume_bits.append(f"最新成交量 {indicators['latest_volume']:.0f}")
                if indicators.get("avg_volume20") is not None:
                    volume_bits.append(f"20日均量 {indicators['avg_volume20']:.0f}")
                if indicators.get("volume_ratio20") is not None:
                    volume_bits.append(f"量能 {indicators['volume_ratio20']:.2f}x")
                evidence.append(EvidenceItem(
                    text=" | ".join([support_text, resistance_text, *volume_bits]),
                    source=source,
                    url=_yf_history_url,
                    timestamp=timestamp,
                ))

                price_snapshot = raw_data.get("price_snapshot")
                if isinstance(price_snapshot, dict):
                    price_source = str(price_snapshot.get("source") or "quote")
                    price = price_snapshot.get("price")
                    currency = price_snapshot.get("currency") or "USD"
                    change_pct = price_snapshot.get("change_percent") or price_snapshot.get("change_pct")
                    price_text = f"Current quote: {currency} {price}"
                    if change_pct is not None:
                        try:
                            price_text += f", intraday {float(change_pct):+.2f}%"
                        except Exception:
                            pass
                    evidence.append(EvidenceItem(
                        text=price_text,
                        source=price_source,
                        timestamp=str(price_snapshot.get("as_of") or timestamp or datetime.now().isoformat()),
                        meta=price_snapshot,
                    ))
                    data_sources.append(price_source)

                option_metrics = raw_data.get("option_metrics")
                if isinstance(option_metrics, dict):
                    option_source = str(option_metrics.get("source") or "options")
                    option_bits = []
                    iv_atm = option_metrics.get("iv_atm")
                    pcr = option_metrics.get("put_call_ratio_oi") or option_metrics.get("put_call_ratio_volume")
                    skew = option_metrics.get("iv_skew_25d")
                    if isinstance(iv_atm, (int, float)):
                        option_bits.append(f"ATM IV {float(iv_atm):.2%}")
                    if isinstance(pcr, (int, float)):
                        option_bits.append(f"PCR {float(pcr):.2f}")
                    if isinstance(skew, (int, float)):
                        option_bits.append(f"Skew {float(skew):+.2%}")
                    evidence.append(EvidenceItem(
                        text="Option metrics: " + (", ".join(option_bits) if option_bits else "available"),
                        source=option_source,
                        timestamp=str(option_metrics.get("as_of") or timestamp or datetime.now().isoformat()),
                        meta=option_metrics,
                    ))
                    data_sources.append(option_source)

                market_sentiment = raw_data.get("market_sentiment")
                if isinstance(market_sentiment, str) and market_sentiment.strip():
                    evidence.append(EvidenceItem(
                        text=f"Market sentiment: {market_sentiment.strip()[:240]}",
                        source="market_sentiment",
                        timestamp=timestamp,
                    ))
                    data_sources.append("market_sentiment")

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

        # P2-8：技术分析图表（K线 + 均线对比 + RSI 仪表盘），数据不足返回 []
        chart_specs: List[dict] = []
        if isinstance(raw_data, dict):
            chart_specs = build_technical_chart_specs(
                str(raw_data.get("ticker") or ""),
                raw_data,
            )

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=data_sources or ["kline"],
            as_of=datetime.now().isoformat(),
            chart_specs=chart_specs,
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
        pct_from_ma20 = ((close - ma20) / ma20 * 100.0) if ma20 else None

        recent_rows = [item for item in kline_data[-20:] if isinstance(item, dict)]
        lows: List[float] = []
        highs: List[float] = []
        volumes: List[float] = []
        for item in recent_rows:
            try:
                if item.get("low") is not None:
                    lows.append(float(item["low"]))
                if item.get("high") is not None:
                    highs.append(float(item["high"]))
                if item.get("volume") is not None:
                    volumes.append(float(item["volume"]))
            except Exception:
                continue
        support = min(lows) if lows else None
        resistance = max(highs) if highs else None
        latest_volume = volumes[-1] if volumes else None
        avg_volume20 = (sum(volumes) / len(volumes)) if volumes else None
        volume_ratio20 = (
            latest_volume / avg_volume20
            if latest_volume is not None and avg_volume20 not in (None, 0)
            else None
        )

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
            "pct_from_ma20": pct_from_ma20,
            "rsi": rsi if rsi is not None else 0.0,
            "rsi_state": rsi_state,
            "macd": macd if macd is not None else 0.0,
            "signal": signal if signal is not None else 0.0,
            "hist": hist if hist is not None else 0.0,
            "trend": trend,
            "momentum": momentum,
            "support": support,
            "resistance": resistance,
            "latest_volume": latest_volume,
            "avg_volume20": avg_volume20,
            "volume_ratio20": volume_ratio20,
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
