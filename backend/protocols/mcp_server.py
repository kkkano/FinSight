# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


_TRUE_VALUES = {"1", "true", "yes", "on"}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._\-:]{1,160}$")
_SENSITIVE_KEY_PARTS = (
    "trace",
    "secret",
    "password",
    "api_key",
    "apikey",
    "raw_internal",
    "diagnostic",
    "diagnostics",
)

OFFICIAL_MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None


Handler = Callable[..., Any]


def is_mcp_server_enabled() -> bool:
    """读取 MCP 协议适配器开关。"""
    return str(os.getenv("MCP_SERVER_ENABLED") or "false").strip().lower() in _TRUE_VALUES


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _text_property(description: str, *, min_length: int = 1) -> dict[str, Any]:
    return {"type": "string", "minLength": min_length, "description": description}


def _int_property(description: str, *, default: int, minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "integer",
        "default": default,
        "minimum": minimum,
        "maximum": maximum,
        "description": description,
    }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler_name: str
    open_world: bool = True

    def as_mcp_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": self.open_world,
            },
        }


def _generic_output_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": True}


def _tool_specs() -> tuple[ToolSpec, ...]:
    generic_output = _generic_output_schema()
    return (
        ToolSpec(
            name="research_company",
            description="读取指定 ticker 已保存的 FinSight 公司研究摘要。",
            input_schema=_schema(
                {
                    "ticker": _text_property("美股 ticker 或已知证券代码。"),
                    "session_id": _text_property("用于读取已保存报告的会话 ID。", min_length=0),
                    "limit": _int_property("最多返回的已保存报告数量。", default=5, minimum=1, maximum=25),
                },
                required=["ticker"],
            ),
            output_schema=generic_output,
            handler_name="research_company",
            open_world=False,
        ),
        ToolSpec(
            name="get_evidence_ledger",
            description="读取已保存报告的证据账本，缺失时返回引用派生账本。",
            input_schema=_schema(
                {
                    "session_id": _text_property("用于读取已保存报告的会话 ID。"),
                    "report_id": _text_property("已保存报告 ID。"),
                },
                required=["session_id", "report_id"],
            ),
            output_schema=generic_output,
            handler_name="get_evidence_ledger",
            open_world=False,
        ),
        ToolSpec(
            name="run_debate",
            description="基于证据账本生成无副作用的多空辩论 artifact。",
            input_schema=_schema(
                {
                    "ledger": {"type": "object", "description": "证据账本 payload。"},
                    "query": _text_property("辩论对应的问题或研究主题。", min_length=0),
                },
                required=["ledger"],
            ),
            output_schema=generic_output,
            handler_name="run_debate",
            open_world=False,
        ),
        ToolSpec(
            name="track_institutional_holdings",
            description="读取机构或 holder CIK 的公开 SEC 13F 持仓披露。",
            input_schema=_schema(
                {
                    "holder_cik_or_name": _text_property("机构 CIK、ticker 或 holder 名称。"),
                    "quarter": _text_property("可选季度，例如 2025Q1。", min_length=0),
                    "limit": _int_property("最多返回的持仓条数。", default=100, minimum=1, maximum=500),
                },
                required=["holder_cik_or_name"],
            ),
            output_schema=generic_output,
            handler_name="track_institutional_holdings",
        ),
        ToolSpec(
            name="get_insider_transactions",
            description="读取美股 ticker 的公开 SEC Form 4 内部人交易披露。",
            input_schema=_schema(
                {
                    "ticker": _text_property("美股 ticker。"),
                    "days": _int_property("回看天数。", default=180, minimum=1, maximum=730),
                    "limit": _int_property("最多返回的交易条数。", default=50, minimum=1, maximum=200),
                },
                required=["ticker"],
            ),
            output_schema=generic_output,
            handler_name="get_insider_transactions",
        ),
    )


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key or "").strip().lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(mode="json"))
        except Exception:
            return str(value)
    return str(value)


def _error_result(code: str, message: str, *, tool_name: str | None = None) -> dict[str, Any]:
    payload = {
        "isError": True,
        "error": {"code": code, "message": message},
    }
    if tool_name:
        payload["tool"] = tool_name
    payload["content"] = [{"type": "text", "text": message}]
    return payload


def _success_result(tool_name: str, result: Any) -> dict[str, Any]:
    structured = _json_safe(result)
    return {
        "isError": False,
        "tool": tool_name,
        "structuredContent": structured,
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured, ensure_ascii=False, sort_keys=True),
            }
        ],
    }


