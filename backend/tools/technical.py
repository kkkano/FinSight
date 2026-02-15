"""Public technical indicator computation utilities.

Extracts and expands the indicator logic from TechnicalAgent into a
reusable, pure-function interface that operates on a standard OHLCV
pandas DataFrame.
"""

import logging
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Minimum data points required for meaningful indicator computation
_MIN_POINTS = 30


def _safe_float(value: Any) -> Optional[float]:
    """Convert value to float, returning None for NaN/Inf."""
    if value is None:
        return None
    try:
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


def _calc_ma(series: pd.Series, window: int) -> Optional[float]:
    """Simple moving average of the last value."""
    if len(series) < window:
        return None
    return _safe_float(series.rolling(window=window).mean().iloc[-1])


def _calc_ema(series: pd.Series, span: int) -> Optional[float]:
    """Exponential moving average of the last value."""
    if len(series) < span:
        return None
    return _safe_float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _calc_rsi(series: pd.Series, window: int = 14) -> Optional[float]:
    """Relative Strength Index (Wilder smoothing)."""
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


def _calc_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """MACD line, signal line, histogram."""
    if len(series) < slow:
        return None, None, None
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    macd_val = _safe_float(macd_line.iloc[-1])
    signal_val = _safe_float(signal_line.iloc[-1])
    hist_val = (macd_val - signal_val) if macd_val is not None and signal_val is not None else None
    return macd_val, signal_val, hist_val


def _calc_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[Optional[float], Optional[float]]:
    """Stochastic Oscillator (%K and %D)."""
    if len(close) < k_period:
        return None, None
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    denom = highest_high - lowest_low
    # Avoid division by zero
    denom = denom.replace(0, np.nan)
    k_series = ((close - lowest_low) / denom) * 100
    d_series = k_series.rolling(window=d_period).mean()
    return _safe_float(k_series.iloc[-1]), _safe_float(d_series.iloc[-1])


def _calc_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> Optional[float]:
    """Average Directional Index."""
    if len(close) < period * 2:
        return None
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
    dx_denom = (plus_di + minus_di).replace(0, np.nan)
    dx = ((plus_di - minus_di).abs() / dx_denom) * 100
    adx = dx.ewm(span=period, adjust=False).mean()
    return _safe_float(adx.iloc[-1])


def _calc_cci(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 20,
) -> Optional[float]:
    """Commodity Channel Index."""
    if len(close) < period:
        return None
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    mad = mad.replace(0, np.nan)
    cci = (tp - sma_tp) / (0.015 * mad)
    return _safe_float(cci.iloc[-1])


def _calc_williams_r(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> Optional[float]:
    """Williams %R."""
    if len(close) < period:
        return None
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    denom = highest_high - lowest_low
    denom = denom.replace(0, np.nan)
    wr = ((highest_high - close) / denom) * -100
    return _safe_float(wr.iloc[-1])


def _calc_bollinger_bands(
    close: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Bollinger Bands (upper, middle, lower)."""
    if len(close) < period:
        return None, None, None
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return (
        _safe_float(upper.iloc[-1]),
        _safe_float(middle.iloc[-1]),
        _safe_float(lower.iloc[-1]),
    )


def _calc_pivot_points(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> tuple[list[float], list[float]]:
    """Classic pivot-point support/resistance levels from the last bar."""
    h = _safe_float(high.iloc[-1])
    l_val = _safe_float(low.iloc[-1])
    c = _safe_float(close.iloc[-1])
    if h is None or l_val is None or c is None:
        return [], []
    pivot = (h + l_val + c) / 3
    s1 = 2 * pivot - h
    s2 = pivot - (h - l_val)
    r1 = 2 * pivot - l_val
    r2 = pivot + (h - l_val)
    supports = [round(s1, 4), round(s2, 4)]
    resistances = [round(r1, 4), round(r2, 4)]
    return supports, resistances


def compute_technical_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Compute technical indicators from OHLCV DataFrame.

    Args:
        df: DataFrame with columns Open, High, Low, Close, Volume.
            Must have at least ``_MIN_POINTS`` rows.

    Returns:
        Dictionary with all computed indicator values.  Returns an empty
        dict if the input is too short.
    """
    if df is None or len(df) < _MIN_POINTS:
        return {}

    # Normalize column names to title-case
    col_map = {c: c.title() for c in df.columns}
    df = df.rename(columns=col_map)

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(set(df.columns)):
        return {}

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    last_close = _safe_float(close.iloc[-1])
    if last_close is None:
        return {}

    # Moving averages
    ma5 = _calc_ma(close, 5)
    ma10 = _calc_ma(close, 10)
    ma20 = _calc_ma(close, 20)
    ma50 = _calc_ma(close, 50)
    ma100 = _calc_ma(close, 100)
    ma200 = _calc_ma(close, 200)
    ema12 = _calc_ema(close, 12)
    ema26 = _calc_ema(close, 26)

    # RSI
    rsi = _calc_rsi(close, 14)
    rsi_state = "neutral"
    if rsi is not None:
        if rsi >= 70:
            rsi_state = "overbought"
        elif rsi <= 30:
            rsi_state = "oversold"

    # MACD
    macd_val, macd_signal, macd_hist = _calc_macd(close)

    # Stochastic
    stoch_k, stoch_d = _calc_stochastic(high, low, close)

    # ADX
    adx = _calc_adx(high, low, close)

    # CCI
    cci = _calc_cci(high, low, close)

    # Williams %R
    williams_r = _calc_williams_r(high, low, close)

    # Bollinger Bands
    bb_upper, bb_middle, bb_lower = _calc_bollinger_bands(close)

    # Pivot support / resistance
    support_levels, resistance_levels = _calc_pivot_points(high, low, close)

    # Average volume (20-day)
    avg_volume: Optional[float] = None
    if len(volume) >= 20:
        avg_volume = _safe_float(volume.tail(20).mean())

    # Trend determination
    trend = "neutral"
    if ma20 is not None and ma50 is not None:
        if last_close > ma20 > ma50:
            trend = "bullish"
        elif last_close < ma20 < ma50:
            trend = "bearish"

    # Momentum assessment
    momentum = "neutral"
    if macd_val is not None and macd_signal is not None:
        if macd_val > macd_signal:
            momentum = "bullish"
        else:
            momentum = "bearish"

    return {
        "close": last_close,
        "trend": trend,
        "momentum": momentum,
        # Moving averages
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma50": ma50,
        "ma100": ma100,
        "ma200": ma200,
        "ema12": ema12,
        "ema26": ema26,
        # RSI
        "rsi": rsi,
        "rsi_state": rsi_state,
        # MACD
        "macd": macd_val,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        # Stochastic
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        # ADX
        "adx": adx,
        # CCI
        "cci": cci,
        # Williams %R
        "williams_r": williams_r,
        # Bollinger Bands
        "bollinger_upper": bb_upper,
        "bollinger_middle": bb_middle,
        "bollinger_lower": bb_lower,
        # Support / Resistance
        "support_levels": support_levels,
        "resistance_levels": resistance_levels,
        # Volume
        "avg_volume": avg_volume,
    }
