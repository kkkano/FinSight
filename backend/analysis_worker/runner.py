"""仅供无网络作业镜像调用；本文件不是进程内 Python 安全沙箱。"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path

# -I 不信任调用方 PYTHONPATH；这里只加入镜像内只读的协议目录。
sys.path.insert(0, "/opt/analysis")
from protocol import MAX_LOG_BYTES, MAX_REQUEST_BYTES, MAX_RESULT_BYTES, JobRequest, safe_code_error
from data_access import get_frame

INPUT = Path("/input/request.json")


class BoundedLog(io.TextIOBase):
    def __init__(self):
        self.parts: list[str] = []
        self.size = 0
        self.truncated = False

    def write(self, text: str) -> int:
        encoded = text.encode("utf-8", errors="replace")
        remaining = MAX_LOG_BYTES - self.size
        part = encoded[:remaining]
        if part:
            self.parts.append(part.decode("utf-8", errors="ignore"))
        self.size += len(part)
        self.truncated |= len(encoded) > remaining
        return len(text)

    def getvalue(self) -> str:
        return "".join(self.parts)


def stage() -> None:
    """可信初始化程序只写原始 JSON，不解析或执行代码。"""
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("analysis_request_too_large")
    with INPUT.open("xb") as target:
        target.write(raw)
    INPUT.chmod(0o444)


def run() -> dict:
    import finsight
    import numpy as np
    import pandas as pd

    request = JobRequest.from_bytes(INPUT.read_bytes())
    class ResultEncoder(json.JSONEncoder):
        def default(self, value):
            if isinstance(value, np.generic):
                return value.item()
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            return super().default(value)
    class Frames(Mapping):
        def __getitem__(self, ref):
            return get_frame(request.datasets, ref)

        def __iter__(self):
            return iter(request.datasets)

        def __len__(self):
            return len(request.datasets)

    scope = {"datasets": request.datasets, "pd": pd, "np": np, "finsight": finsight,
             "frames": Frames(), "__name__": "__analysis__",
             "get_frame": lambda ref, table=None: get_frame(request.datasets, ref, table)}
    log = BoundedLog()
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            exec(compile(request.code, "<analysis>", "exec"), scope, scope)
        if "result" not in scope:
            return {"status": "error", "error": "analysis_result_missing", "logs": log.getvalue(), "logs_truncated": log.truncated}
        size = 0
        encoded = []
        for chunk in ResultEncoder(ensure_ascii=False, allow_nan=False).iterencode(scope["result"]):
            size += len(chunk.encode("utf-8"))
            if size > MAX_RESULT_BYTES:
                return {"status": "error", "error": "analysis_output_limit", "logs": log.getvalue(), "logs_truncated": log.truncated}
            encoded.append(chunk)
        return {"status": "ok", "result": json.loads("".join(encoded)), "logs": log.getvalue(),
                "logs_truncated": log.truncated}
    except BaseException as exc:
        frames = [frame for frame in traceback.extract_tb(exc.__traceback__) if frame.filename == "<analysis>"]
        line = getattr(exc, "lineno", None) if isinstance(exc, SyntaxError) else frames[-1].lineno if frames else None
        detail = safe_code_error({"type": type(exc).__name__, "message": str(exc), "line": line})
        code = "analysis_memory_limit" if isinstance(exc, MemoryError) else "analysis_code_or_result_invalid" if isinstance(exc, (TypeError, ValueError, OverflowError, UnicodeError)) else "analysis_code_failed"
        return {"status": "error", "error": code, "logs": log.getvalue(), "logs_truncated": log.truncated,
                **({"code_error": detail} if detail else {})}


if __name__ == "__main__":
    staging = len(sys.argv) == 2 and sys.argv[1] == "stage"
    if os.getenv("FINSIGHT_ANALYSIS_CONTAINER") != "1" or os.getuid() != (0 if staging else 65532):
        raise SystemExit("analysis_container_required")
    if staging:
        stage()
    elif len(sys.argv) == 1:
        sys.stdout.write(json.dumps(run(), ensure_ascii=False, allow_nan=False))
    else:
        raise SystemExit("analysis_command_invalid")
