# -*- coding: utf-8 -*-
"""PostgreSQL-backed LLM usage quota queries.

业务调用明细统一写入 ``llm_usage``。本模块只负责按租户读取当日成本并执行
每日额度门禁，不在应用运行时创建或修改表结构。
"""
from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import text

from backend.services.database import create_core_engine, resolve_core_postgres_dsn
from backend.utils.env import env_float


class LLMUsageStoreUnavailable(RuntimeError):
    """核心 PostgreSQL 的 LLM usage 数据不可读。"""


class UserDailyCostLimitExceeded(RuntimeError):
    """用户当日 LLM 成本已经达到配置上限。"""

    def __init__(self, *, user_id: str, limit_usd: float, used_usd: float) -> None:
        self.user_id = user_id
        self.limit_usd = limit_usd
        self.used_usd = used_usd
        super().__init__(
            f"今日 AI 分析额度已用完（{limit_usd:.2f} USD/天），明天再来或联系管理员提额。"
        )


class LLMUsageStore:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        self._engine = engine if engine is not None else create_core_engine(dsn=dsn)

    def today_cost_usd(self, user_id: str) -> float:
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            return 0.0
        try:
            with self._engine.connect() as conn:
                value = conn.execute(
                    text(
                        "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage "
                        "WHERE user_id=:user_id AND created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') "
                        "AND created_at < date_trunc('day', now() AT TIME ZONE 'UTC') + interval '1 day'"
                    ),
                    {"user_id": normalized_user},
                ).scalar_one()
        except Exception as exc:
            raise LLMUsageStoreUnavailable("llm_usage postgres unavailable") from exc
        return float(value or 0.0)


_store: LLMUsageStore | None = None
_store_lock = threading.Lock()


def get_llm_usage_store() -> LLMUsageStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            dsn = resolve_core_postgres_dsn(required=False)
            if not dsn:
                raise LLMUsageStoreUnavailable("llm_usage postgres unavailable")
            _store = LLMUsageStore(dsn=dsn)
    return _store


def today_cost_usd(user_id: str) -> float:
    return get_llm_usage_store().today_cost_usd(user_id)


def check_user_quota(user_id: str) -> None:
    normalized_user = str(user_id or "public").strip() or "public"
    limit = env_float("USER_DAILY_COST_LIMIT_USD", 1.0)
    if limit <= 0 or normalized_user == "admin":
        return
    used = today_cost_usd(normalized_user)
    if used >= limit:
        raise UserDailyCostLimitExceeded(
            user_id=normalized_user,
            limit_usd=limit,
            used_usd=used,
        )


def reset_llm_usage_store_cache() -> None:
    global _store
    _store = None


__all__ = [
    "LLMUsageStore",
    "LLMUsageStoreUnavailable",
    "UserDailyCostLimitExceeded",
    "check_user_quota",
    "get_llm_usage_store",
    "reset_llm_usage_store_cache",
    "today_cost_usd",
]
