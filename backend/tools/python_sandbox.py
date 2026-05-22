# -*- coding: utf-8 -*-
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable


class PythonComputeRejected(ValueError):
    """Raised when a compute request violates the restricted contract."""


SAFE_OPERATIONS: frozenset[str] = frozenset(
    {
        "growth_rates",
        "valuation_sanity",
        "surprise_impact",
        "ratio_table",
        "growth_chart",
    }
)

_UNSAFE_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "code",
        "python",
        "script",
        "import",
        "imports",
        "module",
        "path",
        "file",
        "open",
        "socket",
        "subprocess",
        "requests",
        "http",
        "url",
    }
)


def _walk_param_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys: list[str] = []
        for key, item in value.items():
            keys.append(str(key).strip().lower())
            keys.extend(_walk_param_keys(item))
        return keys
    if isinstance(value, list):
        keys = []
        for item in value:
            keys.extend(_walk_param_keys(item))
        return keys
    return []


def validate_compute_request(
    *,
    dataset_refs: list[str],
    operation: str,
    params: dict[str, Any] | None = None,
) -> None:
    op_name = str(operation or "").strip()
    if op_name not in SAFE_OPERATIONS:
        raise PythonComputeRejected(f"unsupported operation: {op_name or '<empty>'}")

    refs = [str(ref or "").strip() for ref in (dataset_refs or []) if str(ref or "").strip()]
    if not refs:
        raise PythonComputeRejected("dataset_refs is required")
    if any(not ref.startswith("step:") for ref in refs):
        raise PythonComputeRejected("dataset_refs must reference collected step outputs")

    payload = params if isinstance(params, dict) else {}
    unsafe = sorted(set(_walk_param_keys(payload)).intersection(_UNSAFE_PARAM_KEYS))
    if unsafe:
        raise PythonComputeRejected(f"arbitrary code or external access is not allowed: {', '.join(unsafe)}")


def run_with_timeout(fn: Callable[[], dict[str, Any]], *, timeout_s: float) -> dict[str, Any]:
    timeout = max(1.0, min(float(timeout_s or 10.0), 30.0))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            future.cancel()
            raise PythonComputeRejected(f"python compute timed out after {timeout:g}s") from exc
