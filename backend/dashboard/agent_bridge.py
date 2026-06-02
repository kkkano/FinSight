# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


DashboardTab = Literal["overview", "financial", "news", "peers", "technical"]

_CORE_AGENTS: tuple[str, ...] = (
    "price_agent",
    "news_agent",
    "fundamental_agent",
    "technical_agent",
    "macro_agent",
    "risk_agent",
)

_TAB_AGENTS: dict[str, tuple[str, ...]] = {
    "technical": ("technical_agent", "price_agent"),
    "news": ("news_agent",),
    "financial": ("fundamental_agent",),
    "peers": ("price_agent", "fundamental_agent", "risk_agent"),
    "overview": _CORE_AGENTS,
}

_TAB_BUDGET: dict[str, int] = {
    "technical": 4,
    "news": 4,
    "financial": 4,
    "peers": 5,
    "overview": 6,
}

_TAB_LABELS: dict[str, str] = {
    "technical": "技术面",
    "news": "新闻",
    "financial": "财务/基本面",
    "peers": "同行对比",
    "overview": "综合概览",
}

_TAB_INSTRUCTIONS: dict[str, str] = {
    "technical": (
        "重点运行 technical_agent 与 price_agent，解释趋势、动量、关键价位、"
        "量价确认和价格行为风险。"
    ),
    "news": (
        "重点运行 news_agent，判断新闻是否是可交易催化、噪音还是二级信号，"
        "并说明对预期和风险的影响。"
    ),
    "financial": (
        "重点运行 fundamental_agent，检查增长、盈利质量、现金流、EPS 修正和估值支撑。"
    ),
    "peers": (
        "按同行对比任务处理，比较估值、增长、利润率、相对强弱和主要风险差异。"
    ),
    "overview": (
        "按综合深挖处理，联动价格、技术面、新闻、基本面、宏观和风险证据。"
    ),
}

_DEFAULT_QUESTIONS: dict[str, str] = {
    "technical": "这个技术面信号是否值得继续跟进，关键风险位在哪里？",
    "news": "这些新闻对未来几个季度预期和股价风险有什么影响？",
    "financial": "当前财务数据是否支持估值和后续增长预期？",
    "peers": "相对同行，这个标的是更强、更弱，还是风险收益不占优？",
    "overview": "当前 Dashboard 信号综合起来，最重要的机会、风险和下一步验证点是什么？",
}


