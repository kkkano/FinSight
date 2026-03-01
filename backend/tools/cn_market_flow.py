from __future__ import annotations

import logging
import os
from typing import Any

from backend.tools.http import _http_get
from backend.utils.quote import safe_float

logger = logging.getLogger(__name__)

_EASTMONEY_USER_AGENT = os.getenv("EASTMONEY_USER_AGENT", "Mozilla/5.0 (FinSight)")
_EASTMONEY_TIMEOUT = int(os.getenv("EASTMONEY_TIMEOUT", "12"))
_EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def _eastmoney_list(*, fs: str, fields: str, limit: int = 20) -> list[dict[str, Any]]:
    params = {
        "pn": "1",
        "pz": str(max(1, min(int(limit), 200))),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": fs,
        "fields": fields,
    }
    try:
        resp = _http_get(
            _EASTMONEY_LIST_URL,
            params=params,
            timeout=_EASTMONEY_TIMEOUT,
            headers={"User-Agent": _EASTMONEY_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) != 200:
            return []
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("diff") if isinstance(data, dict) else None
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        logger.info("cn market eastmoney list failed: %s", exc)
        return []


def _build_symbol(row: dict[str, Any]) -> str:
    code = str(row.get("f12") or "").strip()
    market_id = str(row.get("f13") or "").strip()
    if not code:
        return ""
    if market_id == "1":
        return f"{code}.SH"
    if market_id == "0":
        return f"{code}.SZ"
    return code


def fetch_fund_flow(*, limit: int = 20) -> dict[str, Any]:
    """Fetch A-share fund flow list from Eastmoney snapshot endpoint."""
    rows = _eastmoney_list(
        fs="m:0+t:6,m:1+t:2",
        fields="f12,f13,f14,f2,f3,f62,f184",
        limit=limit,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _build_symbol(row)
        if not symbol:
            continue
        items.append(
            {
                "symbol": symbol,
                "name": str(row.get("f14") or "").strip() or symbol,
                "last_price": safe_float(row.get("f2")),
                "change_percent": safe_float(row.get("f3")),
                "main_net_inflow": safe_float(row.get("f62")),
                "main_net_inflow_ratio": safe_float(row.get("f184")),
            }
        )

    return {
        "success": True,
        "items": items,
        "count": len(items),
        "source": "eastmoney_clist",
        "market": "CN",
    }


def fetch_northbound(*, limit: int = 20) -> dict[str, Any]:
    """Fetch northbound-related ranking via Eastmoney snapshot endpoint."""
    rows = _eastmoney_list(
        fs="m:90+t:2",
        fields="f12,f13,f14,f2,f3,f62,f184",
        limit=limit,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _build_symbol(row) or str(row.get("f12") or "").strip()
        if not symbol:
            continue
        items.append(
            {
                "symbol": symbol,
                "name": str(row.get("f14") or "").strip() or symbol,
                "last_price": safe_float(row.get("f2")),
                "change_percent": safe_float(row.get("f3")),
                "northbound_net": safe_float(row.get("f62")),
                "northbound_ratio": safe_float(row.get("f184")),
            }
        )

    return {
        "success": True,
        "items": items,
        "count": len(items),
        "source": "eastmoney_clist",
        "market": "CN",
    }


__all__ = ["fetch_fund_flow", "fetch_northbound"]
