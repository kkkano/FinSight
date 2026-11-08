"""美股扩展时段行情与 FINRA 延迟场外成交统计，保留来源和可用性边界。"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.services.data_contract import AssetContext
from backend.services.market_hours import get_market_session
from backend.tools.http import _get_no_retry_http_session
from backend.tools.yfinance_client import create_ticker


_FINRA_URL = "https://api.finra.org/data/group/otcMarket/name/weeklySummary"
_FINRA_SOURCE_URL = "https://www.finra.org/finra-data/browse-catalog/otc-transparency"
_INTERVALS = {"1m", "5m", "15m", "30m"}
_SESSIONS = {"all", "pre_market", "regular", "after_hours"}


def _us_symbol(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,13}(?:[.-][A-Z])?", symbol) or AssetContext.from_symbol(symbol).market != "US":
        raise ValueError("us_equity_ticker_required")
    return symbol


def _number(value: Any, *, positive: bool = False) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and (number > 0 if positive else number >= 0) else None


def _unavailable(ticker: str, source: str, error: str, summary: str, **details) -> dict:
    return {"status": "unavailable", "ticker": ticker, "source": source, "as_of": None,
            "currency": None, "delayed": None, "rows": [], "error": error, "summary": summary, **details}


def get_us_extended_hours(ticker: str, period: str = "5d", interval: str = "5m", session: str = "all") -> dict:
    """读取 Yahoo 美股盘前/常规/盘后 OHLCV；不承诺实时、不覆盖 20:00–04:00 夜盘。"""
    symbol = _us_symbol(ticker)
    if period not in {"1d", "5d", "1mo"} or interval not in _INTERVALS or session not in _SESSIONS:
        raise ValueError("extended_hours_parameters_unsupported")
    if interval == "1m" and period == "1mo":
        raise ValueError("one_minute_history_limited_to_five_days")
    source_url = f"https://finance.yahoo.com/quote/{symbol.replace('.', '-')}/history/"
    try:
        stock = create_ticker(symbol.replace(".", "-"))
        frame = stock.history(period=period, interval=interval, prepost=True, auto_adjust=False,
                              actions=False, timeout=15, raise_errors=True)
        if frame is None or frame.empty:
            return _unavailable(symbol, "yfinance", "extended_hours_empty", "来源没有返回该窗口的扩展时段行情。", session=session)
        metadata = stock.get_history_metadata() or {}
        if metadata.get("symbol") and metadata["symbol"].replace(".", "-").upper() != symbol.replace(".", "-"):
            return _unavailable(symbol, "yfinance", "extended_hours_symbol_mismatch", "来源返回的标的与请求不一致。", session=session)
        if len(frame) > 5000:
            return _unavailable(symbol, "yfinance", "extended_hours_window_too_large", "数据超过绘图上限，请缩短 period 或增大 interval。", session=session)
        index = frame.index
        if index.tz is None:
            source_timezone = metadata.get("exchangeTimezoneName")
            if not source_timezone:
                return _unavailable(symbol, "yfinance", "source_timezone_missing", "来源未提供时区，无法可靠区分盘前和盘后。", session=session)
            index = index.tz_localize(source_timezone)
        currency = metadata.get("currency")
        delay_minutes = _number(metadata.get("exchangeDataDelayedBy"))
        rows = []
        previous_time = None
        invalid_bars = 0
        for stamp, (_, raw) in zip(index, frame.iterrows()):
            when = stamp.to_pydatetime().astimezone(timezone.utc)
            if previous_time is not None and when <= previous_time:
                return _unavailable(symbol, "yfinance", "extended_hours_timestamps_invalid", "来源时间重复或乱序，未生成替代行情。", session=session)
            previous_time = when
            bar_session = get_market_session(when, symbol=symbol)
            if bar_session == "closed" or session != "all" and bar_session != session:
                continue
            values = {field: _number(raw.get(field.title()), positive=True) for field in ("open", "high", "low", "close")}
            if (any(value is None for value in values.values())
                    or not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]):
                invalid_bars += 1
                continue
            timestamp = when.isoformat()
            rows.append({"date": timestamp, "time": timestamp, **values,
                         "volume": _number(raw.get("Volume")), "session": bar_session})
        if not rows:
            return _unavailable(symbol, "yfinance", "extended_hours_session_empty", "所选时段没有有效行情，不以常规时段或占位值替代。", session=session)
        return {"status": "ok", "ticker": symbol, "source": "yfinance", "source_url": source_url,
                "as_of": rows[-1]["time"], "observed_at": datetime.now(timezone.utc).isoformat(),
                "source_time_precision": "bar_start", "currency": currency, "timezone": "America/New_York",
                "period": period, "interval": interval, "session": session, "rows": rows,
                "sessions_present": sorted({row["session"] for row in rows}),
                "delayed": delay_minutes > 0 if delay_minutes is not None else None,
                "delay_minutes": delay_minutes, "delay_status": "provided" if delay_minutes is not None else "unknown",
                "auto_adjust": False, "invalid_bars_excluded": invalid_bars,
                "units": {"open": currency, "high": currency, "low": currency, "close": currency, "volume": "shares"},
                "limitations": ["覆盖来源实际返回的 04:00–20:00 纽约时间交易；不包含 20:00–04:00 夜盘。",
                                "时段按交易日历划分，包含夏令时、节假日和提前收市；缺柱不填充。",
                                "最新柱可能尚未结束；未声明延迟时不能视为实时行情。",
                                "成交量保留供应商原值，缺失为 null；没有买卖方向，不能据此计算资金净流入。"]}
    except Exception as exc:
        return _unavailable(symbol, "yfinance", "extended_hours_provider_unavailable", "扩展时段行情暂时无法取得。",
                            session=session, error_type=type(exc).__name__)


def get_finra_otc_activity(ticker: str, weeks: int = 8) -> dict:
    """读取 FINRA ATS/非 ATS 周成交股数和笔数；不是暗盘报价、买卖方向或资金净流入。"""
    symbol = _us_symbol(ticker)
    if type(weeks) is not int or not 1 <= weeks <= 26:
        raise ValueError("otc_weeks_must_be_between_1_and_26")
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(weeks=weeks + 6)).isoformat()
    body = {
        "limit": 128,
        "fields": ["issueSymbolIdentifier", "issueName", "weekStartDate", "summaryTypeCode", "tierIdentifier",
                   "totalWeeklyShareQuantity", "totalWeeklyTradeCount", "lastReportedDate", "lastUpdateDate", "initialPublishedDate"],
        "compareFilters": [
            {"compareType": "equal", "fieldName": "issueSymbolIdentifier", "fieldValue": symbol},
            {"compareType": "greater", "fieldName": "weekStartDate", "fieldValue": start},
        ],
        # 只读证券总计，不能与分 ATS/券商明细重复累计。
        "domainFilters": [{"fieldName": "summaryTypeCode", "values": ["ATS_W_SMBL", "OTC_W_SMBL"]}],
    }
    try:
        response = _get_no_retry_http_session().post(_FINRA_URL, json=body, headers={"Accept": "application/json"}, timeout=(5, 15))
        if response.status_code != 200:
            return _unavailable(symbol, "finra_otc_transparency", "finra_otc_provider_unavailable", "FINRA 场外成交统计暂时无法取得。",
                                http_status=response.status_code, delayed=True, session="weekly_aggregate")
        payload = response.json()
        if not isinstance(payload, list) or len(payload) >= body["limit"]:
            return _unavailable(symbol, "finra_otc_transparency", "finra_otc_response_incomplete", "FINRA 响应格式异常或已达数量上限，未计算不完整合计。",
                                delayed=True, session="weekly_aggregate")
        grouped: dict[str, dict] = {}
        seen = set()
        for item in payload:
            if not isinstance(item, dict) or item.get("issueSymbolIdentifier") != symbol:
                raise ValueError("finra_otc_symbol_mismatch")
            kind = {"ATS_W_SMBL": "ats", "OTC_W_SMBL": "non_ats"}.get(item.get("summaryTypeCode"))
            if kind is None:
                raise ValueError("finra_otc_summary_type_mismatch")
            week = date.fromisoformat(item["weekStartDate"]).isoformat()
            if (week, kind) in seen:
                raise ValueError("finra_otc_duplicate_summary")
            seen.add((week, kind))
            share_volume, trade_count = _number(item.get("totalWeeklyShareQuantity")), _number(item.get("totalWeeklyTradeCount"))
            if share_volume is None or trade_count is None or not trade_count.is_integer():
                raise ValueError("finra_otc_metrics_invalid")
            row = grouped.setdefault(week, {"date": week, "week_start": week, "as_of": week, "session": "weekly_aggregate",
                                            "ats_share_volume": None, "non_ats_share_volume": None,
                                            "ats_trade_count": None, "non_ats_trade_count": None, "venue_metadata": {}})
            row[f"{kind}_share_volume"] = share_volume
            row[f"{kind}_trade_count"] = int(trade_count)
            row["venue_metadata"][kind] = {
                "tier": item.get("tierIdentifier"), "last_reported_date": item.get("lastReportedDate"),
                "published_date": item.get("initialPublishedDate"), "updated_date": item.get("lastUpdateDate"),
                "nominal_publication_delay_weeks": {"T1": 2, "T2": 4, "OTC": 4, "OTCE": 4}.get(item.get("tierIdentifier")),
            }
        rows = [grouped[week] for week in sorted(grouped)[-weeks:]]
        if not rows:
            return _unavailable(symbol, "finra_otc_transparency", "finra_otc_empty", "该标的在查询窗口没有已发布的场外周成交统计。",
                                delayed=True, session="weekly_aggregate")
        for row in rows:
            row["missing_venues"] = [kind for kind in ("ats", "non_ats") if row[f"{kind}_share_volume"] is None]
        return {"status": "ok", "ticker": symbol, "source": "finra_otc_transparency", "source_url": _FINRA_SOURCE_URL,
                "as_of": rows[-1]["week_start"], "source_time_precision": "week", "observed_at": datetime.now(timezone.utc).isoformat(),
                "currency": None, "delayed": True, "delay_status": "published_with_delay", "session": "weekly_aggregate",
                "rows": rows, "units": {"ats_share_volume": "shares", "non_ats_share_volume": "shares",
                                         "ats_trade_count": "trades", "non_ats_trade_count": "trades"},
                "unavailable_metrics": {
                    "net_money_flow": {"status": "unavailable", "reason": "来源不提供成交买卖方向或成交金额，不能计算资金净流入。"},
                    "realtime_dark_pool_quotes": {"status": "unavailable", "reason": "来源为延迟周成交统计，不提供暗盘即时报价或盘口。"},
                },
                "limitations": ["Tier 1 通常延迟两周发布，其他 NMS/OTC 通常延迟四周；以每条实际发布日期为准。",
                                "ATS 与非 ATS 分列；ATS 不等同于所有暗池，非 ATS 也不能视为暗池成交。",
                                "周汇总不含逐笔价格、买卖方向、盘前盘后拆分；股数/笔数不是资金流入流出。",
                                "未返回的场所保留 null，不能解释为零成交；小数股保留来源精度。"]}
    except Exception as exc:
        return _unavailable(symbol, "finra_otc_transparency", "finra_otc_data_unavailable", "FINRA 场外数据未能通过读取或校验。",
                            delayed=True, session="weekly_aggregate", error_type=type(exc).__name__)
