"""工具边界的 JSON 录制与离线回放；不理解用户问法或供应商正文。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from .capture import capture_producers


_KINDS = {
    "get_stock_price": "quote",
    "get_stock_historical_data": "series",
    "get_us_extended_hours": "series",
    "get_finra_otc_activity": "table",
    "get_company_info": "table",
    "get_sec_company_facts_quarterly": "table",
    "get_financial_statements": "table",
    "get_earnings_estimates": "table",
    "get_eps_revisions": "table",
    "get_technical_snapshot": "table",
    "get_company_news": "news",
    "search_news": "news",
    "get_current_datetime": "control",
    "get_watchlist": "control",
    "analyze_dataset": "computation",
    "run_analysis_code": "computation",
    "render_chart": "chart",
}
_VALID_KINDS = {"quote", "series", "table", "news", "document", "computation", "chart", "control"}
_STATUSES = {"ok", "empty", "error"}


def _json_value(value: Any) -> None:
    if value is None or type(value) in {str, int, bool}:
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise ValueError("tape_non_json_value")


def canonical_json(value: Any) -> str:
    """只有 JSON 值可以成为回放键，禁止隐式字符串化对象。"""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("tape_non_json_value") from exc
    _json_value(value)
    return encoded


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _error(code: str, summary: str) -> dict:
    return {"status": "error", "error_code": code, "error": code, "summary": summary}


def _envelope(name: str, raw: Any) -> dict:
    declared = raw.get("status") if isinstance(raw, dict) else None
    code = raw.get("error_code") if isinstance(raw, dict) else None
    status = declared if declared in _STATUSES else (
        "error" if declared in {"unavailable", "failed"} or code else (
            "empty" if raw is None or raw == [] else "ok"
        )
    )
    kind = raw.get("kind") if isinstance(raw, dict) else None
    if kind not in _VALID_KINDS:
        kind = _KINDS.get(name, "document")
    result = {
        "status": status, "kind": kind, "data": deepcopy(raw), "sources": [],
        "as_of": None, "notes": [], "error": None,
    }
    if isinstance(raw, dict):
        if raw.get("status") in _STATUSES and raw.get("kind") in _VALID_KINDS and "data" in raw:
            result["data"] = deepcopy(raw["data"])
        for field in ("sources", "as_of", "notes"):
            if field in raw:
                result[field] = deepcopy(raw[field])
    if status == "error":
        result["error"] = {
            "code": str(code or "tool_provider_error"), "user_message": "录制工具未返回可用结果。",
            "retryable": code == "provider_timeout", "suggestion": None,
        }
    return result


def _captured_http_payload(name: str, arguments: dict, record: dict):
    """按供应商 HTTP 协议投射已录 JSON；不查看格式化正文。"""
    endpoints = {
        "search": {("api.exa.ai", ("search",)): "exa", ("api.tavily.com", ("search",)): "tavily"},
        "get_company_info": {("api.finnhub.io", ("api", "v1", "stock", "profile2")): "finnhub",
                             ("www.alphavantage.co", ("query",)): "alpha_vantage"},
    }
    fallback = None
    for item in record.get("producer_outputs", []):
        if (item.get("producer") != "requests.Response" or item.get("method") != "json"
                or item.get("status") != "captured" or not isinstance(item.get("data"), dict)):
            continue
        metadata = item.get("arguments") or {}
        if not isinstance(metadata.get("url"), str):
            continue
        try:
            url = urlsplit(metadata["url"])
        except ValueError:
            continue
        endpoint = (url.hostname, tuple(part for part in url.path.split("/") if part))
        provider = endpoints.get(name, {}).get(endpoint)
        http_status = metadata.get("status_code")
        if provider is None or type(http_status) is not int:
            continue
        data = deepcopy(item["data"])
        if not 200 <= http_status < 300:
            fallback = {**_error("provider_http_" + str(http_status), "录制供应商返回 HTTP 错误。"),
                        "http_status": http_status, "source": provider, "provider_response": data}
            continue
        if data.get("error") or (provider == "alpha_vantage" and any(key in data for key in ("Error Message", "Information", "Note"))):
            fallback = {**_error("tool_provider_error", "录制供应商声明未返回可用结果。"),
                        "source": provider, "provider_response": data}
            continue
        if name == "search" and isinstance(data.get("results"), list):
            projected = {**data, "source": provider, "status": "ok" if data["results"] else "empty"}
            if data["results"]:
                return projected
            if fallback is None or fallback.get("status") != "error":
                fallback = projected
        elif name == "get_company_info":
            required = "name" if provider == "finnhub" else "Symbol"
            if data.get(required):
                # 与 live sources.company_profile 的纯字段/单位包装保持一致，时点不补造。
                projected = {**data, "ticker": arguments["ticker"], "source": provider, "status": "ok"}
                if provider == "finnhub":
                    projected["column_units"] = {"marketCapitalization": "million " + str(data.get("currency") or "unknown")}
                return projected
            if fallback is None or fallback.get("status") != "error":
                fallback = {**data, "ticker": arguments["ticker"], "source": provider, "status": "empty"}
    return fallback


class ToolTape:
    """同一实例内同键只调用一次；回放缺失会显式返回错误，不联网。"""

    def __init__(self, path: Path, mode: Literal["record", "replay"], faults: dict | None = None,
                 *, seed_path: Path | None = None):
        if mode not in {"record", "replay"}:
            raise ValueError("tape_invalid_mode")
        self.path, self.mode = Path(path), mode
        self.seed_path = Path(seed_path) if seed_path is not None else None
        self.faults = deepcopy(faults or {})
        for fault in self.faults.values():
            if not isinstance(fault, dict) or fault.get("status") not in {"error", "empty"}:
                raise ValueError("tape_invalid_fault")
            canonical_json(fault)
        self._guard = Lock()
        self._locks: dict[str, Lock] = {}
        self._counts = {"recorded": 0, "hits": 0, "misses": 0, "errors": 0}
        self._overlays: dict[str, dict] = {}
        # 只替换当前进程中明确配置的秘密原值，不猜测正文中像密钥的字符串。
        self._secrets = tuple(sorted({
            value for name, value in os.environ.items()
            if value and (name.upper() in {"API_KEY", "TOKEN", "SECRET", "PASSWORD"}
                          or name.upper().endswith(("_API_KEY", "_ACCESS_TOKEN", "_AUTH_TOKEN", "_SECRET", "_PASSWORD")))
        }, key=len, reverse=True))

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        return value

    def _increment(self, name: str) -> None:
        with self._guard:
            self._counts[name] += 1

    def _read(self, path: Path) -> dict:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            checksum = record.pop("checksum")
            key = _hash({"tool": record["tool"], "arguments": record["arguments"]})
            if (record["schema_version"] != 1 or record["key"] != key or path.stem != key
                    or checksum != _hash(record) or record["result"]["status"] not in _STATUSES):
                raise ValueError("tape_corrupt")
            record["checksum"] = checksum
            return record
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("tape_corrupt") from exc

    def _record(self, key: str, name: str, arguments: dict, raw: Any, *, injected: bool = False,
                exception_type: str | None = None, producer_outputs: list | None = None,
                producer_capture: dict | None = None) -> dict:
        raw = self._redact(raw)
        canonical_json(raw)
        record = {
            "schema_version": 1, "key": key, "tool": name, "arguments": arguments,
            "recorded_at": datetime.now(timezone.utc).isoformat(), "injected": injected,
            "result": _envelope(name, raw), "raw_output": raw,
            "producer_outputs": self._redact(producer_outputs or []),
            "producer_capture": producer_capture or {"status": "unavailable", "reason": "injected_fault" if injected else "capture_not_attempted"},
        }
        if exception_type:
            record["exception_type"] = exception_type
        record["checksum"] = _hash(record)
        return record

    def invoke(self, name: str, args: dict, callback: Callable[[dict], Any], *, project=None) -> Any:
        if not isinstance(name, str) or not name or type(args) is not dict:
            raise ValueError("tape_invalid_call")
        canonical_json(args)
        arguments = self._redact(args)
        key = _hash({"tool": name, "arguments": arguments})
        with self._guard:
            lock = self._locks.setdefault(key, Lock())
        with lock:
            if name in self.faults:
                fault = self.faults[name]
                raw = (_error(fault.get("code", "injected_tool_error"), "评测中注入的工具故障。")
                       if fault["status"] == "error" else {"status": "empty", "data": [], "sources": []})
                record = self._record(key, name, arguments, raw, injected=True)
                with self._guard:
                    self._overlays[key] = record
            elif (path := self.path / (key + ".json")).exists():
                record = self._read(path)
                self._increment("hits")
            elif (self.mode == "record" and self.seed_path is not None
                  and (seed := self.seed_path / (key + ".json")).exists()):
                record = self._read(seed)
                self.path.mkdir(parents=True, exist_ok=True)
                path.write_bytes(seed.read_bytes())
                self._increment("hits")
            elif self.mode == "replay":
                self._increment("misses")
                self._increment("errors")
                return _error("tape_miss", "评测回放中缺少该工具及参数的录制结果。")
            else:
                exception_type = None
                with capture_producers(self._redact) as captured:
                    try:
                        raw = callback(deepcopy(args))
                    except Exception as exc:
                        exception_type = type(exc).__name__
                        code = "provider_timeout" if isinstance(exc, TimeoutError) else "tool_exception"
                        raw = _error(code, "录制时工具调用失败；未保存异常正文。")
                record = self._record(key, name, arguments, raw, exception_type=exception_type,
                    producer_outputs=captured.snapshot(), producer_capture=captured.capability())
                self.path.mkdir(parents=True, exist_ok=True)
                temporary = self.path / (key + "." + uuid4().hex + ".tmp")
                temporary.write_text(canonical_json(record) + "\n", encoding="utf-8")
                os.replace(temporary, path)
                self._increment("recorded")
            if record["result"]["status"] == "error":
                self._increment("errors")
            if project is not None:
                projected = project(name, arguments, record)
                if projected["status"] == "error" and record["result"]["status"] != "error":
                    self._increment("errors")
                return deepcopy(projected)
            return deepcopy(record["raw_output"])

    @staticmethod
    def project_envelope(name: str, arguments: dict, record: dict) -> dict:
        """候选实现读取同一录制的结构化原始响应；不联网补齐或解释格式化正文。"""
        from backend.agent_runtime.adapters import adapt_result

        raw = record["raw_output"]
        targets = {"get_stock_price": ("market_data_gateway", "get_quote"),
                   "get_company_info": ("yfinance.TickerBase", "get_info"),
                   "search": ("ddgs.DDGS", "text")}
        if name in targets and isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                producer, method = targets[name]
                captured = [item for item in record.get("producer_outputs", [])
                            if item.get("producer") == producer and item.get("method") == method
                            and item.get("status") == "captured" and isinstance(item.get("data"), (dict, list))]
                if captured:
                    raw = deepcopy(captured[-1]["data"])
                    if not raw:
                        projected = _captured_http_payload(name, arguments, record)
                        if projected is not None:
                            raw = projected
                else:
                    raw = _captured_http_payload(name, arguments, record)
                    if raw is None:
                        raw = _error("unsupported_payload", "这份旧录制没有可回放的结构化供应商响应。")
        return adapt_result(name, raw, arguments).model_dump(mode="json")

    def wrap_specs(self, specs: dict, *, record_specs: dict | None = None) -> dict:
        def wrap(spec):
            projection = self.project_envelope if getattr(spec, "enveloped", False) else None
            callback = spec.invoke
            if self.mode == "record" and projection is not None:
                if record_specs is None or spec.name not in record_specs:
                    raise ValueError("tape_record_spec_missing:" + spec.name)
                # 同一次旧入口调用保留原文和底层响应，候选只投射已捕获的数据。
                callback = record_specs[spec.name].invoke
            return replace(spec, invoke=lambda args: self.invoke(spec.name, args, callback, project=projection))
        return {name: wrap(spec) for name, spec in specs.items()}

    def stats(self) -> dict[str, int]:
        with self._guard:
            return dict(self._counts)

    def records(self) -> list[dict]:
        records = {path.stem: self._read(path) for path in sorted(self.path.glob("*.json"))}
        with self._guard:
            records.update(deepcopy(self._overlays))
        for record in records.values():
            if "producer_outputs" not in record:
                # 旧文件只增加内存视图；保留原文件校验值，绝不为补捕获重新调用供应商。
                record["recorded_checksum"] = record.pop("checksum")
                record["producer_outputs"] = []
                record["producer_capture"] = {"status": "unavailable", "reason": "legacy_record_without_producer_outputs"}
                record["checksum"] = _hash(record)
        return deepcopy([records[key] for key in sorted(records)])
