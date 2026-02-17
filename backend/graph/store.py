# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from backend.services.memory import MemoryService

logger = logging.getLogger(__name__)

_DEFAULT_USER_ID = "default_user"
_RECENT_FOCUS_LIMIT = 10
_RECENT_FOCUS_LOAD_LIMIT = 3
_SUMMARY_MAX_LEN = 600
_MEMORY_INIT_FAILED = object()

_memory_service: MemoryService | object | None = None


def resolve_user_id(thread_id: str | None) -> str:
    raw = str(thread_id or "").strip()
    if not raw:
        return _DEFAULT_USER_ID
    parts = raw.split(":")
    if len(parts) >= 2:
        candidate = parts[1].strip()
        if candidate:
            return candidate
    return _DEFAULT_USER_ID


def _get_memory_service() -> MemoryService | None:
    global _memory_service
    if _memory_service is _MEMORY_INIT_FAILED:
        return None
    if _memory_service is not None:
        return _memory_service
    try:
        storage_path = os.getenv("MEMORY_STORAGE_PATH", "data/memory")
        _memory_service = MemoryService(storage_path=storage_path)
    except Exception as exc:
        logger.warning("[graph.store] init memory service failed: %s", exc)
        _memory_service = _MEMORY_INIT_FAILED
        return None
    return _memory_service


def _normalize_watchlist(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        symbol = item.strip().upper()
        if not symbol:
            continue
        result.append(symbol)
        if len(result) >= 20:
            break
    return result


def _extract_summary(state: dict[str, Any], report: dict[str, Any] | None) -> str:
    candidates: list[str] = []

    if isinstance(report, dict):
        for key in ("summary", "investment_summary", "conclusion"):
            value = report.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        sections = report.get("sections")
        if isinstance(sections, list):
            for item in sections:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    candidates.append(content.strip())
                    break

    artifacts = state.get("artifacts") if isinstance(state, dict) else None
    if isinstance(artifacts, dict):
        render_vars = artifacts.get("render_vars")
        if isinstance(render_vars, dict):
            for key in ("investment_summary", "conclusion", "analysis"):
                value = render_vars.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
        draft_markdown = artifacts.get("draft_markdown")
        if isinstance(draft_markdown, str) and draft_markdown.strip():
            candidates.append(draft_markdown.strip())

    for text in candidates:
        normalized = " ".join(text.split())
        if normalized:
            return normalized[:_SUMMARY_MAX_LEN]
    return ""


def _extract_ticker(state: dict[str, Any], report: dict[str, Any] | None) -> str | None:
    subject = state.get("subject") if isinstance(state, dict) else None
    if isinstance(subject, dict):
        tickers = subject.get("tickers")
        if isinstance(tickers, list):
            for item in tickers:
                if isinstance(item, str) and item.strip():
                    return item.strip().upper()

    if isinstance(report, dict):
        ticker = report.get("ticker")
        if isinstance(ticker, str) and ticker.strip():
            return ticker.strip().upper()
    return None


def load_memory_context(
    *,
    thread_id: str | None,
    memory_service: MemoryService | None = None,
) -> dict[str, Any]:
    service = memory_service or _get_memory_service()
    if service is None:
        return {}

    user_id = resolve_user_id(thread_id)
    try:
        profile = service.get_user_profile(user_id)
    except Exception as exc:
        logger.warning("[graph.store] load profile failed user=%s: %s", user_id, exc)
        return {}

    preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
    last_focus = preferences.get("last_focus")
    if not isinstance(last_focus, dict):
        last_focus = None

    recent_focuses_raw = preferences.get("recent_focuses")
    recent_focuses: list[dict[str, Any]] = []
    if isinstance(recent_focuses_raw, list):
        for item in recent_focuses_raw:
            if isinstance(item, dict):
                recent_focuses.append(item)
            if len(recent_focuses) >= _RECENT_FOCUS_LOAD_LIMIT:
                break

    return {
        "user_id": user_id,
        "risk_tolerance": profile.risk_tolerance,
        "investment_style": profile.investment_style,
        "watchlist": _normalize_watchlist(profile.watchlist),
        "last_focus": last_focus,
        "recent_focuses": recent_focuses,
    }


def persist_memory_snapshot(
    *,
    thread_id: str | None,
    state: dict[str, Any],
    report: dict[str, Any] | None = None,
    memory_service: MemoryService | None = None,
) -> bool:
    service = memory_service or _get_memory_service()
    if service is None:
        return False

    user_id = resolve_user_id(thread_id)
    try:
        profile = service.get_user_profile(user_id)
    except Exception as exc:
        logger.warning("[graph.store] load profile before persist failed user=%s: %s", user_id, exc)
        return False

    summary = _extract_summary(state, report)
    query = str(state.get("query") or "").strip()
    ticker = _extract_ticker(state, report)

    if not summary and not query and not ticker:
        return False

    preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
    existing_recent = preferences.get("recent_focuses")
    existing_list = existing_recent if isinstance(existing_recent, list) else []

    focus_entry: dict[str, Any] = {
        "ticker": ticker,
        "query": query,
        "summary": summary,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(report, dict):
        sentiment = report.get("sentiment")
        if isinstance(sentiment, str) and sentiment.strip():
            focus_entry["sentiment"] = sentiment.strip()

    dedup_recent: list[dict[str, Any]] = [focus_entry]
    for item in existing_list:
        if not isinstance(item, dict):
            continue
        if ticker and str(item.get("ticker") or "").strip().upper() == ticker:
            continue
        dedup_recent.append(item)
        if len(dedup_recent) >= _RECENT_FOCUS_LIMIT:
            break

    preferences["last_focus"] = focus_entry
    preferences["recent_focuses"] = dedup_recent
    profile.preferences = preferences

    try:
        return bool(service.update_user_profile(profile))
    except Exception as exc:
        logger.warning("[graph.store] persist profile failed user=%s: %s", user_id, exc)
        return False


__all__ = [
    "load_memory_context",
    "persist_memory_snapshot",
    "resolve_user_id",
]