class DashboardDeepDiveRequest(BaseModel):
    """Dashboard Tab 触发 Agent 深挖的请求体。"""

    symbol: str = Field(..., min_length=1, description="Dashboard 当前标的")
    tab: DashboardTab = Field(..., description="overview/financial/news/peers/technical")
    metric: str | None = Field(None, description="具体深挖指标、新闻标题或对象")
    dashboard_snapshot: Any | None = Field(None, description="当前 Tab 的结构化快照")
    user_question: str | None = Field(None, description="用户在 Tab 上补充的追问")
    session_id: str | None = Field(None, description="会话 ID，沿用 execute 线程语义")
    run_id: str | None = Field(None, description="前端事件关联 ID")
    trace_raw: bool | None = Field(None, description="是否透出完整 trace 事件")

    @field_validator("symbol")
    @classmethod
    def _symbol_must_not_be_blank(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("symbol must not be blank")
        return text


@dataclass(frozen=True)
class DashboardDeepDiveExecution:
    """Bridge 产出的 execute 参数，不直接承载执行逻辑。"""

    query: str
    tickers: list[str]
    output_mode: str
    confirmation_mode: str
    analysis_depth: str
    agents: list[str]
    budget: int
    source: str
    session_id: str | None
    run_id: str | None
    trace_raw: bool | None
    ui_context: dict[str, Any]
    original_query: str


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _clean_text(value: object, *, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."


def _add_unique(values: list[str], value: object, *, primary: str = "") -> None:
    text = _normalize_symbol(str(value or ""))
    if not text or text == primary or text in values:
        return
    values.append(text)


def _extract_peer_tickers(snapshot: object, *, primary: str) -> list[str]:
    if snapshot is None:
        return []

    peers: list[str] = []

    def walk(value: object, depth: int = 0) -> None:
        if len(peers) >= 5 or depth > 3:
            return
        if isinstance(value, dict):
            for key in ("symbol", "ticker"):
                if key in value:
                    _add_unique(peers, value.get(key), primary=primary)
            for key in ("peers", "items", "rows", "data", "comparables", "peer_symbols"):
                if key in value:
                    walk(value.get(key), depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value[:10]:
                if isinstance(item, str):
                    _add_unique(peers, item, primary=primary)
                else:
                    walk(item, depth + 1)
                if len(peers) >= 5:
                    break

    walk(snapshot)
    return peers


def _snapshot_digest(snapshot: object) -> str:
    if snapshot is None:
        return ""

    items: list[str] = []

    def add(label: str, value: object) -> None:
        if len(items) >= 10:
            return
        if value is None:
            return
        if isinstance(value, (str, int, float, bool)):
            text = _clean_text(value, limit=120)
            if text:
                items.append(f"{label}={text}")
            return
        if isinstance(value, list):
            items.append(f"{label}=list[{len(value)}]")
            return
        if isinstance(value, dict):
            items.append(f"{label}=object[{len(value)}]")

    def walk(value: object, prefix: str = "", depth: int = 0) -> None:
        if len(items) >= 10 or depth > 1:
            return
        if isinstance(value, dict):
            for key, inner in value.items():
                key_text = _clean_text(key, limit=40)
                label = f"{prefix}.{key_text}" if prefix else key_text
                if isinstance(inner, dict) and depth < 1:
                    walk(inner, label, depth + 1)
                else:
                    add(label, inner)
                if len(items) >= 10:
                    break
        elif isinstance(value, list):
            add("items", value)
            for index, inner in enumerate(value[:3]):
                if isinstance(inner, dict):
                    walk(inner, f"items[{index}]", depth + 1)
                else:
                    add(f"items[{index}]", inner)
                if len(items) >= 10:
                    break

    walk(snapshot)
    return "；".join(items)


def _build_query(
    *,
    symbol: str,
    tab: str,
    metric: str,
    snapshot_digest: str,
    user_question: str,
    tickers: list[str],
    agents: list[str],
) -> str:
    label = _TAB_LABELS[tab]
    lines = [
        f"Dashboard Deep Dive：请基于 {label} Tab 对 {symbol} 做 agent 深挖。",
        _TAB_INSTRUCTIONS[tab],
        f"优先运行 agents: {', '.join(agents)}。",
        "请先利用 Dashboard 当前 Tab 快照作为上下文，再用后端工具和 agent 结果补证据。",
        "输出适合回填 Dashboard Tab 的中文结论：结论、关键证据、风险/证伪点、下一步观察。",
    ]
    if tab == "peers" and len(tickers) > 1:
        lines.append(f"对比标的：{', '.join(tickers)}。")
    if metric:
        lines.append(f"重点指标/对象：{metric}。")
    if snapshot_digest:
        lines.append(f"当前 Tab 快照摘要：{snapshot_digest}。")
    lines.append(f"用户追问：{user_question or _DEFAULT_QUESTIONS[tab]}")
    return "\n".join(lines)


def build_dashboard_deep_dive_execution(
    request: DashboardDeepDiveRequest,
) -> DashboardDeepDiveExecution:
    symbol = _normalize_symbol(request.symbol)
    tab = str(request.tab).strip().lower()
    metric = _clean_text(request.metric, limit=240)
    user_question = _clean_text(request.user_question, limit=500)
    snapshot = request.dashboard_snapshot
    agents = list(_TAB_AGENTS[tab])
    tickers = [symbol]
    if tab == "peers":
        tickers.extend(_extract_peer_tickers(snapshot, primary=symbol))

    digest = _snapshot_digest(snapshot)
    source = f"dashboard_deep_dive_{tab}"
    budget = _TAB_BUDGET[tab]
    query = _build_query(
        symbol=symbol,
        tab=tab,
        metric=metric,
        snapshot_digest=digest,
        user_question=user_question,
        tickers=tickers,
        agents=agents,
    )
    ui_context: dict[str, Any] = {
        "source": source,
        "view": "dashboard",
        "active_symbol": symbol,
        "dashboard_deep_dive": True,
        "dashboard_tab": tab,
        "tickers_override": tickers,
        "agents_override": agents,
        "budget_override": budget,
        "analysis_depth": "report",
    }
    if metric:
        ui_context["dashboard_metric"] = metric
    if snapshot is not None:
        ui_context["dashboard_snapshot"] = snapshot
    if digest:
        ui_context["dashboard_snapshot_digest"] = digest
    if user_question:
        ui_context["dashboard_user_question"] = user_question

    return DashboardDeepDiveExecution(
        query=query,
        tickers=tickers,
        output_mode="investment_report",
        confirmation_mode="skip",
        analysis_depth="report",
        agents=agents,
        budget=budget,
        source=source,
        session_id=request.session_id,
        run_id=request.run_id,
        trace_raw=request.trace_raw,
        ui_context=ui_context,
        original_query=query,
    )


__all__ = [
    "DashboardDeepDiveExecution",
    "DashboardDeepDiveRequest",
    "DashboardTab",
    "build_dashboard_deep_dive_execution",
]
