"""统一工具信封及模型、界面投影；不理解或改写用户与模型正文。"""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ToolKind = Literal["quote", "series", "table", "news", "document", "computation", "chart", "control"]
ToolStatus = Literal["ok", "empty", "error"]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    publisher: str | None = None
    url: str | None = None
    published_at: datetime | None = None


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    user_message: str
    retryable: bool
    suggestion: str | None = None


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ToolStatus
    kind: ToolKind
    data: Any = None
    sources: list[Source] = Field(default_factory=list)
    as_of: datetime | None = None
    notes: list[str] = Field(default_factory=list)
    error: ToolError | None = None

    @model_validator(mode="after")
    def check_error_contract(self):
        if (self.status == "error") != (self.error is not None):
            raise ValueError("tool_error_status_mismatch")
        return self


_ROW_FIELDS = {
    "series": ("rows", "data", "kline_data", "bars", "prices", "historical", "observations"),
    "table": ("rows", "data", "holdings", "transactions", "filings", "items", "quarterly", "results", "events"),
    "news": ("news", "articles", "items", "results"),
    "document": ("results", "hits", "documents", "items"),
    "computation": ("rows", "episodes", "results"),
}
_METADATA_FIELDS = ("ticker", "asset", "currency", "unit", "column_units", "frequency", "period", "interval",
                    "as_of", "source_timestamp", "source_latest_filed", "price_basis", "dividends_included",
                    "source_time_precision", "source_time_status", "latest_filing_fiscal_context", "method")
_FIELD_LABELS = {"price": "价格", "change": "涨跌额", "change_percent": "涨跌幅", "currency": "货币",
                 "source_timestamp": "数据时间", "as_of": "数据时间", "frequency": "频率", "period": "期间"}


def result_rows(result: ToolResult) -> list[dict]:
    """先按注册 kind 分发，再读取该类型的有限供应商协议字段。"""
    data = result.data
    if isinstance(data, list):
        return data if all(isinstance(row, dict) for row in data) else []
    if not isinstance(data, dict):
        return []
    if result.kind == "table" and data.get("period_ends") and isinstance(data.get("revenue"), list):
        from .data import _companyfacts_rows
        return _companyfacts_rows(data)
    for key in _ROW_FIELDS.get(result.kind, ()):
        rows = data.get(key)
        if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
            return rows
    return []


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False)


def _cell(value: Any) -> str:
    text = _json(value) if isinstance(value, (dict, list)) else "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _table(rows: list[dict], columns: list[str], units=None) -> str:
    if not columns:
        return ""
    units = units or {}
    labels = [column + (" (" + _cell(units[column]) + ")" if column in units else "") for column in columns]
    lines = ["| " + " | ".join(_cell(label) for label in labels) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(_cell(row.get(column)) for column in columns) + " |" for row in rows)
    return "\n".join(lines)


