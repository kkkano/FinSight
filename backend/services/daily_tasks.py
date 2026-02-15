"""智能任务生成器: 根据用户画像 + 市场数据 + 研报时效动态生成每日任务列表。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


# 研报过期阈值 (天)
REPORT_STALE_DAYS = 3


def _days_since(iso_str: str | None) -> int | None:
    """计算距离 ISO 时间字符串的天数差。"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def _stable_task_id(*, ticker: str = "", category: str, date_str: str = "") -> str:
    """生成稳定的任务 ID (基于 ticker + category + date 的 hash)。

    同一天、同一 ticker、同一类别的任务总是返回相同的 ID，
    避免前端在轮询刷新时重新挂载组件。
    """
    today = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    material = f"{ticker}|{category}|{today}".encode("utf-8")
    return f"task_{hashlib.sha256(material).hexdigest()[:12]}"


def generate_daily_tasks(
    *,
    watchlist: list[str],
    reports: list[dict[str, Any]],
    news_count: int = 0,
    risk_preference: str = "balanced",
) -> list[dict[str, Any]]:
    """根据输入信号生成个性化每日任务列表。

    Args:
        watchlist: 用户关注的 ticker 列表
        reports: 最近的研报列表 (来自 report_index)
        news_count: 未读新闻条数
        risk_preference: 投资者类型 (conservative / balanced / aggressive)

    Returns:
        任务列表, 每条含 id / title / category / priority / action_url / icon / execution_params
    """
    tasks: list[dict[str, Any]] = []

    # --- 1. 研报时效检查 ---
    ticker_last_report: dict[str, dict[str, Any]] = {}
    for r in reports:
        t = r.get("ticker")
        if t and t not in ticker_last_report:
            ticker_last_report[t] = r

    for ticker in watchlist:
        last = ticker_last_report.get(ticker)
        if last:
            days = _days_since(last.get("generated_at"))
            if days is not None and days >= REPORT_STALE_DAYS:
                # 过期研报 → 重新分析
                tasks.append({
                    "id": _stable_task_id(ticker=ticker, category="reanalyze"),
                    "title": f"{ticker} 研报已 {days} 天未更新 — 建议刷新",
                    "category": "reanalyze",
                    "priority": 1 if days >= 7 else 2,
                    "action_url": f"/chat?query=分析 {ticker} 最新情况",
                    "icon": "AlertTriangle",
                    "execution_params": {
                        "query": f"重新分析 {ticker} 最新情况",
                        "tickers": [ticker],
                        "output_mode": "investment_report",
                    },
                })
            else:
                # 近期研报 → 查看 (无需执行)
                report_id = last.get("report_id", "")
                generated = last.get("generated_at", "")[:10]
                tasks.append({
                    "id": _stable_task_id(ticker=ticker, category="review"),
                    "title": f"查看 {ticker} 最新研报 (生成于 {generated})",
                    "category": "review",
                    "priority": 3,
                    "action_url": f"/chat?report_id={report_id}" if report_id else f"/workbench?ticker={ticker}",
                    "icon": "FileSearch",
                    "execution_params": None,
                })
        else:
            # 关注但无研报 → 生成首份分析
            tasks.append({
                "id": _stable_task_id(ticker=ticker, category="generate"),
                "title": f"为 {ticker} 生成首份深度分析",
                "category": "generate",
                "priority": 2,
                "action_url": f"/chat?query=深度分析 {ticker}",
                "icon": "Sparkles",
                "execution_params": {
                    "query": f"深度分析 {ticker}",
                    "tickers": [ticker],
                    "output_mode": "investment_report",
                },
            })

    # --- 2. 新闻任务 (导航型，无需执行) ---
    if news_count > 0:
        tickers_str = ", ".join(watchlist[:3]) if watchlist else "市场"
        tasks.append({
            "id": _stable_task_id(category="news"),
            "title": f"{news_count} 条未读快讯 ({tickers_str})",
            "category": "news",
            "priority": 2,
            "action_url": "/dashboard",
            "icon": "Newspaper",
            "execution_params": None,
        })

    # --- 3. 风险偏好特定任务 ---
    if risk_preference == "conservative":
        tasks.append({
            "id": _stable_task_id(category="risk"),
            "title": "检查持仓风险敞口 — 关注防御性配置",
            "category": "risk",
            "priority": 2,
            "action_url": "/chat?query=分析我的持仓风险敞口",
            "icon": "Shield",
            "execution_params": {
                "query": "分析我的持仓风险敞口",
                "output_mode": "chat",
            },
        })
    elif risk_preference == "aggressive":
        tasks.append({
            "id": _stable_task_id(category="opportunity"),
            "title": "扫描高波动标的机会 — 事件驱动策略",
            "category": "opportunity",
            "priority": 2,
            "action_url": "/chat?query=近期有哪些高波动投资机会",
            "icon": "TrendingUp",
            "execution_params": {
                "query": "近期有哪些高波动投资机会",
                "output_mode": "chat",
            },
        })
    else:
        tasks.append({
            "id": _stable_task_id(category="rebalance"),
            "title": "组合再平衡检查 — 评估配置偏离度",
            "category": "rebalance",
            "priority": 3,
            "action_url": "/chat?query=我的持仓需要再平衡吗",
            "icon": "BarChart2",
            "execution_params": {
                "query": "我的持仓需要再平衡吗",
                "output_mode": "chat",
            },
        })

    # 按 priority 排序 (1=高, 3=低), 最多 5 条
    tasks.sort(key=lambda t: t["priority"])
    return tasks[:5]
