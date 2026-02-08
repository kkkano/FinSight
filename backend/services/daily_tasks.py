"""智能任务生成器: 根据用户画像 + 市场数据 + 研报时效动态生成每日任务列表。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
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
        任务列表, 每条含 id / title / category / priority / action_url / icon
    """
    tasks: list[dict[str, Any]] = []
    task_id = 0

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
                task_id += 1
                tasks.append({
                    "id": f"task_{task_id}",
                    "title": f"{ticker} 研报已 {days} 天未更新 — 建议刷新",
                    "category": "refresh",
                    "priority": 1 if days >= 7 else 2,
                    "action_url": f"/chat?query=分析 {ticker} 最新情况",
                    "icon": "AlertTriangle",
                })
            else:
                task_id += 1
                generated = last.get("generated_at", "")[:10]
                tasks.append({
                    "id": f"task_{task_id}",
                    "title": f"查看 {ticker} 最新研报 (生成于 {generated})",
                    "category": "review",
                    "priority": 3,
                    "action_url": f"/workbench?ticker={ticker}",
                    "icon": "FileSearch",
                })
        else:
            # 关注但无研报
            task_id += 1
            tasks.append({
                "id": f"task_{task_id}",
                "title": f"为 {ticker} 生成首份深度分析",
                "category": "generate",
                "priority": 2,
                "action_url": f"/chat?query=深度分析 {ticker}",
                "icon": "Sparkles",
            })

    # --- 2. 新闻任务 ---
    if news_count > 0:
        task_id += 1
        tickers_str = ", ".join(watchlist[:3]) if watchlist else "市场"
        tasks.append({
            "id": f"task_{task_id}",
            "title": f"{news_count} 条未读快讯 ({tickers_str})",
            "category": "news",
            "priority": 2,
            "action_url": "/dashboard",
            "icon": "Newspaper",
        })

    # --- 3. 风险偏好特定任务 ---
    task_id += 1
    if risk_preference == "conservative":
        tasks.append({
            "id": f"task_{task_id}",
            "title": "检查持仓风险敞口 — 关注防御性配置",
            "category": "risk",
            "priority": 2,
            "action_url": "/chat?query=分析我的持仓风险敞口",
            "icon": "Shield",
        })
    elif risk_preference == "aggressive":
        tasks.append({
            "id": f"task_{task_id}",
            "title": "扫描高波动标的机会 — 事件驱动策略",
            "category": "opportunity",
            "priority": 2,
            "action_url": "/chat?query=近期有哪些高波动投资机会",
            "icon": "TrendingUp",
        })
    else:
        tasks.append({
            "id": f"task_{task_id}",
            "title": "组合再平衡检查 — 评估配置偏离度",
            "category": "rebalance",
            "priority": 3,
            "action_url": "/chat?query=我的持仓需要再平衡吗",
            "icon": "BarChart2",
        })

    # 按 priority 排序 (1=高, 3=低), 最多 5 条
    tasks.sort(key=lambda t: t["priority"])
    return tasks[:5]
