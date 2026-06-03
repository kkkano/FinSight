# -*- coding: utf-8 -*-
"""交易时段判断测试（market_hours）。

覆盖：
- 四时段边界（4:00 / 9:30 / 16:00 / 20:00 ET 整点前后）
- 夏令时(EDT, UTC-4) vs 冬令时(EST, UTC-5) 的北京时间换算正确性
- 周六/周日 → closed
- NYSE 节假日 → closed
- 扫描间隔（默认 + 环境变量覆盖）
- price_rules_active
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.services import market_hours
from backend.services.market_hours import (
    get_market_session,
    get_scan_interval_minutes,
    price_rules_active,
)

_NY = ZoneInfo("America/New_York")
_BJ = ZoneInfo("Asia/Shanghai")


def _ny(year, month, day, hour, minute=0) -> datetime:
    """构造一个美东本地 tz-aware datetime（夏令时由 zoneinfo 自动处理）。"""
    return datetime(year, month, day, hour, minute, tzinfo=_NY)


# ── 时段边界（用一个普通工作日：2026-06-15 周一，夏令时）─────────────


def test_pre_market_at_open_boundary():
    # 4:00 ET 整点 → 盘前开始
    assert get_market_session(_ny(2026, 6, 15, 4, 0)) == "pre_market"


def test_just_before_pre_market_is_closed():
    # 3:59 ET → 还没到盘前 → closed
    assert get_market_session(_ny(2026, 6, 15, 3, 59)) == "closed"


def test_regular_at_open_boundary():
    # 9:30 ET 整点 → 盘中开始（边界归 regular）
    assert get_market_session(_ny(2026, 6, 15, 9, 30)) == "regular"


def test_just_before_regular_is_pre_market():
    # 9:29 ET → 仍是盘前
    assert get_market_session(_ny(2026, 6, 15, 9, 29)) == "pre_market"


def test_after_hours_at_close_boundary():
    # 16:00 ET → 盘后开始（边界归 after_hours）
    assert get_market_session(_ny(2026, 6, 15, 16, 0)) == "after_hours"


def test_just_before_close_is_regular():
    # 15:59 ET → 仍是盘中
    assert get_market_session(_ny(2026, 6, 15, 15, 59)) == "regular"


def test_after_hours_end_boundary_is_closed():
    # 20:00 ET → 盘后结束 → closed
    assert get_market_session(_ny(2026, 6, 15, 20, 0)) == "closed"


def test_just_before_after_hours_end_is_after_hours():
    # 19:59 ET → 仍是盘后
    assert get_market_session(_ny(2026, 6, 15, 19, 59)) == "after_hours"


def test_mid_regular_session():
    assert get_market_session(_ny(2026, 6, 15, 12, 0)) == "regular"


def test_midnight_is_closed():
    assert get_market_session(_ny(2026, 6, 15, 0, 0)) == "closed"


# ── 夏令时 vs 冬令时：北京时间换算正确性 ───────────────────────────


def test_dst_pre_market_open_in_beijing_time():
    """夏令时 2026-07-01：盘前 4:00 EDT(UTC-4) = 北京 16:00。"""
    dt_et = _ny(2026, 7, 1, 4, 0)  # 周三
    assert get_market_session(dt_et) == "pre_market"
    bj = dt_et.astimezone(_BJ)
    assert (bj.hour, bj.minute) == (16, 0)


def test_winter_pre_market_open_in_beijing_time():
    """冬令时 2026-12-01：盘前 4:00 EST(UTC-5) = 北京 17:00。"""
    dt_et = _ny(2026, 12, 1, 4, 0)  # 周二
    assert get_market_session(dt_et) == "pre_market"
    bj = dt_et.astimezone(_BJ)
    assert (bj.hour, bj.minute) == (17, 0)


def test_dst_via_utc_input_matches():
    """传 UTC datetime 也应正确换算：2026-07-01 08:00 UTC = 4:00 EDT = 盘前。"""
    dt_utc = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    assert get_market_session(dt_utc) == "pre_market"


def test_winter_regular_via_utc_input():
    """冬令时 2026-12-01 15:00 UTC = 10:00 EST = 盘中。"""
    dt_utc = datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc)
    assert get_market_session(dt_utc) == "regular"


def test_naive_datetime_treated_as_utc():
    """naive datetime 按 UTC 解释：2026-07-01 08:00(naive) = 4:00 EDT = 盘前。"""
    dt_naive = datetime(2026, 7, 1, 8, 0)
    assert get_market_session(dt_naive) == "pre_market"


# ── 周末 ───────────────────────────────────────────────────────


def test_saturday_is_closed():
    # 2026-06-13 周六，即便在盘中时段也 closed
    assert get_market_session(_ny(2026, 6, 13, 12, 0)) == "closed"


def test_sunday_is_closed():
    # 2026-06-14 周日
    assert get_market_session(_ny(2026, 6, 14, 12, 0)) == "closed"


# ── NYSE 节假日 ────────────────────────────────────────────────


def test_independence_day_observed_is_closed():
    # 2026-07-03 周五（独立日提前休市），盘中时段也 closed
    assert get_market_session(_ny(2026, 7, 3, 12, 0)) == "closed"


def test_christmas_is_closed():
    # 2026-12-25 周五
    assert get_market_session(_ny(2026, 12, 25, 10, 0)) == "closed"


def test_new_year_is_closed():
    # 2026-01-01 周四
    assert get_market_session(_ny(2026, 1, 1, 11, 0)) == "closed"


def test_holiday_set_contains_all_2026():
    assert len(market_hours.NYSE_HOLIDAYS_2026) == 10
    assert "2026-11-26" in market_hours.NYSE_HOLIDAYS_2026  # 感恩节


# ── 扫描间隔 ───────────────────────────────────────────────────


def test_default_intervals():
    assert get_scan_interval_minutes("pre_market") == 10.0
    assert get_scan_interval_minutes("regular") == 15.0
    assert get_scan_interval_minutes("after_hours") == 30.0
    assert get_scan_interval_minutes("closed") == 60.0


def test_interval_env_override(monkeypatch):
    monkeypatch.setenv("MONITOR_INTERVAL_PRE_MARKET", "7")
    monkeypatch.setenv("MONITOR_INTERVAL_REGULAR", "20")
    monkeypatch.setenv("MONITOR_INTERVAL_AFTER_HOURS", "45")
    monkeypatch.setenv("MONITOR_INTERVAL_CLOSED", "90")
    assert get_scan_interval_minutes("pre_market") == 7.0
    assert get_scan_interval_minutes("regular") == 20.0
    assert get_scan_interval_minutes("after_hours") == 45.0
    assert get_scan_interval_minutes("closed") == 90.0


def test_interval_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MONITOR_INTERVAL_REGULAR", "not-a-number")
    assert get_scan_interval_minutes("regular") == 15.0


def test_interval_nonpositive_env_falls_back(monkeypatch):
    # 0 或负数会导致狂扫，应回退默认（诚实兜底）
    monkeypatch.setenv("MONITOR_INTERVAL_PRE_MARKET", "0")
    assert get_scan_interval_minutes("pre_market") == 10.0
    monkeypatch.setenv("MONITOR_INTERVAL_PRE_MARKET", "-5")
    assert get_scan_interval_minutes("pre_market") == 10.0


def test_interval_unknown_session_defaults_to_regular():
    assert get_scan_interval_minutes("weird") == 15.0


# ── price_rules_active ─────────────────────────────────────────


def test_price_rules_active_by_session():
    assert price_rules_active("pre_market") is True
    assert price_rules_active("regular") is True
    assert price_rules_active("after_hours") is True
    assert price_rules_active("closed") is False
