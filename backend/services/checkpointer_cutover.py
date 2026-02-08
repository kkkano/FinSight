# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from backend.graph import checkpointer as checkpointer_mod

_CHECKPOINTER_ENV_KEYS = (
    "LANGGRAPH_CHECKPOINTER_BACKEND",
    "LANGGRAPH_CHECKPOINT_SQLITE_PATH",
    "LANGGRAPH_CHECKPOINT_POSTGRES_DSN",
    "LANGGRAPH_CHECKPOINT_POSTGRES_PIPELINE",
    "LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_postgres_dsn(dsn: str) -> str:
    raw = (dsn or "").strip()
    if not raw:
        return ""
    if "@" not in raw:
        return raw
    right = raw.split("@", 1)[1]
    if "://" in raw:
        scheme = raw.split("://", 1)[0]
        return f"{scheme}://***@{right}"
    return f"***@{right}"


@contextmanager
def _temporary_env(overrides: Mapping[str, str | None]) -> Iterator[None]:
    old_values = {key: os.getenv(key) for key in _CHECKPOINTER_ENV_KEYS}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, old in old_values.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _probe_backend(
    *,
    backend: str,
    sqlite_path: str,
    postgres_dsn: str,
    pipeline: bool,
    allow_fallback: bool,
) -> dict[str, Any]:
    env_updates = {
        "LANGGRAPH_CHECKPOINTER_BACKEND": backend,
        "LANGGRAPH_CHECKPOINT_SQLITE_PATH": sqlite_path,
        "LANGGRAPH_CHECKPOINT_POSTGRES_DSN": postgres_dsn if backend == "postgres" else None,
        "LANGGRAPH_CHECKPOINT_POSTGRES_PIPELINE": "true" if pipeline else "false",
        "LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK": "true" if allow_fallback else "false",
    }
    with _temporary_env(env_updates):
        checkpointer_mod.reset_checkpointer_caches()
        try:
            bundle = checkpointer_mod.get_checkpointer_bundle()
            info = bundle.info
            resolved_backend = str(info.backend)
            if resolved_backend != backend:
                raise RuntimeError(f"expected backend={backend}, got backend={resolved_backend}")
            location = str(info.location or "")
            if resolved_backend == "postgres":
                location = _sanitize_postgres_dsn(location)
            return {
                "backend": resolved_backend,
                "persistent": bool(info.persistent),
                "fallback_used": bool(info.fallback_used),
                "fallback_reason": info.fallback_reason,
                "location": location or None,
            }
        finally:
            checkpointer_mod.reset_checkpointer_caches()


def run_checkpointer_cutover_drill(
    *,
    sqlite_path: str,
    postgres_dsn: str,
    pipeline: bool = False,
    allow_fallback: bool = False,
) -> dict[str, Any]:
    started_at = _now_iso()
    steps: list[dict[str, Any]] = []
    postgres_ok = False

    try:
        sqlite_info = _probe_backend(
            backend="sqlite",
            sqlite_path=sqlite_path,
            postgres_dsn=postgres_dsn,
            pipeline=pipeline,
            allow_fallback=allow_fallback,
        )
        steps.append(
            {
                "step": "sqlite_precheck",
                "status": "pass",
                **sqlite_info,
            }
        )
    except Exception as exc:
        steps.append(
            {
                "step": "sqlite_precheck",
                "status": "failed",
                "error": str(exc),
            }
        )
        finished_at = _now_iso()
        return {
            "ok": False,
            "started_at": started_at,
            "finished_at": finished_at,
            "config": {
                "sqlite_path": sqlite_path,
                "postgres_dsn": _sanitize_postgres_dsn(postgres_dsn),
                "pipeline": pipeline,
                "allow_fallback": allow_fallback,
            },
            "steps": steps,
        }

    try:
        postgres_info = _probe_backend(
            backend="postgres",
            sqlite_path=sqlite_path,
            postgres_dsn=postgres_dsn,
            pipeline=pipeline,
            allow_fallback=allow_fallback,
        )
        postgres_ok = True
        steps.append(
            {
                "step": "postgres_cutover",
                "status": "pass",
                **postgres_info,
            }
        )
    except Exception as exc:
        steps.append(
            {
                "step": "postgres_cutover",
                "status": "failed",
                "error": str(exc),
            }
        )

    rollback_ok = False
    try:
        rollback_info = _probe_backend(
            backend="sqlite",
            sqlite_path=sqlite_path,
            postgres_dsn=postgres_dsn,
            pipeline=pipeline,
            allow_fallback=allow_fallback,
        )
        rollback_ok = True
        steps.append(
            {
                "step": "sqlite_rollback",
                "status": "pass",
                **rollback_info,
            }
        )
    except Exception as exc:
        steps.append(
            {
                "step": "sqlite_rollback",
                "status": "failed",
                "error": str(exc),
            }
        )

    finished_at = _now_iso()
    return {
        "ok": bool(postgres_ok and rollback_ok),
        "started_at": started_at,
        "finished_at": finished_at,
        "config": {
            "sqlite_path": sqlite_path,
            "postgres_dsn": _sanitize_postgres_dsn(postgres_dsn),
            "pipeline": pipeline,
            "allow_fallback": allow_fallback,
        },
        "steps": steps,
    }


def write_checkpointer_drill_evidence(result: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return path


__all__ = [
    "run_checkpointer_cutover_drill",
    "write_checkpointer_drill_evidence",
]

