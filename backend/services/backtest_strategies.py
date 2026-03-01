from __future__ import annotations

from typing import Any


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    period = max(1, int(period))
    k = 2 / (period + 1)
    out: list[float] = [values[0]]
    for value in values[1:]:
        out.append(value * k + out[-1] * (1 - k))
    return out


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    if len(values) < 2:
        return [None for _ in values]
    period = max(2, int(period))
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    output: list[float | None] = [None for _ in values]
    for idx in range(period, len(values)):
        window_gains = gains[idx - period + 1 : idx + 1]
        window_losses = losses[idx - period + 1 : idx + 1]
        avg_gain = sum(window_gains) / period
        avg_loss = sum(window_losses) / period
        if avg_loss == 0:
            output[idx] = 100.0
            continue
        rs = avg_gain / avg_loss
        output[idx] = 100.0 - (100.0 / (1.0 + rs))
    return output


def ma_cross_signals(closes: list[float], *, short_window: int = 20, long_window: int = 50) -> dict[str, Any]:
    short_window = max(2, int(short_window))
    long_window = max(short_window + 1, int(long_window))
    signals: list[int] = [0 for _ in closes]
    for idx in range(len(closes)):
        if idx + 1 < long_window:
            continue
        short_ma = sum(closes[idx - short_window + 1 : idx + 1]) / short_window
        long_ma = sum(closes[idx - long_window + 1 : idx + 1]) / long_window
        signals[idx] = 1 if short_ma > long_ma else 0
    return {
        "name": "ma_cross",
        "signals": signals,
        "params": {"short_window": short_window, "long_window": long_window},
    }


def macd_signals(closes: list[float], *, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, Any]:
    fast = max(2, int(fast))
    slow = max(fast + 1, int(slow))
    signal = max(2, int(signal))

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)

    signals: list[int] = []
    for macd_value, sig_value in zip(macd_line, signal_line):
        signals.append(1 if macd_value > sig_value else 0)

    return {
        "name": "macd",
        "signals": signals,
        "params": {"fast": fast, "slow": slow, "signal": signal},
    }


def rsi_mean_reversion_signals(
    closes: list[float],
    *,
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> dict[str, Any]:
    rsi_values = _rsi(closes, period)
    signals: list[int] = [0 for _ in closes]
    holding = 0
    for idx, value in enumerate(rsi_values):
        if value is None:
            signals[idx] = holding
            continue
        if value <= oversold:
            holding = 1
        elif value >= overbought:
            holding = 0
        signals[idx] = holding

    return {
        "name": "rsi_mean_reversion",
        "signals": signals,
        "params": {"period": period, "oversold": oversold, "overbought": overbought},
    }


def build_strategy_signals(strategy: str, closes: list[float], params: dict[str, Any] | None = None) -> dict[str, Any]:
    strategy_norm = str(strategy or "").strip().lower()
    cfg = params if isinstance(params, dict) else {}

    if strategy_norm in {"macd", "macd_strategy"}:
        return macd_signals(
            closes,
            fast=int(cfg.get("fast", 12)),
            slow=int(cfg.get("slow", 26)),
            signal=int(cfg.get("signal", 9)),
        )

    if strategy_norm in {"rsi", "rsi_mean_reversion", "rsi_mr"}:
        return rsi_mean_reversion_signals(
            closes,
            period=int(cfg.get("period", 14)),
            oversold=float(cfg.get("oversold", 30.0)),
            overbought=float(cfg.get("overbought", 70.0)),
        )

    return ma_cross_signals(
        closes,
        short_window=int(cfg.get("short_window", 20)),
        long_window=int(cfg.get("long_window", 50)),
    )


SUPPORTED_STRATEGIES = [
    {
        "id": "ma_cross",
        "name": "MA Cross",
        "description": "短均线上穿长均线买入，下穿卖出",
        "default_params": {"short_window": 20, "long_window": 50},
    },
    {
        "id": "macd",
        "name": "MACD",
        "description": "MACD 线上穿信号线买入，下穿卖出",
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
    },
    {
        "id": "rsi_mean_reversion",
        "name": "RSI Mean Reversion",
        "description": "RSI 超卖买入，超买卖出",
        "default_params": {"period": 14, "oversold": 30.0, "overbought": 70.0},
    },
]


__all__ = [
    "SUPPORTED_STRATEGIES",
    "build_strategy_signals",
    "ma_cross_signals",
    "macd_signals",
    "rsi_mean_reversion_signals",
]
