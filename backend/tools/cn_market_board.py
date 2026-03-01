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
_EASTMONEY_DATA_CENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


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
        logger.info("cn market board list failed: %s", exc)
        return []


def fetch_limit_board(*, limit: int = 20) -> dict[str, Any]:
    """Fetch limit-up board style ranking from Eastmoney list endpoint."""
    rows = _eastmoney_list(
        fs="m:0+t:4,m:1+t:4",
        fields="f12,f14,f2,f3,f8,f10,f62",
        limit=limit,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("f12") or "").strip()
        if not code:
            continue
        items.append(
            {
                "symbol": code,
                "name": str(row.get("f14") or "").strip() or code,
                "last_price": safe_float(row.get("f2")),
                "change_percent": safe_float(row.get("f3")),
                "turnover_rate": safe_float(row.get("f8")),
                "volume_ratio": safe_float(row.get("f10")),
                "main_net_inflow": safe_float(row.get("f62")),
            }
        )

    return {
        "success": True,
        "items": items,
        "count": len(items),
        "source": "eastmoney_clist",
        "market": "CN",
    }


def fetch_lhb(*, limit: int = 20) -> dict[str, Any]:
    """Fetch LongHuBang-like list from Eastmoney datacenter endpoint."""
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": str(max(1, min(int(limit), 100))),
        "sortTypes": "-1",
        "sortColumns": "TRADE_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    items: list[dict[str, Any]] = []
    try:
        resp = _http_get(
            _EASTMONEY_DATA_CENTER_URL,
            params=params,
            timeout=_EASTMONEY_TIMEOUT,
            headers={"User-Agent": _EASTMONEY_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) == 200:
            payload = resp.json()
            result = payload.get("result") if isinstance(payload, dict) else None
            rows = result.get("data") if isinstance(result, dict) else None
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    symbol = str(row.get("SECURITY_CODE") or "").strip()
                    if not symbol:
                        continue
                    items.append(
                        {
                            "symbol": symbol,
                            "name": str(row.get("SECURITY_NAME_ABBR") or "").strip() or symbol,
                            "trade_date": row.get("TRADE_DATE"),
                            "close_price": safe_float(row.get("CLOSE_PRICE")),
                            "change_percent": safe_float(row.get("CHANGE_RATE")),
                            "net_buy": safe_float(row.get("NET_BUY_AMT")),
                            "buy_amt": safe_float(row.get("BUY_AMT")),
                            "sell_amt": safe_float(row.get("SELL_AMT")),
                            "reason": row.get("EXPLAIN"),
                        }
                    )
    except Exception as exc:
        logger.info("fetch_lhb failed: %s", exc)

    return {
        "success": True,
        "items": items,
        "count": len(items),
        "source": "eastmoney_datacenter",
        "market": "CN",
    }


__all__ = ["fetch_limit_board", "fetch_lhb"]
