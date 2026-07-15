# -*- coding: utf-8 -*-
"""由页面 lease 驱动的当前标的实时监控引擎。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from backend.metrics import (
    increment_monitor_escalation,
    increment_monitor_tick,
    increment_monitor_trigger,
)
from backend.services.agent_prediction_store import get_agent_prediction_store
from backend.services.market_data_gateway import get_market_data_gateway
from backend.services.market_hours import get_market_session
from backend.services.monitor_comment_store import get_monitor_comment_store
from backend.services.monitor_lease_store import get_monitor_lease_store
from backend.services.monitor_signals import (
    MarketSnapshot,
    MonitorTrigger,
    detect_triggers,
    heartbeat_due,
)

logger = logging.getLogger(__name__)

# 行情游标只用于判断相邻 tick 是否穿越关键价位；lease 和点评游标均在 PostgreSQL。
_realtime_snapshots: dict[tuple[str, str, str], MarketSnapshot] = {}


class RealtimeMarketDataUnavailable(RuntimeError):
    """实时监控没有取得可信 quote。"""


@dataclass(frozen=True)
class RealtimeMonitorTarget:
    """由有效页面 lease 临时投影出的唯一监控目标。"""

    user_id: str
    session_id: str
    symbol: str


def dispatch_realtime_triggers(
    target: RealtimeMonitorTarget,
    snapshot: MarketSnapshot,
    triggers: list[MonitorTrigger],
    prediction: Any = None,
    prediction_escalated: bool = False,
) -> bool:
    """把确定性 trigger 交给受限点评生产者。"""
    from backend.services.monitor_commentator import produce_monitor_comments_sync

    return produce_monitor_comments_sync(
        target,
        snapshot,
        triggers,
        prediction,
        prediction_escalated=prediction_escalated,
    )


def _target_from_lease(lease: dict[str, Any]) -> RealtimeMonitorTarget:
    return RealtimeMonitorTarget(
        user_id=str(lease.get("user_id") or "").strip(),
        session_id=str(lease.get("session_id") or "").strip(),
        symbol=str(lease.get("symbol") or "").strip().upper(),
    )


def _fetch_realtime_snapshot(target: RealtimeMonitorTarget, now: datetime) -> MarketSnapshot:
    quote_result = get_market_data_gateway().get_quote(target.symbol)
    quote = quote_result.get("quote") if isinstance(quote_result, dict) else None
    if (
        not isinstance(quote_result, dict)
        or quote_result.get("quality") != "trusted"
        or quote_result.get("error_code")
        or not isinstance(quote, dict)
        or quote.get("price") is None
    ):
        raise RealtimeMarketDataUnavailable("trusted quote unavailable")
    return MarketSnapshot(
        symbol=target.symbol,
        observed_at=str(quote_result.get("as_of") or now.isoformat()),
        price=float(quote["price"]),
    )


def _latest_prediction(target: RealtimeMonitorTarget) -> Any:
    try:
        return get_agent_prediction_store().get_latest(
            user_id=target.user_id,
            symbol=target.symbol,
        )
    except Exception as exc:
        logger.warning(
            "[RealtimeMonitor] prediction read failed user=%s session=%s symbol=%s error=%s",
            target.user_id,
            target.session_id,
            target.symbol,
            type(exc).__name__,
        )
        return None


def _cooldown_seconds() -> int:
    try:
        value = int(os.getenv("MONITOR_PREDICTION_COOLDOWN_SECONDS", "1800"))
    except ValueError:
        value = 1800
    return max(60, min(value, 86_400))


def _enqueue_prediction_if_due(
    *,
    target: RealtimeMonitorTarget,
    triggers: list[MonitorTrigger],
    now: datetime,
    comment_store: Any,
) -> bool:
    if not any(trigger.escalates_prediction for trigger in triggers):
        return False
    try:
        last_escalation = comment_store.latest_escalation_at(
            user_id=target.user_id,
            session_id=target.session_id,
            symbol=target.symbol,
        )
        if last_escalation is not None:
            if last_escalation.tzinfo is None:
                last_escalation = last_escalation.replace(tzinfo=timezone.utc)
            if (now - last_escalation).total_seconds() < _cooldown_seconds():
                increment_monitor_escalation("cooldown")
                return False

        from backend.services.prediction_service import get_prediction_service

        get_prediction_service().enqueue(
            user_id=target.user_id,
            symbol=target.symbol,
            timeframe="1d",
        )
        increment_monitor_escalation("queued")
        return True
    except Exception as exc:
        increment_monitor_escalation("error")
        logger.warning(
            "[RealtimeMonitor] prediction escalation failed user=%s session=%s symbol=%s error=%s",
            target.user_id,
            target.session_id,
            target.symbol,
            type(exc).__name__,
        )
        return False


def run_realtime_monitor_cycle(
    *,
    now: datetime | None = None,
    snapshot_fetcher: Callable[[RealtimeMonitorTarget, datetime], MarketSnapshot] | None = None,
    trigger_consumer: Callable[
        [RealtimeMonitorTarget, MarketSnapshot, list[MonitorTrigger], Any, bool], bool
    ]
    | None = None,
) -> int:
    """执行一次 60 秒 tick，返回实际写入点评的目标数。"""
    tick_at = now or datetime.now(timezone.utc)
    if tick_at.tzinfo is None:
        tick_at = tick_at.replace(tzinfo=timezone.utc)
    lease_store = get_monitor_lease_store()
    fetcher = snapshot_fetcher or _fetch_realtime_snapshot
    consumer = trigger_consumer or dispatch_realtime_triggers

    try:
        with lease_store.realtime_tick_lock() as acquired:
            if not acquired:
                increment_monitor_tick("processed")
                logger.info("[RealtimeMonitor] advisory lock busy; skip tick")
                return 0

            lease_store.cleanup_expired(now=tick_at)
            leases = lease_store.list_active(now=tick_at)
            if not leases:
                _realtime_snapshots.clear()
                increment_monitor_tick("no_lease")
                logger.info("[RealtimeMonitor] no active page leases; skip before market/LLM I/O")
                return 0
            if get_market_session(tick_at) == "closed":
                increment_monitor_tick("closed")
                logger.info("[RealtimeMonitor] market closed; skip active page leases")
                return 0

            unique_targets: dict[tuple[str, str, str], RealtimeMonitorTarget] = {}
            for lease in leases:
                target = _target_from_lease(lease)
                key = (target.user_id, target.session_id, target.symbol)
                if all(key):
                    unique_targets.setdefault(key, target)

            active_keys = set(unique_targets)
            for stale_key in set(_realtime_snapshots) - active_keys:
                _realtime_snapshots.pop(stale_key, None)

            comment_store = get_monitor_comment_store()
            written_targets = 0
            errors = 0
            for key, target in unique_targets.items():
                try:
                    # 点评库不可用时不再消耗行情或 LLM 配额。
                    last_comment_at = comment_store.latest_comment_at(
                        user_id=target.user_id,
                        session_id=target.session_id,
                        symbol=target.symbol,
                    )
                    current = fetcher(target, tick_at)
                    previous = _realtime_snapshots.get(key, current)
                    prediction = _latest_prediction(target)
                    triggers = evaluate_realtime_snapshot(
                        previous=previous,
                        current=current,
                        prediction=prediction,
                        last_comment_at=last_comment_at,
                        now=tick_at,
                    )
                    _realtime_snapshots[key] = current
                    if not triggers:
                        continue
                    for trigger in triggers:
                        increment_monitor_trigger(trigger.kind, trigger.severity)
                    prediction_escalated = _enqueue_prediction_if_due(
                        target=target,
                        triggers=triggers,
                        now=tick_at,
                        comment_store=comment_store,
                    )
                    wrote = consumer(
                        target,
                        current,
                        triggers,
                        prediction,
                        prediction_escalated,
                    )
                    written_targets += int(bool(wrote))
                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "[RealtimeMonitor] tick failed user=%s session=%s symbol=%s error=%s",
                        target.user_id,
                        target.session_id,
                        target.symbol,
                        type(exc).__name__,
                    )
            increment_monitor_tick("error" if errors else "processed")
            return written_targets
    except Exception as exc:
        increment_monitor_tick("error")
        logger.warning(
            "[RealtimeMonitor] lease store unavailable; fail closed error=%s",
            type(exc).__name__,
        )
        return 0


def evaluate_realtime_snapshot(
    previous: MarketSnapshot,
    current: MarketSnapshot,
    prediction: Any,
    last_comment_at: datetime | None,
    now: datetime,
) -> list[MonitorTrigger]:
    """只计算实时触发，不调用 LLM、不写库。"""
    if get_market_session(now) == "closed":
        return []
    triggers = detect_triggers(previous=previous, current=current, prediction=prediction)
    if triggers:
        return triggers
    if heartbeat_due(last_comment_at=last_comment_at, now=now):
        return [MonitorTrigger(
            kind="heartbeat",
            detail=(
                f"{current.symbol} 过去 300 秒无显式触发；"
                f"最新价 {float(current.price):.4f}"
            ),
            observed_at=current.observed_at,
            severity="info",
        )]
    return []


__all__ = [
    "RealtimeMarketDataUnavailable",
    "RealtimeMonitorTarget",
    "dispatch_realtime_triggers",
    "evaluate_realtime_snapshot",
    "run_realtime_monitor_cycle",
]
