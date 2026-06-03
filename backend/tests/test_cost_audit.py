# -*- coding: utf-8 -*-
"""P2-7：CostAuditStore 持久化 / 聚合 / Top 排序 / 清理 测试。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.cost_audit import CostAuditStore


def _summary(total: int, prompt: int, completion: int, calls: int, cost: float, by_model=None):
    """构造一个形如 TokenUsageAccumulator.summary() 的 dict。"""
    return {
        "total_prompt_tokens": prompt,
        "total_completion_tokens": completion,
        "total_tokens": total,
        "llm_token_calls": calls,
        "total_cost_usd": cost,
        "tokens_by_model": by_model or {},
    }


@pytest.fixture()
def store(tmp_path):
    return CostAuditStore(db_path=str(tmp_path / "cost_audit.db"))


# --- record + daily_summary 聚合 -------------------------------------------


def test_record_and_daily_summary_aggregates(store):
    store.record(session_id="s1", source="chat", summary=_summary(150, 100, 50, 2, 0.01))
    store.record(session_id="s2", source="report", summary=_summary(300, 200, 100, 3, 0.05))

    daily = store.daily_summary(days=7)
    assert len(daily) == 1  # 同一天
    day = daily[0]
    assert day["total_tokens"] == 450
    assert day["request_count"] == 2
    assert pytest.approx(day["total_cost_usd"], abs=1e-9) == 0.06
    # 分 source 聚合
    assert day["by_source"]["chat"]["tokens"] == 150
    assert day["by_source"]["report"]["tokens"] == 300
    assert day["by_source"]["report"]["count"] == 1


def test_record_skips_empty_request(store):
    """0 token + 0 调用的空请求不落库，避免噪声。"""
    store.record(session_id="empty", source="chat", summary=_summary(0, 0, 0, 0, 0.0))
    assert store.totals(days=7)["request_count"] == 0


def test_record_normalizes_unknown_source(store):
    store.record(session_id="x", source="weird_source", summary=_summary(100, 60, 40, 1, 0.002))
    top = store.top_requests(days=7)
    assert top[0]["source"] == "other"


# --- top_requests 排序 ------------------------------------------------------


def test_top_requests_sorted_by_tokens_desc(store):
    store.record(session_id="small", source="chat", summary=_summary(100, 50, 50, 1, 0.001))
    store.record(session_id="big", source="report", summary=_summary(5000, 4000, 1000, 8, 0.5))
    store.record(session_id="mid", source="dashboard", summary=_summary(800, 500, 300, 3, 0.02))

    top = store.top_requests(days=7, limit=20)
    assert [r["total_tokens"] for r in top] == [5000, 800, 100]
    assert top[0]["session_id"] == "big"


def test_top_requests_respects_limit(store):
    for i in range(5):
        store.record(session_id=f"s{i}", source="chat", summary=_summary(100 + i, 50, 50, 1, 0.0))
    top = store.top_requests(days=7, limit=3)
    assert len(top) == 3


def test_top_requests_preserves_model_breakdown(store):
    by_model = {"gpt-4o": {"prompt": 100, "completion": 50, "calls": 1}}
    store.record(session_id="m", source="report", summary=_summary(150, 100, 50, 1, 0.01, by_model))
    top = store.top_requests(days=7)
    assert top[0]["model_breakdown"]["gpt-4o"]["prompt"] == 100


# --- 多 source 分组 ---------------------------------------------------------


def test_totals_across_sources(store):
    store.record(session_id="a", source="chat", summary=_summary(100, 60, 40, 1, 0.01))
    store.record(session_id="b", source="report", summary=_summary(200, 120, 80, 2, 0.02))
    store.record(session_id="c", source="monitor_l2", summary=_summary(50, 30, 20, 1, 0.005))

    totals = store.totals(days=7)
    assert totals["total_tokens"] == 350
    assert totals["request_count"] == 3
    assert pytest.approx(totals["total_cost_usd"], abs=1e-9) == 0.035


# --- cleanup 保留期 ---------------------------------------------------------


def test_cleanup_keeps_recent_removes_old(store):
    # 直接写一条「91 天前」的旧记录绕过 record 的当前时间戳。
    conn = store._db()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    conn.execute(
        """INSERT INTO cost_records
           (created_at, session_id, source, total_tokens, prompt_tokens,
            completion_tokens, llm_calls, cost_usd, model_breakdown)
           VALUES (?, 'old', 'chat', 100, 60, 40, 1, 0.0, NULL)""",
        (old_ts,),
    )
    conn.commit()
    store.record(session_id="new", source="chat", summary=_summary(200, 120, 80, 2, 0.0))

    removed = store.cleanup(keep_days=90)
    assert removed == 1
    # 新记录仍在
    assert store.totals(days=90)["request_count"] == 1


def test_daily_summary_window_excludes_out_of_range(store):
    """超出 days 窗口的记录不进入 daily_summary。"""
    conn = store._db()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    conn.execute(
        """INSERT INTO cost_records
           (created_at, session_id, source, total_tokens, prompt_tokens,
            completion_tokens, llm_calls, cost_usd, model_breakdown)
           VALUES (?, 'old', 'chat', 999, 500, 499, 5, 0.9, NULL)""",
        (old_ts,),
    )
    conn.commit()
    store.record(session_id="recent", source="chat", summary=_summary(100, 60, 40, 1, 0.0))

    daily = store.daily_summary(days=7)
    assert len(daily) == 1
    assert daily[0]["total_tokens"] == 100
