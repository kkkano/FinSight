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


def fetch_concept_map(*, keyword: str = "", limit: int = 20) -> dict[str, Any]:
    """Fetch concept board list and apply keyword filter."""
    params = {
        "pn": "1",
        "pz": str(max(1, min(int(limit), 200))),
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:3",
        "fields": "f12,f14,f2,f3,f62,f104,f105",
    }
    rows: list[dict[str, Any]] = []
    try:
        resp = _http_get(
            _EASTMONEY_LIST_URL,
            params=params,
            timeout=_EASTMONEY_TIMEOUT,
            headers={"User-Agent": _EASTMONEY_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) == 200:
            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            diff = data.get("diff") if isinstance(data, dict) else None
            if isinstance(diff, list):
                rows = [item for item in diff if isinstance(item, dict)]
    except Exception as exc:
        logger.info("fetch_concept_map failed: %s", exc)

    kw = str(keyword or "").strip().lower()
    items: list[dict[str, Any]] = []
    for row in rows:
        concept_name = str(row.get("f14") or "").strip()
        if kw and kw not in concept_name.lower():
            continue
        concept_code = str(row.get("f12") or "").strip()
        if not concept_code:
            continue
        items.append(
            {
                "concept_code": concept_code,
                "concept_name": concept_name or concept_code,
                "change_percent": safe_float(row.get("f3")),
                "main_net_inflow": safe_float(row.get("f62")),
                "up_count": safe_float(row.get("f104")),
                "down_count": safe_float(row.get("f105")),
            }
        )

    return {
        "success": True,
        "keyword": keyword,
        "items": items,
        "count": len(items),
        "source": "eastmoney_concept_board",
        "market": "CN",
    }


__all__ = ["fetch_concept_map"]
