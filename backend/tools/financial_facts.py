"""金融事实的主体、期间、单位与会计定义合同；纯函数，不执行外部取数。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
import re
from typing import Any


def fact_date(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def fact_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_currency(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z]{3}", raw):
        return None
    return raw if raw == "GBp" else raw.upper()


@dataclass(frozen=True)
class MonetaryAmount:
    value: float | None
    currency: str | None


def monetary_amount(value: Any, currency: Any, *, scale: float = 1.0) -> MonetaryAmount:
    number = fact_number(value)
    return MonetaryAmount(fact_number(number * scale) if number is not None else None, normalize_currency(currency))


def market_cap_lines(value: Any, currency: Any, *, scale: float = 1.0) -> str:
    amount = monetary_amount(value, currency, scale=scale)
    currency_line = f"- Currency: {amount.currency}" if amount.currency else "- Currency: [数据缺失] 市场报价币种未核验"
    if amount.value is None or amount.value <= 0:
        cap_line = "- Market Cap: [数据缺失] 市值不可用"
    elif not amount.currency:
        cap_line = "- Market Cap: [数据缺失] 市值币种未核验，未将数值标为美元"
    else:
        cap_line = f"- Market Cap: {amount.currency} {amount.value:,.0f}"
    return f"{cap_line}\n{currency_line}"


def parse_profile_market_cap(payload: Any) -> MonetaryAmount:
    if isinstance(payload, dict):
        value = next((payload[key] for key in ("market_cap", "marketCap", "MarketCapitalization", "marketCapitalization") if key in payload), None)
        return monetary_amount(value, payload.get("market_cap_currency") or payload.get("currency") or payload.get("Currency"))
    if not isinstance(payload, str):
        return MonetaryAmount(None, None)
    currency_match = re.search(r"(?:^|\n)\s*-?\s*Currency\s*:\s*([A-Za-z]{3})\s*(?:\n|$)", payload, re.IGNORECASE)
    currency = normalize_currency(currency_match.group(1)) if currency_match else None
    cap_match = re.search(r"(?:^|\n)\s*-?\s*Market (?:Cap|Capitalization)\s*:\s*(?:([A-Za-z]{3})\s+|\$)?([\d,.]+)\s*([KMBT])?\s*(?:\n|$)", payload, re.IGNORECASE)
    if not cap_match:
        return MonetaryAmount(None, currency)
    inline_currency = normalize_currency(cap_match.group(1))
    if inline_currency and currency and inline_currency != currency:
        return MonetaryAmount(None, None)
    scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get((cap_match.group(3) or "").upper(), 1.0)
    return monetary_amount(cap_match.group(2).replace(",", ""), inline_currency or currency, scale=scale)


def duration_frequency(start: Any, end: Any) -> str:
    start_date, end_date = fact_date(start), fact_date(end)
    if not start_date or not end_date:
        return "unknown"
    days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
    if 70 <= days <= 110:
        return "quarterly"
    if 330 <= days <= 380:
        return "annual"
    if 150 <= days <= 210:
        return "semiannual"
    return "unknown"


@dataclass(frozen=True)
class FinancialFact:
    subject: str
    metric: str
    value: float
    unit: str
    source: str
    period_end: str
    frequency: str
    period_start: str | None = None
    filed: str | None = None
    accession: str | None = None
    concept: str | None = None
    form: str | None = None
    source_url: str | None = None

    def metadata(self) -> dict[str, Any]:
        return asdict(self)


def statement_row(table: dict[str, Any], aliases: list[str]) -> dict[str, Any] | None:
    """别名优先级高于供应商行顺序；成本、EBITDA 和其他净利定义不能模糊命中。"""
    names, rows = table.get("index"), table.get("data")
    if not isinstance(names, list) or not isinstance(rows, list):
        return None
    normalized = [re.sub(r"\s+", " ", str(name).strip().lower()) for name in names]
    for alias in aliases:
        target = re.sub(r"\s+", " ", alias.strip().lower())
        if target in normalized:
            index = normalized.index(target)
            if index < len(rows) and isinstance(rows[index], dict):
                return rows[index]
    return None


def statement_dates(table: dict[str, Any]) -> list[str]:
    return sorted({parsed for col in (table.get("columns") or []) if (parsed := fact_date(col))}, reverse=True)


def statement_frequency(table: dict[str, Any], columns: list[str]) -> str:
    explicit = str(table.get("frequency") or "").lower()
    if explicit:
        return explicit if explicit in {"quarterly", "annual", "instant", "semiannual"} else "unknown"
    if len(columns) < 2:
        return "unknown"
    days = (date.fromisoformat(columns[0]) - date.fromisoformat(columns[1])).days
    if 70 <= days <= 110:
        return "quarterly"
    if 330 <= days <= 380:
        return "annual"
    return "unknown"


def comparison_point(series: list[dict[str, Any]], *, days: int, tolerance: int) -> dict[str, Any] | None:
    if not series or not (latest := fact_date(series[0].get("period"))):
        return None
    latest_date = date.fromisoformat(latest)
    candidates = [
        row for row in series[1:]
        if (point := fact_date(row.get("period")))
        and abs((latest_date - date.fromisoformat(point)).days - days) <= tolerance
    ]
    return min(candidates, key=lambda row: abs((latest_date - date.fromisoformat(row["period"])).days - days)) if candidates else None


def growth_rate(latest: Any, previous: Any) -> float | None:
    current, base = fact_number(latest), fact_number(previous)
    if current is None or base in {None, 0}:
        return None
    return (current - base) / abs(base)


def search_line_is_noise(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or not re.search(r"[\w\u4e00-\u9fff]", text):
        return True
    return bool(re.match(
        r"^(?:#{1,6}\s*)?(?:search results?|搜索结果|搜索来源|搜尋結果|latest news|news results?|"
        r"no (?:recent )?(?:search results?|news)|未找到|暂无(?:新闻|搜索结果)|来源列表)\b|"
        r"^(?:URL|Link|链接|網址|摘要|Snippet|Content)\s*[:：]?$",
        text, re.IGNORECASE,
    ))
