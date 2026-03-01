from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.services.backtest_strategies import SUPPORTED_STRATEGIES, build_strategy_signals
from backend.tools import fetch_cn_hk_kline, get_stock_historical_data


@dataclass
class PricePoint:
    time: str
    close: float


class BacktestEngine:
    def __init__(self, *, default_fee_bps: float = 5.0, default_slippage_bps: float = 3.0) -> None:
        self.default_fee_bps = float(default_fee_bps)
        self.default_slippage_bps = float(default_slippage_bps)

    @staticmethod
    def list_strategies() -> list[dict[str, Any]]:
        return list(SUPPORTED_STRATEGIES)

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).split("T")[0])
        except Exception:
            return None

    @staticmethod
    def _filter_by_date(points: list[PricePoint], start_date: str | None, end_date: str | None) -> list[PricePoint]:
        start = BacktestEngine._parse_date(start_date)
        end = BacktestEngine._parse_date(end_date)
        if start is None and end is None:
            return points

        output: list[PricePoint] = []
        for point in points:
            dt = BacktestEngine._parse_date(point.time)
            if dt is None:
                continue
            if start and dt < start:
                continue
            if end and dt > end:
                continue
            output.append(point)
        return output

    @staticmethod
    def _normalize_points(raw: list[dict[str, Any]]) -> list[PricePoint]:
        points: list[PricePoint] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                close = float(item.get("close"))
            except Exception:
                continue
            ts = str(item.get("time") or "").strip()
            if not ts:
                continue
            points.append(PricePoint(time=ts, close=close))
        points.sort(key=lambda p: p.time)
        return points

    def _load_series(self, ticker: str, market: str | None = None) -> tuple[list[PricePoint], str]:
        payload = get_stock_historical_data(ticker, period="5y", interval="1d")
        if isinstance(payload, dict):
            kline = payload.get("kline_data")
            if isinstance(kline, list):
                points = self._normalize_points(kline)
                if points:
                    return points, str(payload.get("source") or "historical")

        market_norm = str(market or "").strip().upper()
        if market_norm in {"CN", "HK"}:
            fallback = fetch_cn_hk_kline(ticker, limit=1200)
            if isinstance(fallback, list):
                points = self._normalize_points(fallback)
                if points:
                    return points, "eastmoney_kline"

        return [], "unavailable"

    @staticmethod
    def _max_drawdown(equity_curve: list[dict[str, Any]]) -> float:
        if not equity_curve:
            return 0.0
        peak = float(equity_curve[0]["equity"])
        worst = 0.0
        for item in equity_curve:
            equity = float(item["equity"])
            peak = max(peak, equity)
            if peak <= 0:
                continue
            dd = (equity - peak) / peak
            worst = min(worst, dd)
        return worst * 100.0

    def run(
        self,
        *,
        ticker: str,
        strategy: str,
        params: dict[str, Any] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        initial_cash: float = 100000.0,
        fee_bps: float | None = None,
        slippage_bps: float | None = None,
        t_plus_one: bool = True,
        market: str | None = None,
    ) -> dict[str, Any]:
        symbol = str(ticker or "").strip().upper()
        if not symbol:
            return {"success": False, "error": "ticker is required"}

        points, source = self._load_series(symbol, market=market)
        points = self._filter_by_date(points, start_date, end_date)
        if len(points) < 40:
            return {
                "success": False,
                "error": "insufficient_price_data",
                "ticker": symbol,
                "source": source,
                "points": len(points),
            }

        closes = [point.close for point in points]
        signal_payload = build_strategy_signals(strategy, closes, params)
        signals = signal_payload.get("signals") or []
        if len(signals) != len(points):
            return {"success": False, "error": "signal_length_mismatch"}

        fee_rate = max(0.0, float(self.default_fee_bps if fee_bps is None else fee_bps)) / 10000.0
        slippage_rate = max(0.0, float(self.default_slippage_bps if slippage_bps is None else slippage_bps)) / 10000.0

        cash = float(initial_cash)
        shares = 0.0
        buy_index = -10**9
        equity_curve: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        wins = 0
        closed_trades = 0

        for idx, point in enumerate(points):
            signal_idx = idx - 1 if t_plus_one else idx
            target = int(signals[signal_idx]) if signal_idx >= 0 else 0
            price = float(point.close)

            can_sell = True
            if t_plus_one and shares > 0 and idx <= buy_index:
                can_sell = False

            if target == 1 and shares <= 0 and cash > 0:
                buy_price = price * (1 + slippage_rate)
                qty = cash / (buy_price * (1 + fee_rate))
                cost = qty * buy_price
                fee = cost * fee_rate
                cash -= cost + fee
                shares = qty
                buy_index = idx
                trades.append(
                    {
                        "type": "buy",
                        "time": point.time,
                        "price": buy_price,
                        "shares": qty,
                        "fee": fee,
                    }
                )

            elif target == 0 and shares > 0 and can_sell:
                sell_price = price * (1 - slippage_rate)
                proceeds = shares * sell_price
                fee = proceeds * fee_rate
                realized = proceeds - fee

                buy_trade = next((item for item in reversed(trades) if item.get("type") == "buy"), None)
                if isinstance(buy_trade, dict):
                    invested = float(buy_trade.get("price") or 0) * float(buy_trade.get("shares") or 0) + float(
                        buy_trade.get("fee") or 0
                    )
                    pnl = realized - invested
                    closed_trades += 1
                    if pnl > 0:
                        wins += 1
                else:
                    pnl = None

                cash += realized
                trades.append(
                    {
                        "type": "sell",
                        "time": point.time,
                        "price": sell_price,
                        "shares": shares,
                        "fee": fee,
                        "pnl": pnl,
                    }
                )
                shares = 0.0

            equity = cash + shares * price
            equity_curve.append({"time": point.time, "equity": equity, "price": price, "position": int(shares > 0)})

        final_equity = float(equity_curve[-1]["equity"])
        total_return = (final_equity / float(initial_cash) - 1.0) * 100.0
        max_dd = self._max_drawdown(equity_curve)
        win_rate = (wins / closed_trades * 100.0) if closed_trades > 0 else 0.0

        return {
            "success": True,
            "ticker": symbol,
            "strategy": signal_payload.get("name") or strategy,
            "strategy_params": signal_payload.get("params") or {},
            "source": source,
            "period": {
                "start": points[0].time,
                "end": points[-1].time,
                "bars": len(points),
            },
            "settings": {
                "initial_cash": float(initial_cash),
                "fee_bps": float(fee_rate * 10000),
                "slippage_bps": float(slippage_rate * 10000),
                "t_plus_one": bool(t_plus_one),
            },
            "metrics": {
                "final_equity": final_equity,
                "total_return_pct": total_return,
                "max_drawdown_pct": max_dd,
                "trade_count": closed_trades,
                "win_rate_pct": win_rate,
            },
            "trades": trades,
            "equity_curve": equity_curve,
        }


__all__ = ["BacktestEngine", "PricePoint"]
