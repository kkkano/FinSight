from __future__ import annotations

import logging
import os
from typing import Optional

from .http import _http_get

logger = logging.getLogger(__name__)

_JINA_BASE = os.getenv("JINA_READER_BASE_URL", "https://r.jina.ai/")
_JINA_TIMEOUT = int(os.getenv("JINA_READER_TIMEOUT", "15"))
_JINA_MAX_CHARS = int(os.getenv("JINA_READER_MAX_CHARS", "12000"))
_JINA_MIN_CHARS = int(os.getenv("JINA_READER_MIN_CHARS", "50"))


def fetch_via_jina(url: str, *, timeout: int | None = None) -> Optional[str]:
    """Fetch markdown-like content via Jina Reader.

    Returns None on any failure path and never raises.
    """
    target = str(url or "").strip()
    if not target.startswith(("http://", "https://")):
        return None

    # Jina cannot help with google rss wrapper links.
    if "news.google.com" in target:
        return None

    try:
        resp = _http_get(
            f"{_JINA_BASE}{target}",
            headers={
                "Accept": "text/plain",
                "User-Agent": "FinSight/1.0 (+https://github.com/finsight)",
            },
            timeout=timeout or _JINA_TIMEOUT,
        )
        if getattr(resp, "status_code", 0) != 200:
            return None
        text = str(getattr(resp, "text", "") or "").strip()
        if len(text) < _JINA_MIN_CHARS:
            return None
        return text[:_JINA_MAX_CHARS]
    except Exception as exc:  # pragma: no cover - best effort fallback
        logger.debug("[JinaReader] fetch failed for %s: %s", target, exc)
        return None
