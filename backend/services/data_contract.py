"""数据的市场上下文、来源观测与缺失状态，不推断未知的源时间或币种。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar

T = TypeVar("T")
DataStatus = Literal["ok", "empty", "missing", "error", "degraded"]


@dataclass(frozen=True)
class AssetContext:
    symbol: str
    market: str
    exchange: str
    timezone: str
    calendar_name: str | None

    @classmethod
    def from_symbol(cls, symbol: str) -> "AssetContext":
        value = str(symbol or "").strip().upper()
        suffix = value.rsplit(".", 1)[-1] if "." in value else ""
        markets = {
            "SS": ("CN", "SSE", "Asia/Shanghai", "SSE"),
            "SH": ("CN", "SSE", "Asia/Shanghai", "SSE"),
            "SZ": ("CN", "SZSE", "Asia/Shanghai", "SSE"),
            "BJ": ("CN", "BSE", "Asia/Shanghai", "SSE"),
            "HK": ("HK", "HKEX", "Asia/Hong_Kong", "HKEX"),
        }
        if suffix in markets:
            return cls(value, *markets[suffix])
        if "-" in value and value.rsplit("-", 1)[-1] in {"USD", "USDT", "BTC", "ETH"}:
            return cls(value, "CRYPTO", "continuous", "UTC", None)
        if suffix and suffix not in {"A", "B"}:
            return cls(value, "UNKNOWN", "unknown", "UTC", None)
        return cls(value, "US", "US", "America/New_York", "NYSE")

    def metadata(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataResult(Generic[T]):
    data: T
    status: DataStatus
    provider: str | None = None
    as_of: str | None = None
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    currency: str | None = None
    frequency: str | None = None
    error_code: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: T) -> "DataResult[T]":
        source = payload if isinstance(payload, dict) else {}
        error = source.get("error_code") or source.get("error")
        if source.get("__dashboard_failure__"):
            error = source.get("reason") or "upstream_unavailable"
        raw_status = source.get("status")
        status: DataStatus = (
            "error" if error else raw_status if raw_status in {"ok", "empty", "missing", "error", "degraded"}
            else "missing" if payload is None else "empty" if not payload
            else "missing" if raw_status in {"unavailable", "data_unavailable"}
            else "degraded" if source.get("degraded") or raw_status == "partial" else "ok"
        )
        return cls(
            data=payload, status=status, provider=source.get("provider") or source.get("source"),
            as_of=source.get("as_of"), currency=source.get("currency"),
            frequency=source.get("frequency"), error_code=str(error) if error else None,
            observed_at=source.get("observed_at") or datetime.now(timezone.utc).isoformat(),
        )

    def metadata(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self) if item.name != "data"}
