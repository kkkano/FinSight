# -*- coding: utf-8 -*-
"""页面实时监控使用的美股交易时段判断。

按美东时间把当前时刻归类为四个时段，供监控引擎分时段调度：
  - pre_market   盘前 4:00-9:30 ET：信息最密集（财报/CPI·非农 8:30 发布），扫描最勤
  - regular      盘中 9:30-16:00 ET：常规盯盘
  - after_hours  盘后 16:00-20:00 ET：盘后异动，扫描放缓
  - closed       闭市/周末/NYSE 节假日：停止页面实时监控 I/O

设计要点（KISS / YAGNI）：
- 用标准库 zoneinfo 的 America/New_York 自动处理夏令时，无需引第三方时区库
- NYSE 节假日硬编码 2026 全年（不引日历库；跨年前由人工更新即可）
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo  # Python 3.9+ 标准库

# 时段字面量（用字符串而非枚举：跨模块/落库/前端契约都用裸字符串，KISS）
MarketSession = str  # "pre_market" | "regular" | "after_hours" | "closed"

_NY_TZ = ZoneInfo("America/New_York")

# NYSE 2026 节假日（硬编码，YAGNI 不引日历库）
NYSE_HOLIDAYS_2026 = [
    "2026-01-01",  # 元旦
    "2026-01-19",  # MLK 日
    "2026-02-16",  # 总统日
    "2026-04-03",  # 耶稣受难日
    "2026-05-25",  # 阵亡将士日
    "2026-06-19",  # 六月节
    "2026-07-03",  # 独立日（7/4 周六，提前到周五休市）
    "2026-09-07",  # 劳动节
    "2026-11-26",  # 感恩节
    "2026-12-25",  # 圣诞节
]
_HOLIDAY_SET = frozenset(NYSE_HOLIDAYS_2026)

# 时段边界（美东本地时间）
_PRE_OPEN = time(4, 0)
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_AFTER_CLOSE = time(20, 0)

def get_market_session(now: datetime | None = None) -> MarketSession:
    """返回当前美股交易时段。

    Args:
        now: 参考时刻；None 时用当前 UTC 时间。建议传 tz-aware datetime；
             传入 naive datetime 时按 UTC 解释（向后兼容，避免误判本地时区）。

    Returns:
        "pre_market" / "regular" / "after_hours" / "closed" 之一。

    规则：
    - 换算到 America/New_York（夏令时自动处理）
    - 周六/周日 → closed
    - NYSE 2026 节假日 → closed
    - 4:00-9:30 ET → pre_market；9:30-16:00 → regular；
      16:00-20:00 → after_hours；其余 → closed
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        # naive 一律按 UTC 解释，避免依赖运行机器本地时区
        now = now.replace(tzinfo=timezone.utc)

    ny = now.astimezone(_NY_TZ)

    # 周末（周一=0 ... 周六=5 周日=6）
    if ny.weekday() >= 5:
        return "closed"

    # NYSE 节假日
    if ny.date().isoformat() in _HOLIDAY_SET:
        return "closed"

    t = ny.time()
    if _PRE_OPEN <= t < _REGULAR_OPEN:
        return "pre_market"
    if _REGULAR_OPEN <= t < _REGULAR_CLOSE:
        return "regular"
    if _REGULAR_CLOSE <= t < _AFTER_CLOSE:
        return "after_hours"
    return "closed"
__all__ = [
    "MarketSession",
    "NYSE_HOLIDAYS_2026",
    "get_market_session",
]
