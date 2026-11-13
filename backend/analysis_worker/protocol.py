"""计算作业协议及硬上限，不依赖业务配置或凭据。"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_LOG_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = MAX_RESULT_BYTES + MAX_LOG_BYTES * 6 + 4096
MAX_CODE_CHARS = 16000
MAX_SECONDS = 60.0


def safe_code_error(value) -> dict | None:
    """只回传计算代码本身的简短错误，不携带堆栈或宿主路径。"""
    if not isinstance(value, dict) or value.get("type") not in {
        "KeyError", "ValueError", "TypeError", "NameError", "IndexError", "AttributeError",
        "ZeroDivisionError", "SyntaxError", "ImportError", "MemoryError", "Exception", "SystemExit",
    }:
        return None
    message = str(value.get("message") or "")
    message = re.sub(r"\b(?:sk-[\w-]{12,}|sb_secret_[\w-]+|Bearer\s+\S+|eyJ[\w-]+\.[\w-]+\.[\w-]+)", "[已隐藏]", message, flags=re.I)
    message = re.sub(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)[^\s,;&]+", r"\1\2[已隐藏]", message)
    result = {"type": value["type"], "message": message[:500]}
    line = value.get("line")
    if type(line) is int and 0 < line <= 16000:
        result["line"] = line
    return result


class AnalysisError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def strict_json(raw: str | bytes):
    def reject_constant(_value):
        raise ValueError("non_finite_json")

    return json.loads(raw, parse_constant=reject_constant)


@dataclass(frozen=True)
class JobRequest:
    code: str
    datasets: dict
    timeout_seconds: float = 15.0

    @classmethod
    def from_bytes(cls, raw: bytes) -> "JobRequest":
        if len(raw) > MAX_REQUEST_BYTES:
            raise AnalysisError("analysis_request_too_large")
        try:
            value = strict_json(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise AnalysisError("analysis_request_invalid") from None
        if not isinstance(value, dict) or set(value) - {"code", "datasets", "timeout_seconds"}:
            raise AnalysisError("analysis_request_invalid")
        code, datasets = value.get("code"), value.get("datasets")
        if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
            raise AnalysisError("analysis_code_invalid")
        if not isinstance(datasets, dict) or len(datasets) > 8:
            raise AnalysisError("analysis_datasets_invalid")
        if any(not isinstance(ref, str) or not ref or len(ref) > 256 for ref in datasets):
            raise AnalysisError("analysis_datasets_invalid")
        seconds = value.get("timeout_seconds", 15.0)
        if (isinstance(seconds, bool) or not isinstance(seconds, (float, int))
                or not math.isfinite(seconds) or not 0 < seconds <= MAX_SECONDS):
            raise AnalysisError("analysis_timeout_invalid")
        # 拒绝 JSON 中孤立代理码点，避免后续写入 UTF-8 时产生不确定行为。
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, UnicodeError, RecursionError):
            raise AnalysisError("analysis_request_invalid") from None
        return cls(code=code, datasets=datasets, timeout_seconds=float(seconds))

    def encode(self) -> bytes:
        return json.dumps({"code": self.code, "datasets": self.datasets}, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":")).encode("utf-8")
