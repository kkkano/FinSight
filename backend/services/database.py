# -*- coding: utf-8 -*-
"""核心 PostgreSQL 连接与 Alembic 版本门禁。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "alembic.ini"
CORE_DSN_ENV_NAMES = (
    "FINSIGHT_POSTGRES_DSN",
    "AGENT_PREDICTION_POSTGRES_DSN",
    "RAG_V2_POSTGRES_DSN",
    "LANGGRAPH_CHECKPOINT_POSTGRES_DSN",
)


class DatabaseConfigurationError(RuntimeError):
    """数据库连接配置无效。"""


class DatabaseSchemaMismatch(RuntimeError):
    """数据库 revision 与应用代码不一致。"""


@dataclass(frozen=True)
class SchemaRevisionStatus:
    configured: bool
    current: tuple[str, ...]
    expected: tuple[str, ...]
    is_current: bool


def app_mode(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return str(source.get("APP_MODE") or "development").strip().lower()


def is_production_mode(environ: Mapping[str, str] | None = None) -> bool:
    return app_mode(environ) == "production"


def normalize_sync_postgres_dsn(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("postgres://"):
        normalized = "postgresql://" + normalized[len("postgres://") :]
    if normalized.startswith("postgresql+asyncpg://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql+asyncpg://") :]
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql://") :]
    if not normalized.startswith("postgresql+psycopg://"):
        raise DatabaseConfigurationError("核心数据库只允许 PostgreSQL psycopg DSN")
    return normalized


def resolve_core_postgres_dsn(
    environ: Mapping[str, str] | None = None,
    *,
    required: bool = False,
) -> str:
    source = os.environ if environ is None else environ
    raw = next((str(source.get(name) or "").strip() for name in CORE_DSN_ENV_NAMES if source.get(name)), "")
    if not raw:
        if required:
            raise DatabaseConfigurationError(
                "缺少 FINSIGHT_POSTGRES_DSN；生产核心存储不得回退到 SQLite/JSON"
            )
        return ""
    return normalize_sync_postgres_dsn(raw)


def create_core_engine(*, dsn: str | None = None, **kwargs: Any):
    normalized = normalize_sync_postgres_dsn(dsn) if dsn is not None else resolve_core_postgres_dsn(required=True)
    options = {"future": True, "pool_pre_ping": True}
    options.update(kwargs)
    return create_engine(normalized, **options)


def alembic_heads() -> tuple[str, ...]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return tuple(sorted(ScriptDirectory.from_config(config).get_heads()))


def schema_revision_status(*, engine: Any | None = None) -> SchemaRevisionStatus:
    expected = alembic_heads()
    if engine is None:
        dsn = resolve_core_postgres_dsn(required=False)
        if not dsn:
            return SchemaRevisionStatus(False, (), expected, False)
        engine = create_core_engine(dsn=dsn)

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    except Exception as exc:
        raise DatabaseSchemaMismatch("核心数据库缺少可读取的 alembic_version") from exc

    current = tuple(sorted(str(item) for item in rows))
    return SchemaRevisionStatus(True, current, expected, current == expected)


def assert_core_schema_current(*, engine: Any | None = None) -> SchemaRevisionStatus:
    if engine is None and not resolve_core_postgres_dsn(required=False):
        if is_production_mode():
            raise DatabaseConfigurationError(
                "production 必须配置 FINSIGHT_POSTGRES_DSN"
            )
        return SchemaRevisionStatus(False, (), alembic_heads(), False)

    status = schema_revision_status(engine=engine)
    if not status.is_current:
        current = ",".join(status.current) or "<none>"
        expected = ",".join(status.expected) or "<none>"
        raise DatabaseSchemaMismatch(
            f"核心数据库 schema revision 不匹配: current={current}, expected={expected}；"
            "请先执行 alembic upgrade head"
        )
    return status


__all__ = [
    "ALEMBIC_CONFIG_PATH",
    "CORE_DSN_ENV_NAMES",
    "DatabaseConfigurationError",
    "DatabaseSchemaMismatch",
    "SchemaRevisionStatus",
    "alembic_heads",
    "app_mode",
    "assert_core_schema_current",
    "create_core_engine",
    "is_production_mode",
    "normalize_sync_postgres_dsn",
    "resolve_core_postgres_dsn",
    "schema_revision_status",
]
