"""供应商结构字段转换；异常正文、用户原话均不参与失败判断。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from urllib.parse import urlsplit

from ..envelope import Source, ToolError, ToolResult
from ..diagnostics import error_info, safe_code
from .catalog import TOOL_KINDS, TOOL_LABEL_ALIASES, TOOL_LABELS


def timestamp(value):
    if isinstance(value, datetime):
        return value
    # 只有日期的供应商值保留在 data，不伪造午夜的观测时间。
    if not isinstance(value, str) or len(value) <= 10:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _source(item, default_title):
    if not isinstance(item, dict):
        return None
    url = item.get("url") or item.get("source_url") or item.get("link") or item.get("final_url")
    if not isinstance(url, str) or urlsplit(url).scheme not in {"https", "http"}:
        url = None
    publisher = item.get("publisher") or item.get("source") or item.get("source_name") or item.get("provider")
    if not isinstance(publisher, str):
        publisher = None
    title = item.get("title") or item.get("headline") or publisher or default_title
    if not url and not publisher and not item.get("title") and not item.get("headline"):
        return None
    return Source(title=str(title), publisher=publisher, url=url,
                  published_at=timestamp(item.get("published_at") or item.get("published_date")
                                         or item.get("publishedDate")))


def _sources(raw, name):
    from ..diagnostics import TOOL_TITLES
    title = TOOL_LABELS.get(name) or TOOL_TITLES.get(TOOL_LABEL_ALIASES.get(name, name), "研究资料")
    candidates = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    if isinstance(raw, dict):
        for field in ("sources", "news", "articles", "results", "filings", "items", "transcripts"):
            if isinstance(raw.get(field), list):
                candidates = [*candidates, *raw[field]]
    result, seen = [], set()
    for item in candidates:
        source = _source(item, title)
        if source is None:
            continue
        key = (source.title, source.publisher, source.url, source.published_at)
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


def error_result(name, code, raw=None, *, retryable=False):
    info = error_info("tool_timeout" if code == "provider_timeout" else code)
    return ToolResult(status="error", kind=TOOL_KINDS[name], data=deepcopy(raw),
        error=ToolError(code=safe_code(code), user_message=info["reason"], retryable=retryable,
                        suggestion=info["recovery_action"]))


def adapt_result(name, raw, arguments=None) -> ToolResult:
    if name not in TOOL_KINDS:
        raise ValueError("tool_adapter_not_registered")
    if isinstance(raw, ToolResult):
        return raw.model_copy(deep=True)
    if (isinstance(raw, dict) and raw.get("status") in {"ok", "empty", "error"}
            and raw.get("kind") in set(TOOL_KINDS.values())
            and set(("status", "kind", "data", "sources", "notes", "error")).issubset(raw)):
        return ToolResult.model_validate(raw).model_copy(deep=True)
    if isinstance(raw, BaseException):
        code = "provider_timeout" if isinstance(raw, TimeoutError) else getattr(raw, "code", "tool_provider_error")
        return error_result(name, code, retryable=isinstance(raw, TimeoutError))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            if TOOL_KINDS[name] not in {"document", "control"}:
                return error_result(name, "unsupported_payload", raw)
    if not isinstance(raw, (dict, list)) and TOOL_KINDS[name] not in {"document", "control"}:
        return error_result(name, "unsupported_payload", raw)
    if raw is None or raw == [] or raw == {} or raw == "":
        return ToolResult(status="empty", kind=TOOL_KINDS[name], data=deepcopy(raw))
    declared = raw.get("status") if isinstance(raw, dict) else None
    code = raw.get("error_code") or raw.get("error") if isinstance(raw, dict) else None
    if declared in {"error", "failed", "unavailable"} or (code and declared not in {"ok", "success"}):
        if isinstance(code, dict):
            code = code.get("code")
        code = code if isinstance(code, str) else "tool_provider_error"
        retryable = raw.get("retryable") is True or code in {"provider_timeout", "tool_timeout", "model_http_429"}
        return error_result(name, code, raw, retryable=retryable)
    status = "empty" if declared in {"empty", "no_results"} else "ok"
    if name == "inspect_dataset" and isinstance(raw, dict) and type(raw.get("total")) is int:
        raw = {**raw, "row_count": raw["total"]}
    notes = []
    if isinstance(raw, dict):
        for field in ("notes", "warnings", "limitations"):
            if isinstance(raw.get(field), list):
                notes.extend(item for item in raw[field] if isinstance(item, str))
        if raw.get("source") == "sec_companyfacts":
            notes.append("latest_filing_fiscal_context 仅对应其中的 period_end；source_latest_filed 是整份 CompanyFacts 的最晚事实申报日，不代表选中季度重新申报或本次抓取时间。")
        if TOOL_KINDS[name] in {"quote", "series"}:
            notes.append("freshness_seconds 是数据龄")
            quote = raw.get("data") if TOOL_KINDS[name] == "quote" and isinstance(raw.get("data"), dict) else raw
            if quote.get("delay_seconds") is None:
                notes.append("延迟未知，不能表述为实时")
    return ToolResult(status=status, kind=TOOL_KINDS[name], data=deepcopy(raw),
        sources=[] if TOOL_KINDS[name] == "control" else _sources(raw, name),
        as_of=timestamp(raw.get("as_of") or raw.get("source_timestamp")) if isinstance(raw, dict) else None,
        notes=list(dict.fromkeys(notes)))
