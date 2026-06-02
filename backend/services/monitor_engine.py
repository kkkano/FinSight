# -*- coding: utf-8 -*-
"""
工作台 Phase 1：L1 规则扫描引擎（零 LLM 成本）。

对单个 session 跑规则扫描，产出 Finding 并落库。Phase 1 实现两条规则：
  1. 价格异动（price_move）：持仓 + watchlist target 的 ticker 单日涨跌超阈值
  2. 持仓集中度（concentration）：单一持仓市值占比超阈值

其余 trigger_type（sentiment_shift / earnings_near / macro_event）预留，本期不实现。

设计要点：
- 价格复用 alert_scheduler.fetch_price_snapshot（多源免费 fallback）
- 产出前 has_recent_finding 去重（默认 4 小时窗口）
- 单条规则内捕获异常，互不影响
- 模块级引用 fetch_price_snapshot / get_positions / list_session_ids / get_monitor_store，
  便于测试 monkeypatch
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from backend.services.alert_scheduler import fetch_price_snapshot
from backend.services.monitor_l2 import get_l2_budget, l2_enabled, run_l2_analysis
from backend.services.monitor_store import get_monitor_store
from backend.services.portfolio_store import get_positions, list_session_ids

logger = logging.getLogger(__name__)

# 默认阈值（可被 MonitorTarget.config 覆盖）
DEFAULT_PRICE_MOVE_PCT = 5.0
DEFAULT_CONCENTRATION_PCT = 80.0
DEDUP_WINDOW_HOURS = 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_finding(
    session_id: str,
    target: str,
    trigger_type: str,
    trigger_detail: dict,
    title: str,
    summary: str,
    actions: list[dict],
) -> dict:
    """构造一条 Finding（agent_analysis 在 Phase 1 恒为 None）。"""
    return {
        "id": uuid.uuid4().hex,
        "session_id": session_id,
        "created_at": _now_iso(),
        "target": target,
        "trigger_type": trigger_type,
        "trigger_detail": trigger_detail,
        "title": title,
        "summary": summary,
        "agent_analysis": None,
        "actions": actions,
        "status": "new",
    }


def _build_target_config_map(targets: list[dict]) -> dict[str, dict]:
    """ticker(大写) -> config，仅收 enabled 且有 ticker 的 target。"""
    out: dict[str, dict] = {}
    for t in targets:
        if not t.get("enabled", True):
            continue
        ticker = t.get("ticker")
        if ticker:
            out[str(ticker).strip().upper()] = t.get("config") or {}
    return out


def _portfolio_concentration_config(targets: list[dict]) -> dict:
    """取 PORTFOLIO 级（ticker 为空）target 的 config，用于集中度阈值。"""
    for t in targets:
        if not t.get("enabled", True):
            continue
        if not t.get("ticker"):
            return t.get("config") or {}
    return {}


async def _scan_price_move(
    session_id: str,
    store,
    positions: list[dict],
    config_map: dict[str, dict],
) -> list[dict]:
    """价格异动规则：覆盖持仓 + watchlist target 的全部 ticker。"""
    findings: list[dict] = []

    tickers: set[str] = {
        str(p.get("ticker", "")).strip().upper() for p in positions if p.get("ticker")
    }
    tickers |= set(config_map.keys())

    for ticker in sorted(tickers):
        try:
            threshold = float(config_map.get(ticker, {}).get("price_move_pct") or DEFAULT_PRICE_MOVE_PCT)

            snap = fetch_price_snapshot(ticker)
            if snap is None or snap.change_percent is None:
                continue
            change_pct = float(snap.change_percent)
            if abs(change_pct) < threshold:
                continue

            if store.has_recent_finding(session_id, ticker, "price_move", within_hours=DEDUP_WINDOW_HOURS):
                continue

            direction = "上涨" if change_pct >= 0 else "下跌"
            finding = _new_finding(
                session_id=session_id,
                target=ticker,
                trigger_type="price_move",
                trigger_detail={
                    "change_pct": round(change_pct, 4),
                    "threshold": threshold,
                    "price": snap.price,
                },
                title=f"{ticker} 单日{direction} {abs(change_pct):.1f}%",
                summary=f"{ticker} 今日{direction} {abs(change_pct):.1f}%，已超过 {threshold:.0f}% 盯盘阈值。",
                actions=[
                    {"type": "full_report", "label": "全面体检", "ticker": ticker},
                    {"type": "chart", "label": "看图表", "ticker": ticker},
                ],
            )
            store.insert_finding(finding)
            findings.append(finding)
        except Exception as exc:  # noqa: BLE001 - 单条规则失败不影响其他
            logger.warning("[MonitorEngine] price_move scan failed for %s: %s", ticker, exc)

    return findings


async def _scan_concentration(
    session_id: str,
    store,
    positions: list[dict],
    conc_config: dict,
) -> list[dict]:
    """集中度规则：单一持仓市值占比超阈值则告警（PORTFOLIO 级）。"""
    findings: list[dict] = []
    try:
        if len(positions) < 1:
            return findings

        threshold = float(conc_config.get("concentration_pct") or DEFAULT_CONCENTRATION_PCT)

        values: list[tuple[str, float]] = []
        for p in positions:
            ticker = str(p.get("ticker", "")).strip().upper()
            shares = float(p.get("shares", 0) or 0)
            if not ticker or shares <= 0:
                continue
            snap = fetch_price_snapshot(ticker)
            price = None
            if snap is not None and snap.price is not None:
                price = float(snap.price)
            if price is None:
                price = float(p.get("avg_cost") or 0)
            values.append((ticker, shares * price))

        total = sum(v for _, v in values)
        if total <= 0:
            return findings

        top_ticker, top_value = max(values, key=lambda x: x[1])
        pct = top_value / total * 100.0
        if pct <= threshold:
            return findings

        if store.has_recent_finding(session_id, "PORTFOLIO", "concentration", within_hours=DEDUP_WINDOW_HOURS):
            return findings

        finding = _new_finding(
            session_id=session_id,
            target="PORTFOLIO",
            trigger_type="concentration",
            trigger_detail={
                "top_ticker": top_ticker,
                "concentration_pct": round(pct, 2),
                "threshold": threshold,
            },
            title=f"持仓过度集中：{top_ticker} 占比 {pct:.0f}%",
            summary=f"单一持仓 {top_ticker} 市值占比 {pct:.0f}%，已超过 {threshold:.0f}% 集中度阈值，建议分散风险。",
            actions=[
                {"type": "rebalance", "label": "调仓建议", "ticker": "PORTFOLIO"},
            ],
        )
        store.insert_finding(finding)
        findings.append(finding)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MonitorEngine] concentration scan failed for %s: %s", session_id, exc)

    return findings


async def _run_l2_for_findings(store, findings: list[dict]) -> None:
    """Phase 2：对新产生的 findings 逐条做 L2 agent 深析（带成本护栏）。

    - 总开关 / 熔断 / 预算任一不满足则整体跳过
    - 单条预算用尽即停止后续 L2（已分析的保留）
    - L2 失败（run_l2_analysis 返回 None）不影响 Finding 本身
    """
    if not l2_enabled():
        return
    budget = get_l2_budget()
    for finding in findings:
        if not budget.can_spend():
            break
        analysis = await run_l2_analysis(finding)
        if analysis:
            budget.record_spend()
            store.update_finding_analysis(finding["session_id"], finding["id"], analysis)
            finding["agent_analysis"] = analysis  # 返回值里也带上


async def run_l1_scan(session_id: str, enable_l2: bool = True) -> list[dict]:
    """对单个 session 跑 L1 规则扫描，返回本次新产生的 findings。

    enable_l2=True 时（默认），对新 finding 串联 L2 agent 深析（受成本护栏限制）。
    """
    store = get_monitor_store()
    positions = get_positions(session_id)
    targets = store.list_targets(session_id)

    # 无持仓且无盯盘标的 -> 直接返回
    if not positions and not targets:
        return []

    config_map = _build_target_config_map(targets)
    conc_config = _portfolio_concentration_config(targets)

    findings: list[dict] = []
    findings += await _scan_price_move(session_id, store, positions, config_map)
    findings += await _scan_concentration(session_id, store, positions, conc_config)

    # Phase 2: L2 agent 自动深析（有成本护栏）
    if enable_l2 and findings:
        await _run_l2_for_findings(store, findings)

    return findings


def run_monitor_scan_cycle() -> None:
    """调度入口（同步包装）：扫描所有有持仓的 session。"""
    try:
        session_ids = list_session_ids()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MonitorEngine] failed to list sessions: %s", exc)
        return

    if not session_ids:
        logger.info("[MonitorEngine] no sessions with holdings; skip L1 scan.")
        return

    async def _scan_all() -> int:
        total = 0
        for sid in session_ids:
            try:
                produced = await run_l1_scan(sid)
                total += len(produced)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[MonitorEngine] L1 scan failed for session %s: %s", sid, exc)
        return total

    try:
        produced = asyncio.run(_scan_all())
        logger.info("[MonitorEngine] L1 scan cycle done: sessions=%s findings=%s", len(session_ids), produced)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MonitorEngine] L1 scan cycle error: %s", exc)


__all__ = ["run_l1_scan", "run_monitor_scan_cycle"]
