# -*- coding: utf-8 -*-
"""交易时段判断测试（market_hours）。

覆盖：
- 四时段边界（4:00 / 9:30 / 16:00 / 20:00 ET 整点前后）
- 夏令时(EDT, UTC-4) vs 冬令时(EST, UTC-5) 的北京时间换算正确性
- 周六/周日 → closed
- NYSE 节假日 → closed
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.services.market_hours import get_market_session

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


def test_next_year_holiday_does_not_require_a_new_table():
    assert get_market_session(_ny(2027, 1, 1, 12, 0)) == "closed"


def test_mixed_markets_use_their_own_session():
    now = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)
    assert get_market_session(now, symbol="600519.SS") == "regular"
    assert get_market_session(now, symbol="0700.HK") == "regular"
    assert get_market_session(now, symbol="AAPL") == "closed"


@pytest.mark.parametrize("symbol", ["600519.SS", "0700.HK"])
def test_asian_lunch_break_is_closed(symbol):
    assert get_market_session(datetime(2026, 10, 12, 4, 15, tzinfo=timezone.utc), symbol=symbol) == "closed"


def test_nyse_early_close_uses_calendar_schedule():
    assert get_market_session(_ny(2026, 11, 27, 13, 0)) == "after_hours"


def test_crypto_does_not_use_nyse_holidays():
    assert get_market_session(_ny(2026, 12, 25, 12, 0), symbol="BTC-USD") == "regular"
