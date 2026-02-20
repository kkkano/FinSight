from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

from .http import _http_get

logger = logging.getLogger(__name__)

_WAYBACK_AVAILABLE_API = "https://archive.org/wayback/available"
_WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"
_WAYBACK_SNAPSHOT_BASE = "https://web.archive.org/web"
_WAYBACK_TIMEOUT = int(os.getenv("WAYBACK_TIMEOUT", "15"))
_WAYBACK_MAX_CHARS = int(os.getenv("WAYBACK_MAX_CHARS", "12000"))
_WAYBACK_USER_AGENT = os.getenv("WAYBACK_USER_AGENT", "FinSight/1.0")


def _safe_iso8601(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return raw


def _normalize_domain(url: str) -> str:
    try:
        return urlparse(str(url or "").strip().lower()).netloc.lstrip("www.")
    except Exception:
        return ""


def _extract_text(content: str, content_type: str) -> str:
    raw = str(content or "")
    if not raw:
        return ""
    if "html" not in str(content_type or "").lower():
        text = raw
    else:
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _resolve_via_available(url: str, timeout: int) -> dict[str, Any] | None:
    try:
        resp = _http_get(
            _WAYBACK_AVAILABLE_API,
            params={"url": url},
            timeout=timeout,
            headers={"User-Agent": _WAYBACK_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) != 200:
            return None
        payload = resp.json() if hasattr(resp, "json") else json.loads(resp.text)
    except Exception:
        return None

    snapshots = payload.get("archived_snapshots") if isinstance(payload, dict) else None
    closest = snapshots.get("closest") if isinstance(snapshots, dict) else None
    if not isinstance(closest, dict):
        return None
    snapshot_url = str(closest.get("url") or "").strip()
    if not snapshot_url:
        return None
    status = str(closest.get("status") or "").strip()
    if status and not status.startswith("2"):
        return None
    timestamp = str(closest.get("timestamp") or "").strip()
    return {
        "snapshot_url": snapshot_url,
        "timestamp": timestamp or None,
        "published_date": _safe_iso8601(timestamp) if timestamp else None,
        "source": "wayback",
        "status": status or None,
        "domain": _normalize_domain(url),
    }


def _resolve_via_cdx(url: str, timeout: int, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,statuscode,mimetype",
        "filter": "statuscode:200",
        "limit": "1",
        "sort": "reverse",
    }
    if from_ts:
        params["from"] = from_ts
    if to_ts:
        params["to"] = to_ts
    try:
        resp = _http_get(
            _WAYBACK_CDX_API,
            params=params,
            timeout=timeout,
            headers={"User-Agent": _WAYBACK_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) != 200:
            return None
        payload = resp.json() if hasattr(resp, "json") else json.loads(resp.text)
    except Exception:
        return None

    if not isinstance(payload, list) or len(payload) < 2:
        return None
    headers = payload[0] if isinstance(payload[0], list) else []
    row = payload[1] if isinstance(payload[1], list) else []
    if not headers or not row:
        return None
    mapping = {str(headers[idx]): row[idx] for idx in range(min(len(headers), len(row)))}
    timestamp = str(mapping.get("timestamp") or "").strip()
    original = str(mapping.get("original") or url).strip()
    if not timestamp:
        return None
    snapshot_url = f"{_WAYBACK_SNAPSHOT_BASE}/{timestamp}/{original}"
    return {
        "snapshot_url": snapshot_url,
        "timestamp": timestamp,
        "published_date": _safe_iso8601(timestamp),
        "source": "wayback",
        "status": str(mapping.get("statuscode") or ""),
        "domain": _normalize_domain(original),
    }


def resolve_wayback_snapshot(
    url: str,
    *,
    timeout: int | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> dict[str, Any] | None:
    """Resolve the best available Wayback snapshot metadata for a URL."""
    target = str(url or "").strip()
    if not target.startswith(("http://", "https://")):
        return None
    timeout_s = int(timeout or _WAYBACK_TIMEOUT)

    available = _resolve_via_available(target, timeout_s)
    if available:
        return available
    return _resolve_via_cdx(target, timeout_s, from_ts=from_ts, to_ts=to_ts)


def fetch_via_wayback(url: str, *, timeout: int | None = None) -> Optional[str]:
    """Fetch archived page text via Wayback; returns None on any failure."""
    snapshot = resolve_wayback_snapshot(url, timeout=timeout)
    if not snapshot:
        return None
    snapshot_url = str(snapshot.get("snapshot_url") or "").strip()
    if not snapshot_url:
        return None
    try:
        resp = _http_get(
            snapshot_url,
            timeout=int(timeout or _WAYBACK_TIMEOUT),
            headers={"User-Agent": _WAYBACK_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) != 200:
            return None
        content_type = str(getattr(resp, "headers", {}).get("Content-Type", "")).lower()
        text = _extract_text(str(getattr(resp, "text", "") or ""), content_type)
        if len(text) < 80:
            return None
        return text[:_WAYBACK_MAX_CHARS]
    except Exception as exc:
        logger.debug("[Wayback] fetch failed for %s: %s", snapshot_url, exc)
        return None


__all__ = ["resolve_wayback_snapshot", "fetch_via_wayback"]
