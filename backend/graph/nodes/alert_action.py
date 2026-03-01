# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from backend.graph.state import GraphState
from backend.services.alert_scheduler import fetch_price_snapshot
from backend.services.subscription_service import get_subscription_service


def _resolve_user_email(state: GraphState) -> str | None:
    direct = str(state.get("user_email") or "").strip()
    if direct:
        return direct
    ui_context = state.get("ui_context") or {}
    fallback = str((ui_context.get("user_email") if isinstance(ui_context, dict) else "") or "").strip()
    return fallback or None


def _resolve_ticker(state: GraphState, alert_params: dict[str, Any]) -> str | None:
    ticker = str(alert_params.get("ticker") or "").strip().upper()
    if ticker:
        return ticker
    subject = state.get("subject") or {}
    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    if isinstance(tickers, list) and tickers:
        first = str(tickers[0] or "").strip().upper()
        if first:
            return first
    return None


def _merge_alert_types(existing: list[str] | None) -> list[str]:
    merged = list(existing or [])
    if "price_change" not in merged:
        merged.append("price_change")
    return merged


def _build_success_markdown(*, ticker: str, mode: str, direction: str | None, price_target: float | None, price_threshold: float | None, alert_types: list[str]) -> str:
    if mode == "price_target":
        arrow = "上涨到" if direction == "above" else "下跌到"
        return (
            f"已为 `{ticker}` 创建到价提醒：{arrow} `{price_target}` 时提醒。\n"
            f"- 订阅类型：{', '.join(alert_types)}\n"
            "- 说明：系统已保留你原有订阅类型，并追加价格提醒。"
        )

    return (
        f"已为 `{ticker}` 创建涨跌幅提醒：绝对涨跌幅达到 `{price_threshold}%` 时提醒。\n"
        f"- 订阅类型：{', '.join(alert_types)}\n"
        "- 说明：系统已保留你原有订阅类型，并追加价格提醒。"
    )


async def alert_action(state: GraphState) -> dict[str, Any]:
    user_email = _resolve_user_email(state)
    if not user_email:
        return {
            "alert_valid": False,
            "skip_session_context": True,
            "artifacts": {
                "draft_markdown": "请先在设置中配置提醒邮箱，然后再说「某股票涨到/跌到XX提醒我」。"
            },
        }

    alert_params = state.get("alert_params") or {}
    ticker = _resolve_ticker(state, alert_params)
    if not ticker:
        return {
            "alert_valid": False,
            "skip_session_context": True,
            "artifacts": {
                "draft_markdown": "我还不知道你要订阅哪只股票，请补充 ticker（例如 AAPL）。"
            },
        }

    mode = str(alert_params.get("alert_mode") or "price_change_pct")
    price_target = alert_params.get("price_target")
    price_threshold = alert_params.get("price_threshold")
    direction = alert_params.get("direction")

    if mode == "price_target":
        if price_target is None:
            return {
                "alert_valid": False,
                "skip_session_context": True,
                "artifacts": {"draft_markdown": "到价提醒缺少目标价格，请补充后重试。"},
            }
        if direction not in {"above", "below"}:
            snap = fetch_price_snapshot(ticker)
            current_price = snap.price if snap is not None else None
            if isinstance(current_price, (int, float)):
                direction = "above" if float(price_target) >= float(current_price) else "below"
            else:
                direction = "above"

    svc = get_subscription_service()
    existing_subs = svc.get_subscriptions(user_email)
    existing = None
    for item in existing_subs:
        if str(item.get("ticker") or "").strip().upper() == ticker:
            existing = item
            break

    merged_alert_types = _merge_alert_types((existing or {}).get("alert_types") if isinstance(existing, dict) else None)
    risk_threshold = (existing or {}).get("risk_threshold", "high") if isinstance(existing, dict) else "high"

    ok = svc.subscribe(
        email=user_email,
        ticker=ticker,
        alert_types=merged_alert_types,
        price_threshold=price_threshold,
        alert_mode=mode,
        price_target=price_target,
        direction=direction,
        risk_threshold=risk_threshold,
    )

    if not ok:
        return {
            "alert_valid": False,
            "skip_session_context": True,
            "artifacts": {"draft_markdown": "提醒创建失败，请稍后重试。"},
        }

    markdown = _build_success_markdown(
        ticker=ticker,
        mode=mode,
        direction=direction,
        price_target=price_target,
        price_threshold=price_threshold,
        alert_types=merged_alert_types,
    )

    return {
        "alert_valid": True,
        "skip_session_context": True,
        "artifacts": {"draft_markdown": markdown},
    }


__all__ = ["alert_action"]