def _prefix(text: str, budget: int) -> str:
    from .context import tokens
    if tokens(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if tokens(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _document_page(data: dict, lead: str, budget: int) -> str:
    """回读页的游标只按真正送给模型的原文字数前进。"""
    from .context import tokens
    content, offset, total = data["content"], data["offset"], data["total_chars"]
    def render(size):
        payload = {**data, "content": content[:size], "next_offset": offset + size,
                   "has_more": offset + size < total}
        return "\n\n".join(filter(None, [lead, _json(payload)]))
    low, high = 0, len(content)
    while low < high:
        middle = (low + high + 1) // 2
        if tokens(render(middle)) <= budget:
            low = middle
        else:
            high = middle - 1
    text = render(low)
    if tokens(text) <= budget:
        return text
    # 小预算不截断 JSON 或残留原游标；零字页明确表示没有推进。
    payload = _json({"content": "", "offset": offset, "total_chars": total,
                     "next_offset": offset, "has_more": offset < total})
    return payload if tokens(payload) <= budget else ""


def to_model(result: ToolResult | dict, budget: int, handle=None, source_ids=None) -> str:
    """模型只取得有界投影；分页不会修改信封和完整原始值。"""
    from .context import tokens
    result = ToolResult.model_validate(result)
    if type(budget) is not int or budget < 1:
        raise ValueError("invalid_tool_result_budget")
    header = [f"状态：{result.status}"]
    if result.as_of is not None:
        header.append("数据时点：" + result.as_of.isoformat())
    header.extend(result.notes)
    ids = list(source_ids or [])
    for index, source in enumerate(result.sources):
        number = f"[{ids[index]}] " if index < len(ids) else ""
        header.append(number + " · ".join(filter(None, [source.title, source.publisher, source.url])))
    if len(ids) > len(result.sources):
        header.append("来源编号：" + "、".join(f"[{number}]" for number in ids[len(result.sources):]))
    if result.status == "error":
        header.extend([result.error.user_message, result.error.suggestion or ""])
        if result.kind == "computation" and isinstance(result.data, dict):
            diagnostic = result.data.get("code_error")
            if isinstance(diagnostic, dict):
                details = {key: diagnostic[key] for key in ("type", "message", "line")
                           if isinstance(diagnostic.get(key), (str, int))}
                if details:
                    header.append("计算代码诊断：" + _json(details))
        return _prefix("\n".join(filter(None, header)), budget)
    data = result.data
    rows = result_rows(result)
    if isinstance(data, dict):
        header.extend(f"{key}：{_json(data[key])}" for key in _METADATA_FIELDS if key in data)
    lead = "\n".join(header)
    if (result.kind == "document" and isinstance(data, dict) and isinstance(data.get("content"), str)
            and type(data.get("offset")) is int and type(data.get("total_chars")) is int):
        return _document_page(data, lead, budget)
    if rows:
        # 分项申报元数据保存在完整资料；不把整份元数据塞成每行的一个巨型单元格。
        columns = list(dict.fromkeys(key for row in rows for key in row if key != "fact_metadata"))
        units = dict(data.get("column_units") or {}) if isinstance(data, dict) else {}
        if isinstance(data, dict):
            for field, details in (data.get("derived_fields") or {}).items():
                if isinstance(details, dict) and isinstance(details.get("unit"), str):
                    units.setdefault(field, details["unit"])
        for column in columns:
            declared = {row.get("fact_metadata", {}).get(column, {}).get("unit") for row in rows
                        if isinstance(row.get("fact_metadata"), dict)
                        and isinstance(row["fact_metadata"].get(column), dict)}
            if len(declared) == 1 and None not in declared:
                units.setdefault(column, next(iter(declared)))
        total = len(rows)
        if isinstance(data, dict) and type(data.get("row_count")) is int:
            total = max(total, data["row_count"])
        def render(count):
            note = f"共 {total} 行，已显示 {count} 行"
            if count < total and handle is not None:
                note += f"，句柄 {handle}，可用 read_data 读取其余部分"
            return "\n\n".join(filter(None, [lead, _table(rows[:count], columns, units), note]))
        low, high = 0, len(rows)
        while low < high:
            middle = (low + high + 1) // 2
            if tokens(render(middle)) <= budget:
                low = middle
            else:
                high = middle - 1
        return _prefix(render(low), budget)
    if result.kind == "quote" and isinstance(data, dict):
        quote = data.get("data") if isinstance(data.get("data"), dict) else data
        fields = ("ticker", "symbol", "price", "change", "change_percent", "currency", "source_timestamp",
                  "market_session", "source_time_precision", "source_time_status", "price_basis", "dividends_included")
        body = "\n".join(f"- {field}：{_cell(quote[field])}" for field in fields if field in quote)
    elif isinstance(data, dict):
        body = "\n".join(f"- {field}：{_cell(value)}" for field, value in data.items())
    else:
        body = data if isinstance(data, str) else _json(data)
    full = "\n\n".join(filter(None, [lead, body]))
    if tokens(full) <= budget:
        return full
    note = f"原文共 {len(body)} 字符，当前为有界片段"
    if handle is not None:
        note += f"，句柄 {handle}，可用 read_data 读取其余部分"
    fixed = "\n\n".join(filter(None, [lead, note]))
    remaining = budget - tokens(fixed) - 8
    if remaining < 1:
        return _prefix(fixed, budget)
    return _prefix(fixed + "\n\n" + _prefix(body, remaining), budget)


def to_ui(result: ToolResult | dict, name=None, arguments=None) -> dict:
    """展示结构明确携带类型；原始结果不经过界面投影回写。"""
    from .diagnostics import TOOL_TITLES, clean_text, safe_preview, tool_summary
    from .adapters.catalog import TOOL_LABEL_ALIASES, TOOL_LABELS
    result = ToolResult.model_validate(result)
    arguments = arguments or {}
    data = result.data if isinstance(result.data, dict) else {}
    asset = data.get("asset") if isinstance(data.get("asset"), dict) else {}
    target = arguments.get("ticker") or arguments.get("symbol") or data.get("ticker") or asset.get("symbol")
    target = clean_text(str(target or arguments.get("query") or arguments.get("indicator") or "当前研究资料"), 100)
    title = TOOL_LABELS.get(name) or TOOL_TITLES.get(TOOL_LABEL_ALIASES.get(name, name), "研究资料")
    summary = result.error.user_message if result.error is not None else "" if result.data is None else tool_summary(result.data)
    rows = result_rows(result) if result.status != "error" else []
    keys = ("price", "change", "change_percent", "currency", "source_timestamp", "as_of", "frequency", "period")
    quote = {**data, **data["data"]} if result.kind == "quote" and isinstance(data.get("data"), dict) else data
    facts = [{"label": _FIELD_LABELS[key], "value": safe_preview(quote[key])} for key in keys if key in quote]
    if result.kind == "quote" and result.status == "ok" and quote.get("price") is not None:
        summary = " ".join(str(value) for value in (quote["price"], quote.get("currency")) if value is not None)
    as_of = result.as_of.isoformat() if result.as_of is not None else data.get("as_of") or quote.get("source_timestamp")
    total = max(len(rows), data["row_count"]) if type(data.get("row_count")) is int else len(rows)
    return {"kind": result.kind, "status": result.status, "title": title, "target": target,
            "result": clean_text(summary, 240), "summary": clean_text(summary, 240), "key_facts": facts,
            "row_count": total, "returned_rows": min(len(rows), 6), "has_more": total > min(len(rows), 6),
            "rows": [safe_preview(row, max_chars=3000) for row in rows[:6]], "as_of": as_of,
            "sources": [safe_preview(source.model_dump(mode="json")) for source in result.sources[:8]],
            "notes": [clean_text(note, 600) for note in result.notes if note != "freshness_seconds 是数据龄"],
            "error": result.error.model_dump(mode="json") if result.error is not None else None}
