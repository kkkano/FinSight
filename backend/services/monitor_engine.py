# -*- coding: utf-8 -*-
"""
工作台：L1 规则扫描引擎（零 LLM 成本）。

对单个 session 跑规则扫描，产出 Finding 并落库。当前实现五条规则：
  1. 价格异动（price_move）：持仓 + watchlist target 的 ticker 单日涨跌超阈值
  2. 持仓集中度（concentration）：单一持仓市值占比超阈值
  3. 舆情突变（sentiment_shift）：ticker 新闻舆情平均分绝对值超阈值
  4. 财报临近（earnings_near）：ticker 财报日距今 <= 3 天
  5. 宏观事件（macro_event）：近 2 天内有宏观事件（CPI/FOMC/NFP 等），PORTFOLIO 级单条聚合

设计要点：
- 价格复用 alert_scheduler.fetch_price_snapshot（多源免费 fallback）
- 舆情/日历复用 tools.get_news_sentiment_score / get_event_calendar（外部 API，慢）
- 产出前 has_recent_finding 去重（默认 4 小时窗口）
- 单条规则内捕获异常，互不影响（外部 API 慢且易失败，逐 ticker 独立 try/except）
- 模块级引用 fetch_price_snapshot / get_positions / list_session_ids / get_monitor_store /
  get_news_sentiment_score / get_event_calendar，便于测试 monkeypatch

配额护栏：
- 舆情规则走 Alpha Vantage（免费版 25 请求/天），每次扫描每个 ticker 最多 1 次调用；
  可用 MONITOR_SENTIMENT_RULE_ENABLED=false 整条关掉省配额（默认开启）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from backend.services.alert_scheduler import fetch_price_snapshot
from backend.services.market_hours import (
    get_market_session,
    get_scan_interval_minutes,
    price_rules_active,
)
from backend.services.email_service import get_email_service
from backend.services.monitor_l2 import get_l2_budget, l2_enabled, run_l2_analysis
from backend.services.monitor_store import get_monitor_store
from backend.services.portfolio_store import get_positions, list_session_ids
from backend.services.session_price import fetch_session_aware_price_snapshot
from backend.tools import get_event_calendar, get_news_sentiment_score

logger = logging.getLogger(__name__)

# Dispatcher 内存态：上次实际扫描的单调时间戳。
# ⚠️ 仅单 worker 有效：多 worker 部署时各进程有独立 _last_scan_at，会各自按间隔扫描
# （重复扫描，但扫描本身幂等——Finding 有 has_recent_finding 去重，无外部副作用）。
# 邮件通知的去重才是关键（有外部副作用），已落库到 monitor.db notify_cooldown 表（见下）。
# 重启重置无妨，下个心跳即恢复节奏。
_last_scan_at: float | None = None

# 通知冷却阈值：同 session 该窗口内最多发 1 封。
# 冷却时间戳已落库（monitor_store.notify_cooldown），跨重启 / 多 worker 共享，
# 不再用进程内 dict（重启会立即重发、多 worker 各自冷却互不可见）。
NOTIFY_COOLDOWN_SECONDS = 3600.0  # 同 session 1 小时内最多发 1 封

# 默认阈值（可被 MonitorTarget.config 覆盖）
DEFAULT_PRICE_MOVE_PCT = 5.0
DEFAULT_CONCENTRATION_PCT = 80.0
DEFAULT_SENTIMENT_ABS_THRESHOLD = 0.35  # 舆情突变：平均分绝对值阈值
EARNINGS_NEAR_DAYS = 3  # 财报临近：距今 <= 3 天（含今天）触发
MACRO_EVENT_DAYS = 2  # 宏观事件：距今 <= 2 天触发
DEDUP_WINDOW_HOURS = 4


def _sentiment_rule_enabled() -> bool:
    """舆情规则总开关（省 Alpha Vantage 配额用），默认开启。"""
    return str(os.getenv("MONITOR_SENTIMENT_RULE_ENABLED", "true")).strip().lower() not in {
        "false",
        "0",
        "off",
        "no",
    }


def _days_until(date_str: str) -> int | None:
    """计算 ISO 日期距今天的天数（>0 未来，0 今天，<0 已过）；解析失败返回 None。"""
    try:
        target = datetime.fromisoformat(str(date_str).strip()[:10]).date()
    except (TypeError, ValueError):
        return None
    today = datetime.now(timezone.utc).date()
    return (target - today).days


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


# 各时段价格异动文案前缀（盘前/盘后区分于盘中"单日"，便于用户判断）
_SESSION_MOVE_PREFIX = {
    "pre_market": "盘前",
    "after_hours": "盘后",
    "regular": "单日",
}


async def _scan_price_move(
    session_id: str,
    store,
    positions: list[dict],
    config_map: dict[str, dict],
    market_session: str = "regular",
) -> list[dict]:
    """价格异动规则：覆盖持仓 + watchlist target 的全部 ticker。

    market_session 决定取哪个时段的价格（盘前价/盘后价/常规价）及文案前缀。
    闭市时段由调用方跳过本规则（price_rules_active 为 False）。
    """
    findings: list[dict] = []

    tickers: set[str] = {
        str(p.get("ticker", "")).strip().upper() for p in positions if p.get("ticker")
    }
    tickers |= set(config_map.keys())

    prefix = _SESSION_MOVE_PREFIX.get(market_session, "单日")

    for ticker in sorted(tickers):
        try:
            threshold = float(config_map.get(ticker, {}).get("price_move_pct") or DEFAULT_PRICE_MOVE_PCT)

            snap = fetch_session_aware_price_snapshot(ticker, market_session)
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
                    "market_session": market_session,
                    "price_basis": snap.price_basis,
                },
                title=f"{ticker} {prefix}{direction} {abs(change_pct):.1f}%",
                summary=f"{ticker} {prefix}{direction} {abs(change_pct):.1f}%，已超过 {threshold:.0f}% 盯盘阈值。",
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


def _holding_watchlist_tickers(positions: list[dict], config_map: dict[str, dict]) -> list[str]:
    """持仓 + watchlist 去重后的 ticker 列表（大写、排序，确定性顺序便于配额估算）。"""
    tickers: set[str] = {
        str(p.get("ticker", "")).strip().upper() for p in positions if p.get("ticker")
    }
    tickers |= set(config_map.keys())
    return sorted(t for t in tickers if t)


async def _scan_sentiment_shift(
    session_id: str,
    store,
    positions: list[dict],
    config_map: dict[str, dict],
) -> list[dict]:
    """规则 3：舆情突变。

    对持仓 + watchlist ticker 调 get_news_sentiment_score()，平均分绝对值超阈值则触发。
    - score 为 None（数据不可用/限流）→ 跳过不报警（诚实原则：没数据不报警）
    - 配额护栏：每个 ticker 每次扫描最多 1 次 Alpha Vantage 调用
    """
    findings: list[dict] = []
    if not _sentiment_rule_enabled():
        return findings

    for ticker in _holding_watchlist_tickers(positions, config_map):
        try:
            threshold = float(
                config_map.get(ticker, {}).get("sentiment_abs_threshold")
                or DEFAULT_SENTIMENT_ABS_THRESHOLD
            )

            payload = get_news_sentiment_score(ticker)
            score = payload.get("score") if isinstance(payload, dict) else None
            if score is None:
                # 数据不可用：跳过，不触发（绝不编造分数）
                continue
            score = float(score)
            if abs(score) < threshold:
                continue

            if store.has_recent_finding(session_id, ticker, "sentiment_shift", within_hours=DEDUP_WINDOW_HOURS):
                continue

            tone = "强正面" if score >= 0 else "强负面"
            label = payload.get("label") or ("Bullish" if score >= 0 else "Bearish")
            article_count = payload.get("article_count") or 0
            finding = _new_finding(
                session_id=session_id,
                target=ticker,
                trigger_type="sentiment_shift",
                trigger_detail={
                    "score": round(score, 4),
                    "label": label,
                    "threshold": threshold,
                    "article_count": article_count,
                },
                title=f"{ticker} 舆情{tone}：分数 {score:+.2f}",
                summary=f"{ticker} 近期 {article_count} 篇新闻平均舆情分 {score:+.2f}（{label}），"
                f"绝对值已超过 {threshold:.2f} 盯盘阈值。",
                actions=[
                    {"type": "full_report", "label": "全面体检", "ticker": ticker},
                    {"type": "chart", "label": "看图表", "ticker": ticker},
                ],
            )
            store.insert_finding(finding)
            findings.append(finding)
        except Exception as exc:  # noqa: BLE001 - 单 ticker 失败不影响其他
            logger.warning("[MonitorEngine] sentiment_shift scan failed for %s: %s", ticker, exc)
        finally:
            # Alpha Vantage 免费版限制 1 请求/秒：连续 ticker 之间留间隔，
            # 避免第二个 ticker 必然撞限流（缓存命中时多等 1.2s 对后台扫描无影响）
            await asyncio.sleep(1.2)

    return findings


def _clamp_days(raw: Any, default: int) -> int:
    """把 config 里的天数窗口归一化到 1-30 范围；非法/缺失回退默认值。"""
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(30, val))


async def _scan_earnings_near(
    session_id: str,
    store,
    positions: list[dict],
    config_map: dict[str, dict],
) -> list[dict]:
    """规则 4：财报临近。

    对持仓 + watchlist ticker 调 get_event_calendar(days_ahead=7)，
    earnings_events 里有 date 距今 <= N 天（含今天）则触发。
    N 默认 EARNINGS_NEAR_DAYS(3)，可被 per-ticker config.earnings_near_days 覆盖（1-30）。
    """
    findings: list[dict] = []

    for ticker in _holding_watchlist_tickers(positions, config_map):
        try:
            near_days = _clamp_days(
                config_map.get(ticker, {}).get("earnings_near_days"), EARNINGS_NEAR_DAYS
            )

            # calendar 取数窗口至少覆盖 near_days（默认 7，自定义天数更大时跟着放宽）
            calendar = get_event_calendar(ticker, days_ahead=max(7, near_days))
            if not isinstance(calendar, dict):
                continue
            events = calendar.get("earnings_events") or []

            nearest: tuple[int, str] | None = None
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                ev_date = ev.get("date")
                if not ev_date:  # 过滤无日期占位
                    continue
                days = _days_until(ev_date)
                if days is None or days < 0 or days > near_days:
                    continue
                if nearest is None or days < nearest[0]:
                    nearest = (days, str(ev_date)[:10])

            if nearest is None:
                continue

            days, earnings_date = nearest
            if store.has_recent_finding(session_id, ticker, "earnings_near", within_hours=DEDUP_WINDOW_HOURS):
                continue

            when = "今日" if days == 0 else f"{days} 天后"
            finding = _new_finding(
                session_id=session_id,
                target=ticker,
                trigger_type="earnings_near",
                trigger_detail={
                    "earnings_date": earnings_date,
                    "days_until": days,
                    "threshold_days": near_days,
                },
                title=f"{ticker} 财报临近：{earnings_date}",
                summary=f"{ticker} 将于 {earnings_date}（{when}）公布财报，建议提前关注前瞻与持仓风险。",
                actions=[
                    {"type": "full_report", "label": "财报前瞻", "ticker": ticker},
                    {"type": "chart", "label": "看图表", "ticker": ticker},
                ],
            )
            store.insert_finding(finding)
            findings.append(finding)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MonitorEngine] earnings_near scan failed for %s: %s", ticker, exc)

    return findings


async def _scan_macro_event(
    session_id: str,
    store,
    positions: list[dict],
    portfolio_config: dict | None = None,
) -> list[dict]:
    """规则 5：宏观事件（PORTFOLIO 级，target='MACRO'）。

    调一次 get_event_calendar（任一持仓 ticker，没持仓用 'SPY'）拿 macro_events，
    过滤掉 date=None 占位符（source='macro_watchlist' 兜底），
    有 date 距今 <= N 天的事件则触发。N 默认 MACRO_EVENT_DAYS(2)，
    可被 PORTFOLIO 级 config.macro_event_days 覆盖（1-30）。
    多个事件聚合成一条 Finding（避免刷屏）。
    去重 key：target='MACRO' + trigger_type='macro_event'。
    """
    findings: list[dict] = []
    try:
        macro_days = _clamp_days(
            (portfolio_config or {}).get("macro_event_days"), MACRO_EVENT_DAYS
        )

        probe_ticker = "SPY"
        for p in positions:
            t = str(p.get("ticker", "")).strip().upper()
            if t:
                probe_ticker = t
                break

        # calendar 取数窗口至少覆盖 macro_days
        calendar = get_event_calendar(probe_ticker, days_ahead=max(7, macro_days))
        if not isinstance(calendar, dict):
            return findings
        macro_events = calendar.get("macro_events") or []

        upcoming: list[dict] = []
        for ev in macro_events:
            if not isinstance(ev, dict):
                continue
            ev_date = ev.get("date")
            if not ev_date:  # 过滤 date=None 的 macro_watchlist 占位符
                continue
            days = _days_until(ev_date)
            if days is None or days < 0 or days > macro_days:
                continue
            upcoming.append(
                {"date": str(ev_date)[:10], "title": str(ev.get("title") or "宏观事件")[:160], "days_until": days}
            )

        if not upcoming:
            return findings

        upcoming.sort(key=lambda e: e["days_until"])
        if store.has_recent_finding(session_id, "MACRO", "macro_event", within_hours=DEDUP_WINDOW_HOURS):
            return findings

        head = upcoming[0]
        when = "今日" if head["days_until"] == 0 else f"{head['days_until']} 天后"
        extra = f"（另有 {len(upcoming) - 1} 项）" if len(upcoming) > 1 else ""
        finding = _new_finding(
            session_id=session_id,
            target="MACRO",
            trigger_type="macro_event",
            trigger_detail={
                "events": upcoming,
                "threshold_days": macro_days,
            },
            title=f"宏观事件临近：{head['title']}",
            summary=f"{head['date']}（{when}）有宏观事件「{head['title']}」{extra}，可能引发市场波动。",
            actions=[
                {"type": "full_report", "label": "宏观影响分析", "ticker": "MACRO"},
            ],
        )
        store.insert_finding(finding)
        findings.append(finding)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MonitorEngine] macro_event scan failed for %s: %s", session_id, exc)

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


def _smtp_configured() -> bool:
    """SMTP 是否已配置：SMTP_USER 和 SMTP_PASSWORD 环境变量都非空。"""
    return bool(os.getenv("SMTP_USER")) and bool(os.getenv("SMTP_PASSWORD"))


def _notify_findings(session_id: str, findings: list[dict]) -> None:
    """把本轮新 findings 汇总成一封邮件发出（受开关 + SMTP 配置 + 冷却限制）。

    - 仅当 settings.notify_enabled 且 notify_email 非空 且 SMTP 已配置时才发
    - 冷却：同 session 1 小时内最多发 1 封（落库 monitor.db notify_cooldown，超频跳过）
    - 发送失败（网络/SMTP）不影响扫描主流程（try/except + log）
    诚实原则：拿不到配置或未开启时静默跳过，不报错。
    """
    try:
        if not findings:
            return

        store = get_monitor_store()
        settings = store.get_settings(session_id)
        notify_email = settings.get("notify_email")
        if not settings.get("notify_enabled") or not notify_email:
            return
        if not _smtp_configured():
            # SMTP 未配置：静默跳过（不视为错误，settings 已在 API 层拦截启用）
            return

        # 冷却：距上次发信不足 1 小时则跳过。时间戳落库（跨重启 / 多 worker 共享）。
        now = datetime.now(timezone.utc)
        last = store.get_last_notified_at(session_id)
        if last is not None:
            elapsed = (now - last).total_seconds()
            # elapsed < 0 视为时钟回拨/异常未来戳：保守按冷却中处理，避免重发
            if elapsed < NOTIFY_COOLDOWN_SECONDS:
                logger.info(
                    "[MonitorEngine] notify cooldown active for session %s, skip (%.0fs left)",
                    session_id,
                    NOTIFY_COOLDOWN_SECONDS - elapsed,
                )
                return

        # 组装邮件：标题 + 逐条 title/summary
        count = len(findings)
        subject = f"FinSight 盯盘发现 {count} 条新异常"
        lines_html: list[str] = []
        lines_text: list[str] = []
        for f in findings:
            title = str(f.get("title") or "盯盘发现")
            summary = str(f.get("summary") or "")
            lines_html.append(
                f"<li><strong>{title}</strong><br/>"
                f"<span style='color:#555'>{summary}</span></li>"
            )
            lines_text.append(f"- {title}\n  {summary}")

        html_content = (
            "<!DOCTYPE html><html><head><meta charset='UTF-8'></head><body>"
            "<div style='max-width:600px;margin:0 auto;font-family:Arial,sans-serif;"
            "line-height:1.6;color:#333'>"
            "<h2 style='color:#2196F3'>FinSight 盯盘提醒</h2>"
            f"<p>本轮扫描发现 <strong>{count}</strong> 条新异常：</p>"
            f"<ul>{''.join(lines_html)}</ul>"
            "<p style='color:#999;font-size:12px;margin-top:24px'>"
            "此邮件由 FinSight 盯盘系统自动发送。</p>"
            "</div></body></html>"
        )
        text_content = (
            f"FinSight 盯盘提醒\n\n本轮扫描发现 {count} 条新异常：\n\n"
            + "\n\n".join(lines_text)
            + "\n\n---\n此邮件由 FinSight 盯盘系统自动发送。"
        )

        email_service = get_email_service()
        success, error_type, error_msg = email_service.send_email(
            notify_email, subject, html_content, text_content
        )
        if success:
            store.set_last_notified_at(session_id, now)
            logger.info(
                "[MonitorEngine] notify sent for session %s (%s findings) to %s",
                session_id,
                count,
                notify_email,
            )
        else:
            logger.warning(
                "[MonitorEngine] notify send failed for session %s: %s (%s)",
                session_id,
                error_msg,
                error_type,
            )
    except Exception as exc:  # noqa: BLE001 - 通知失败绝不影响扫描主流程
        logger.warning("[MonitorEngine] notify findings failed for %s: %s", session_id, exc)


async def run_l1_scan(
    session_id: str,
    enable_l2: bool = True,
    market_session: str | None = None,
) -> list[dict]:
    """对单个 session 跑 L1 规则扫描，返回本次新产生的 findings。

    market_session 为 None 时自动判定当前时段（向后兼容：API 手动扫描不传也能跑）。
    - 闭市时段（price_rules_active 为 False）跳过价格异动规则，只扫舆情/财报/宏观/集中度
    - 价格规则用对应时段的价格（盘前价/盘后价/常规价）
    - 所有本次 finding 的 trigger_detail 统一注入 market_session（前端可据此区分时段来源）

    enable_l2=True 时（默认），对新 finding 串联 L2 agent 深析（受成本护栏限制）。
    """
    if market_session is None:
        market_session = get_market_session()

    store = get_monitor_store()
    positions = get_positions(session_id)
    targets = store.list_targets(session_id)

    # 无持仓且无盯盘标的 -> 直接返回
    if not positions and not targets:
        return []

    config_map = _build_target_config_map(targets)
    conc_config = _portfolio_concentration_config(targets)

    findings: list[dict] = []
    # 价格异动：闭市价格不动，跳过（不调价格 API，省请求且不报无意义异动）
    if price_rules_active(market_session):
        findings += await _scan_price_move(
            session_id, store, positions, config_map, market_session
        )
    findings += await _scan_concentration(session_id, store, positions, conc_config)
    findings += await _scan_sentiment_shift(session_id, store, positions, config_map)
    findings += await _scan_earnings_near(session_id, store, positions, config_map)
    # 宏观天数窗口复用 PORTFOLIO 级 config（与集中度同一份 conc_config）
    findings += await _scan_macro_event(session_id, store, positions, conc_config)

    # 说明：market_session 只写入价格异动规则的 trigger_detail（已在 _scan_price_move
    # 落库时带上，库与内存一致）。非价格规则（财报/宏观/集中度/舆情）与时段语义无关，
    # 不强行注入，避免库内存不一致 + 冗余字段（DRY / 诚实一致性）。

    # Phase 2: L2 agent 自动深析（有成本护栏）
    if enable_l2 and findings:
        await _run_l2_for_findings(store, findings)

    # Phase 3: 新 finding 邮件通知（受 session 级开关 + 冷却限制，失败不影响主流程）
    if findings:
        _notify_findings(session_id, findings)

    return findings


def run_monitor_scan_cycle(market_session: str | None = None) -> None:
    """调度入口（同步包装）：扫描所有有持仓的 session（时段感知）。

    market_session 为 None 时自动判定当前时段并透传给每个 session 的扫描，
    使闭市跳过价格规则、盘前/盘后用对应时段价格。保留本函数供手动调用 / 向后兼容。
    """
    if market_session is None:
        market_session = get_market_session()

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
                produced = await run_l1_scan(sid, market_session=market_session)
                total += len(produced)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[MonitorEngine] L1 scan failed for session %s: %s", sid, exc)
        return total

    try:
        produced = asyncio.run(_scan_all())
        logger.info(
            "[MonitorEngine] L1 scan cycle done: session_state=%s sessions=%s findings=%s",
            market_session,
            len(session_ids),
            produced,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MonitorEngine] L1 scan cycle error: %s", exc)


def run_monitor_dispatch_cycle() -> None:
    """调度心跳入口（每 ~5 分钟被 APScheduler 调一次）。

    分时段调度的核心：心跳频率固定，实际扫描频率按时段间隔（pre_market 10 /
    regular 15 / after_hours 30 / closed 60 分钟）由本函数节流：
      1. 判定当前时段 + 该时段扫描间隔
      2. 距上次实际扫描不足 interval → 本心跳跳过（节流，避免高频扫）
      3. 否则执行 run_monitor_scan_cycle(session) 并更新 _last_scan_at
    """
    global _last_scan_at

    session = get_market_session()
    interval_minutes = get_scan_interval_minutes(session)

    import time as _time

    now = _time.monotonic()
    if _last_scan_at is not None and (now - _last_scan_at) < interval_minutes * 60.0:
        elapsed_min = (now - _last_scan_at) / 60.0
        logger.info(
            "[MonitorEngine] dispatch: session=%s interval=%smin elapsed=%.1fmin -> skip (throttled)",
            session,
            interval_minutes,
            elapsed_min,
        )
        return

    logger.info(
        "[MonitorEngine] dispatch: session=%s interval=%smin -> scanning",
        session,
        interval_minutes,
    )
    run_monitor_scan_cycle(market_session=session)
    _last_scan_at = _time.monotonic()


__all__ = [
    "run_l1_scan",
    "run_monitor_scan_cycle",
    "run_monitor_dispatch_cycle",
    "_notify_findings",
]