def _validate_id(value: Any, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(cleaned):
        raise ValueError(f"{field_name} format invalid")
    return cleaned


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_float(value: Any, default: float = 0.5) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _report_index_path() -> Path:
    return Path(os.getenv("REPORT_INDEX_SQLITE_PATH", "backend/data/report_index.sqlite")).resolve()


def _connect_report_index_readonly() -> sqlite3.Connection | None:
    path = _report_index_path()
    if not path.exists():
        return None
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _decode_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_ledger_from_report(report: dict[str, Any], *, citations: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[Any] = [
        report.get("evidence_ledger"),
        (report.get("meta") or {}).get("evidence_ledger") if isinstance(report.get("meta"), dict) else None,
        (report.get("report_hints") or {}).get("evidence_ledger") if isinstance(report.get("report_hints"), dict) else None,
    ]
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    hints = meta.get("report_hints") if isinstance(meta.get("report_hints"), dict) else {}
    candidates.append(hints.get("evidence_ledger"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate

    report_id = str(report.get("report_id") or "").strip()
    summary = str(report.get("summary") or "").strip()
    source_ids = [str(item.get("source_id") or "").strip() for item in citations if isinstance(item, dict)]
    source_ids = [source_id for source_id in source_ids if source_id]
    return {
        "ledger_id": f"report:{report_id}:citations",
        "query": str(report.get("title") or report.get("ticker") or "").strip(),
        "subject": {"ticker": str(report.get("ticker") or "").strip()},
        "claims": [
            {
                "claim_id": f"report:{report_id}:summary",
                "claim": summary or "Saved report exists, but no structured claim summary was stored.",
                "stance": "unknown",
                "evidence_ids": source_ids,
                "confidence": _safe_float(report.get("confidence_score")),
                "agent_name": "report_index",
                "task_ids": [],
                "limitations": ["Structured evidence ledger was not stored with this report."],
            }
        ],
        "sources": [
            {
                "source_id": str(item.get("source_id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "url": item.get("url"),
                "source": str(item.get("source_type") or "report_citation"),
                "published_date": item.get("published_date"),
                "reliability": _safe_float(item.get("confidence")),
            }
            for item in citations
            if isinstance(item, dict) and str(item.get("source_id") or "").strip()
        ],
        "uncertainties": [],
        "contradictions": [],
        "coverage_targets": [],
    }


def _read_report_replay(*, session_id: str, report_id: str) -> dict[str, Any] | None:
    session_id = _validate_id(session_id, "session_id")
    report_id = _validate_id(report_id, "report_id")
    conn = _connect_report_index_readonly()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT report_json
            FROM report_index
            WHERE session_id = ? AND report_id = ? AND publishable = 1
            """,
            (session_id, report_id),
        ).fetchone()
        if not row:
            return None
        citation_rows = conn.execute(
            """
            SELECT citation_json
            FROM citation_index
            WHERE session_id = ? AND report_id = ?
            ORDER BY row_id ASC
            """,
            (session_id, report_id),
        ).fetchall()
    finally:
        conn.close()

    report = _decode_json_object(row["report_json"])
    citations: list[dict[str, Any]] = []
    for citation_row in citation_rows:
        citation = _decode_json_object(citation_row["citation_json"])
        if citation:
            citations.append(citation)
    return {"report": report, "citations": citations}


def _research_company(*, ticker: str, session_id: str = "", limit: int = 5) -> dict[str, Any]:
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return {"error": "ticker_required", "message": "ticker is required"}
    session_id = str(session_id or "").strip()
    if not session_id:
        return {
            "ticker": ticker,
            "reports": [],
            "error": "session_id_required",
            "message": "Provide session_id to read saved company research.",
        }
    session_id = _validate_id(session_id, "session_id")
    limit_value = _bounded_int(limit, default=5, minimum=1, maximum=25)
    conn = _connect_report_index_readonly()
    if conn is None:
        return {
            "ticker": ticker,
            "reports": [],
            "error": "report_index_unavailable",
            "message": "No readable report index database is configured.",
        }
    try:
        rows = conn.execute(
            """
            SELECT report_id, ticker, title, summary, generated_at, confidence_score, tags_json
            FROM report_index
            WHERE session_id = ? AND ticker = ? AND publishable = 1
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            (session_id, ticker, limit_value),
        ).fetchall()
    finally:
        conn.close()

    reports: list[dict[str, Any]] = []
    for row in rows:
        tags: list[Any] = []
        try:
            parsed_tags = json.loads(row["tags_json"] or "[]")
            tags = parsed_tags if isinstance(parsed_tags, list) else []
        except Exception:
            tags = []
        reports.append(
            {
                "report_id": row["report_id"],
                "ticker": row["ticker"],
                "title": row["title"],
                "summary": row["summary"],
                "generated_at": row["generated_at"],
                "confidence_score": row["confidence_score"],
                "tags": tags,
            }
        )
    return {"ticker": ticker, "reports": reports, "count": len(reports), "error": None}


def _get_evidence_ledger(*, session_id: str, report_id: str) -> dict[str, Any]:
    replay = _read_report_replay(session_id=session_id, report_id=report_id)
    if replay is None:
        return {
            "report_id": str(report_id or "").strip(),
            "status": "not_found",
            "error": "report_not_found",
            "message": "No publishable saved report was found for this session and report_id.",
        }
    report = replay.get("report") if isinstance(replay.get("report"), dict) else {}
    citations = replay.get("citations") if isinstance(replay.get("citations"), list) else []
    ledger = _extract_ledger_from_report(report, citations=citations)
    return {
        "report_id": str(report.get("report_id") or report_id).strip(),
        "status": "found",
        "ledger": ledger,
        "source": "report_index",
        "error": None,
    }


def _run_debate(*, ledger: dict[str, Any], query: str = "") -> dict[str, Any]:
    from backend.research.debate import build_debate_artifact

    return build_debate_artifact(ledger, query=str(query or ""))


def _track_institutional_holdings(
    *,
    holder_cik_or_name: str = "",
    cik_or_name: str = "",
    quarter: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from backend.tools.sec_holdings import get_institutional_holdings

    holder = str(holder_cik_or_name or cik_or_name or "").strip()
    if not holder:
        return {"error": "holder_required", "message": "holder_cik_or_name is required"}
    return get_institutional_holdings(
        cik_or_name=holder,
        quarter=str(quarter).strip() if quarter else None,
        limit=_bounded_int(limit, default=100, minimum=1, maximum=500),
    )


def _get_insider_transactions(*, ticker: str, days: int = 180, limit: int = 50) -> dict[str, Any]:
    from backend.tools.sec_holdings import get_insider_transactions

    return get_insider_transactions(
        ticker=str(ticker or "").strip().upper(),
        days=_bounded_int(days, default=180, minimum=1, maximum=730),
        limit=_bounded_int(limit, default=50, minimum=1, maximum=200),
    )


def _default_handlers() -> dict[str, Handler]:
    return {
        "research_company": _research_company,
        "get_evidence_ledger": _get_evidence_ledger,
        "run_debate": _run_debate,
        "track_institutional_holdings": _track_institutional_holdings,
        "get_insider_transactions": _get_insider_transactions,
    }


def _call_handler(handler: Handler, arguments: Mapping[str, Any]) -> Any:
    signature = inspect.signature(handler)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return handler(**dict(arguments))
    filtered = {key: value for key, value in arguments.items() if key in signature.parameters}
    return handler(**filtered)


class ReadOnlyToolRegistry:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        handlers: Mapping[str, Handler] | None = None,
        specs: tuple[ToolSpec, ...] | None = None,
    ) -> None:
        self.enabled = is_mcp_server_enabled() if enabled is None else bool(enabled)
        self._specs = specs or _tool_specs()
        custom_handlers = dict(handlers or {})
        defaults = _default_handlers()
        self._handlers = {**defaults, **custom_handlers}
        self._specs_by_name = {spec.name: spec for spec in self._specs}

    def list_tools(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        return [spec.as_mcp_tool() for spec in self._specs]

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        tool_name = str(name or "").strip()
        if not self.enabled:
            return _error_result(
                "mcp_server_disabled",
                "MCP server 已关闭。设置 MCP_SERVER_ENABLED=true 后才会暴露只读研究工具。",
                tool_name=tool_name or None,
            )
        spec = self._specs_by_name.get(tool_name)
        if spec is None:
            return _error_result("unknown_tool", f"未知 MCP 工具：{tool_name}", tool_name=tool_name)
        handler = self._handlers.get(spec.handler_name)
        if handler is None:
            return _error_result("tool_unavailable", f"工具 handler 不可用：{tool_name}", tool_name=tool_name)
        try:
            result = _call_handler(handler, arguments or {})
        except ValueError as exc:
            return _error_result("invalid_arguments", str(exc), tool_name=tool_name)
        except Exception:
            return _error_result("tool_failed", "只读工具调用失败。", tool_name=tool_name)
        return _success_result(tool_name, result)


def build_tool_registry(
    *,
    enabled: bool | None = None,
    handlers: Mapping[str, Handler] | None = None,
) -> ReadOnlyToolRegistry:
    return ReadOnlyToolRegistry(enabled=enabled, handlers=handlers)


def list_mcp_tools() -> list[dict[str, Any]]:
    return build_tool_registry().list_tools()


def dispatch_tool_call(name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return build_tool_registry().call_tool(name, arguments or {})


__all__ = [
    "OFFICIAL_MCP_AVAILABLE",
    "ReadOnlyToolRegistry",
    "ToolSpec",
    "build_tool_registry",
    "dispatch_tool_call",
    "is_mcp_server_enabled",
    "list_mcp_tools",
]
