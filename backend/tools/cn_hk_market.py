from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

from backend.utils.quote import safe_float

from .http import _http_get

logger = logging.getLogger(__name__)

_EASTMONEY_USER_AGENT = os.getenv("EASTMONEY_USER_AGENT", "Mozilla/5.0 (FinSight)")
_EASTMONEY_TIMEOUT = int(os.getenv("EASTMONEY_TIMEOUT", "12"))
_EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EASTMONEY_FINANCIAL_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def detect_market(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return "UNKNOWN"
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "UNKNOWN"


def normalize_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def ticker_to_eastmoney_secid(ticker: str) -> str | None:
    symbol = normalize_ticker(ticker)
    market = detect_market(symbol)
    if market == "CN":
        if symbol.endswith(".SS"):
            return f"1.{symbol[:-3]}"
        if symbol.endswith(".SZ") or symbol.endswith(".BJ"):
            return f"0.{symbol[:-3]}"
        return None
    if market == "HK":
        core = re.sub(r"\D", "", symbol[:-3])
        if not core:
            return None
        return f"116.{core.zfill(5)}"
    return None


def ticker_to_secu_code(ticker: str) -> str | None:
    symbol = normalize_ticker(ticker)
    market = detect_market(symbol)
    if market == "CN":
        if symbol.endswith(".SS"):
            return f"{symbol[:-3]}.SH"
        if symbol.endswith(".SZ"):
            return f"{symbol[:-3]}.SZ"
        if symbol.endswith(".BJ"):
            return f"{symbol[:-3]}.BJ"
        return None
    if market == "HK":
        core = re.sub(r"\D", "", symbol[:-3])
        if not core:
            return None
        return f"{core.zfill(5)}.HK"
    return None


def _eastmoney_get_json(url: str, params: dict[str, Any], timeout: int | None = None) -> dict[str, Any] | None:
    try:
        resp = _http_get(
            url,
            params=params,
            timeout=int(timeout or _EASTMONEY_TIMEOUT),
            headers={"User-Agent": _EASTMONEY_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) != 200:
            return None
        payload = resp.json()
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        logger.info("[CNHK] eastmoney request failed for %s: %s", url, exc)
        return None


def _period_label(report_date: Any, report_type: Any) -> str | None:
    date_text = str(report_date or "").strip()
    if not date_text:
        return None
    day_part = date_text.split(" ")[0]
    try:
        dt = datetime.fromisoformat(day_part)
    except Exception:
        return None
    year = dt.year
    report_text = str(report_type or "").strip()
    if any(token in report_text for token in ("一季报", "一季度")):
        return f"{year}Q1"
    if any(token in report_text for token in ("中报", "半年报", "二季报", "二季度")):
        return f"{year}Q2"
    if any(token in report_text for token in ("三季报", "三季度")):
        return f"{year}Q3"
    if any(token in report_text for token in ("年报", "年度")):
        return f"{year}FY"
    quarter = (dt.month - 1) // 3 + 1
    return f"{year}Q{quarter}"


def _period_sort_key(period: str) -> tuple[int, int]:
    match = re.match(r"^(20\d{2})(Q([1-4])|FY)$", str(period or ""))
    if not match:
        return (0, 0)
    year = int(match.group(1))
    token = match.group(2)
    if token == "FY":
        return (year, 0)
    quarter = int(match.group(3) or 0)
    return (year, quarter)


def _price_from_raw(value: Any, decimals: int) -> Optional[float]:
    raw = safe_float(value)
    if raw is None:
        return None
    scale = 10 ** max(0, min(decimals, 6))
    if scale <= 0:
        scale = 100
    return raw / scale


def _percent_div_100(value: Any) -> Optional[float]:
    raw = safe_float(value)
    if raw is None:
        return None
    return raw / 100.0


def _has_any_metric(result: dict[str, Any], metric_fields: tuple[str, ...]) -> bool:
    for field in metric_fields:
        values = result.get(field) or []
        if any(v is not None for v in values):
            return True
    return False


def fetch_cn_hk_quote_metrics(ticker: str) -> dict[str, Any] | None:
    ticker_norm = normalize_ticker(ticker)
    market = detect_market(ticker_norm)
    if market not in {"CN", "HK"}:
        return None

    secid = ticker_to_eastmoney_secid(ticker_norm)
    if not secid:
        return None

    payload = _eastmoney_get_json(
        _EASTMONEY_QUOTE_URL,
        {
            "secid": secid,
            "fields": "f43,f57,f58,f59,f116,f162,f167,f170,f168,f169,f174,f175",
        },
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None

    decimals = int(safe_float(data.get("f59")) or 2)
    result = {
        "symbol": ticker_norm,
        "market": market,
        "name": str(data.get("f58") or "").strip() or ticker_norm,
        "last_price": _price_from_raw(data.get("f43"), decimals),
        "market_cap": safe_float(data.get("f116")),
        "trailing_pe": _percent_div_100(data.get("f162")),
        "forward_pe": None,
        "price_to_book": _percent_div_100(data.get("f167")),
        "price_to_sales": None,
        "ev_to_ebitda": None,
        "dividend_yield": None,
        "beta": None,
        "week52_high": _price_from_raw(data.get("f174"), decimals),
        "week52_low": _price_from_raw(data.get("f175"), decimals),
        "source": "eastmoney_quote",
    }
    if all(
        result.get(key) is None
        for key in (
            "last_price",
            "market_cap",
            "trailing_pe",
            "price_to_book",
            "week52_high",
            "week52_low",
        )
    ):
        return None
    return result


def fetch_cn_hk_kline(ticker: str, *, limit: int = 260, klt: str = "101", fqt: str = "1") -> list[dict[str, Any]]:
    ticker_norm = normalize_ticker(ticker)
    market = detect_market(ticker_norm)
    if market not in {"CN", "HK"}:
        return []

    secid = ticker_to_eastmoney_secid(ticker_norm)
    if not secid:
        return []

    payload = _eastmoney_get_json(
        _EASTMONEY_KLINE_URL,
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": str(klt),
            "fqt": str(fqt),
            "lmt": str(max(1, min(int(limit), 1200))),
            "end": "20500101",
        },
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    klines = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(klines, list):
        return []

    output: list[dict[str, Any]] = []
    for raw in klines:
        parts = str(raw or "").split(",")
        if len(parts) < 6:
            continue
        output.append(
            {
                "time": parts[0],
                "open": safe_float(parts[1]),
                "close": safe_float(parts[2]),
                "high": safe_float(parts[3]),
                "low": safe_float(parts[4]),
                "volume": safe_float(parts[5]),
            }
        )
    return output


def _fetch_finance_rows(report_name: str, secu_code: str, limit: int) -> list[dict[str, Any]]:
    payload = _eastmoney_get_json(
        _EASTMONEY_FINANCIAL_URL,
        {
            "reportName": report_name,
            "columns": "ALL",
            "pageNumber": "1",
            "pageSize": str(max(1, min(limit, 20))),
            "sortTypes": "-1",
            "sortColumns": "REPORT_DATE",
            "source": "F10",
            "client": "PC",
            "filter": f'(SECUCODE="{secu_code}")',
        },
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    return rows if isinstance(rows, list) else []


def fetch_cn_hk_financial_statements(ticker: str, periods: int = 8) -> dict[str, Any] | None:
    ticker_norm = normalize_ticker(ticker)
    market = detect_market(ticker_norm)
    if market not in {"CN", "HK"}:
        return None

    secu_code = ticker_to_secu_code(ticker_norm)
    if not secu_code:
        return None

    target_periods = max(1, min(int(periods), 12))
    rows_by_period: dict[str, dict[str, Any]] = {}

    if market == "CN":
        income_rows = _fetch_finance_rows("RPT_F10_FINANCE_GINCOME", secu_code, target_periods + 3)
        balance_rows = _fetch_finance_rows("RPT_F10_FINANCE_GBALANCE", secu_code, target_periods + 3)
        cash_rows = _fetch_finance_rows("RPT_F10_FINANCE_GCASHFLOW", secu_code, target_periods + 3)

        for row in income_rows:
            if not isinstance(row, dict):
                continue
            period = _period_label(row.get("REPORT_DATE"), row.get("REPORT_TYPE"))
            if not period:
                continue
            entry = rows_by_period.setdefault(period, {})
            entry["revenue"] = safe_float(row.get("TOTAL_OPERATE_INCOME") or row.get("OPERATE_INCOME"))
            entry["gross_profit"] = safe_float(row.get("GROSS_PROFIT"))
            entry["operating_income"] = safe_float(row.get("OPERATE_PROFIT"))
            entry["net_income"] = safe_float(row.get("PARENT_NETPROFIT") or row.get("NETPROFIT"))
            entry["eps"] = safe_float(row.get("BASIC_EPS"))

        for row in balance_rows:
            if not isinstance(row, dict):
                continue
            period = _period_label(row.get("REPORT_DATE"), row.get("REPORT_TYPE"))
            if not period:
                continue
            entry = rows_by_period.setdefault(period, {})
            entry["total_assets"] = safe_float(row.get("TOTAL_ASSETS"))
            entry["total_liabilities"] = safe_float(row.get("TOTAL_LIABILITIES"))

        for row in cash_rows:
            if not isinstance(row, dict):
                continue
            period = _period_label(row.get("REPORT_DATE"), row.get("REPORT_TYPE"))
            if not period:
                continue
            entry = rows_by_period.setdefault(period, {})
            ocf = safe_float(row.get("NETCASH_OPERATE"))
            entry["operating_cash_flow"] = ocf
            free_cash_flow = safe_float(row.get("FREE_CASH_FLOW"))
            if free_cash_flow is None and ocf is not None:
                capex = safe_float(row.get("INVESTPAYCASH") or row.get("CONSTRUCT_LONG_ASSET"))
                if capex is not None:
                    free_cash_flow = ocf - capex if capex > 0 else ocf + capex
            entry["free_cash_flow"] = free_cash_flow
    else:
        hk_rows = _fetch_finance_rows("RPT_HKF10_FN_MAININDICATOR", secu_code, target_periods + 3)
        for row in hk_rows:
            if not isinstance(row, dict):
                continue
            period = _period_label(row.get("REPORT_DATE"), row.get("REPORT_TYPE"))
            if not period:
                continue
            entry = rows_by_period.setdefault(period, {})
            entry["revenue"] = safe_float(row.get("OPERATE_INCOME"))
            entry["gross_profit"] = safe_float(row.get("GROSS_PROFIT"))
            entry["operating_income"] = safe_float(row.get("OPERATE_PROFIT"))
            entry["net_income"] = safe_float(row.get("HOLDER_PROFIT") or row.get("NETPROFIT"))
            entry["eps"] = safe_float(row.get("BASIC_EPS"))
            entry["total_assets"] = safe_float(row.get("TOTAL_ASSETS"))
            entry["total_liabilities"] = safe_float(row.get("TOTAL_LIABILITIES"))
            entry["operating_cash_flow"] = safe_float(row.get("NETCASH_OPERATE"))
            entry["free_cash_flow"] = safe_float(row.get("FREE_CASH_FLOW"))

    if not rows_by_period:
        return None

    period_labels = sorted(rows_by_period.keys(), key=_period_sort_key, reverse=True)[:target_periods]
    if not period_labels:
        return None

    result: dict[str, Any] = {
        "periods": period_labels,
        "revenue": [rows_by_period.get(period, {}).get("revenue") for period in period_labels],
        "gross_profit": [rows_by_period.get(period, {}).get("gross_profit") for period in period_labels],
        "operating_income": [rows_by_period.get(period, {}).get("operating_income") for period in period_labels],
        "net_income": [rows_by_period.get(period, {}).get("net_income") for period in period_labels],
        "eps": [rows_by_period.get(period, {}).get("eps") for period in period_labels],
        "total_assets": [rows_by_period.get(period, {}).get("total_assets") for period in period_labels],
        "total_liabilities": [rows_by_period.get(period, {}).get("total_liabilities") for period in period_labels],
        "operating_cash_flow": [rows_by_period.get(period, {}).get("operating_cash_flow") for period in period_labels],
        "free_cash_flow": [rows_by_period.get(period, {}).get("free_cash_flow") for period in period_labels],
        "source": "eastmoney_financials",
        "market": market,
    }
    metric_fields = (
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps",
        "total_assets",
        "total_liabilities",
        "operating_cash_flow",
        "free_cash_flow",
    )
    return result if _has_any_metric(result, metric_fields) else None


__all__ = [
    "detect_market",
    "normalize_ticker",
    "ticker_to_eastmoney_secid",
    "ticker_to_secu_code",
    "fetch_cn_hk_quote_metrics",
    "fetch_cn_hk_kline",
    "fetch_cn_hk_financial_statements",
]
