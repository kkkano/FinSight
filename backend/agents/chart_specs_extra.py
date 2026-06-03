# -*- coding: utf-8 -*-
"""technical / macro / risk 三个 agent 的图表规格构建函数。

与 chart_specs.py 同构：每个 spec 形如 {type, title, data}，data 字段名
必须与前端 SmartChart 的 SmartChartData 对齐（labels/values/unit/series/ohlc）。

诚实原则：只画真实存在的结构化数据，数据不足一律返回 []。
"""
from __future__ import annotations

from typing import Any

from backend.agents.chart_specs import _kline_rows, _ohlc_from_rows, _safe_float


# ---------------------------------------------------------------------------
#  technical：K线 + 均线对比 + RSI 仪表盘
# ---------------------------------------------------------------------------
def build_technical_chart_specs(ticker: str, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """技术分析图表。

    数据来源：TechnicalAgent._format_output 传入的 raw_data，含 kline_data(OHLC)。
    - candlestick：基于 kline_data 的 OHLC 序列
    - bar：收盘价 vs MA20/MA50/MA200 的横向对比（真实算出的均线值）
    - gauge：RSI(14) 当前读数（0-100，天然适配仪表盘）

    数据不足时返回 []。
    """
    if not isinstance(snapshot, dict):
        return []

    ticker_label = str(ticker or snapshot.get("ticker") or "Technical").strip().upper() or "Technical"
    rows = _kline_rows(snapshot)
    if not rows:
        return []

    specs: list[dict[str, Any]] = []

    # 1) K线图：直接复用 chart_specs 的 OHLC 构建逻辑
    ohlc_data = _ohlc_from_rows(rows)
    if ohlc_data:
        specs.append(
            {
                "type": "candlestick",
                "title": f"{ticker_label} candlestick",
                "data": ohlc_data,
            }
        )

    # 2) 均线对比 + RSI 仪表盘：依赖技术指标计算结果
    indicators = _compute_indicators_for_chart(rows)
    if indicators:
        ma_labels: list[str] = []
        ma_values: list[float] = []
        close = indicators.get("close")
        if close is not None:
            ma_labels.append("Close")
            ma_values.append(round(float(close), 4))
        for key, label in (("ma20", "MA20"), ("ma50", "MA50"), ("ma200", "MA200")):
            value = indicators.get(key)
            if value is not None:
                ma_labels.append(label)
                ma_values.append(round(float(value), 4))
        # 至少 close + 一条均线才有对比意义
        if len(ma_labels) >= 2:
            specs.append(
                {
                    "type": "bar",
                    "title": f"{ticker_label} price vs moving averages",
                    "data": {"labels": ma_labels, "values": ma_values},
                }
            )

        rsi = indicators.get("rsi")
        if rsi is not None:
            specs.append(
                {
                    "type": "gauge",
                    "title": f"{ticker_label} RSI(14)",
                    "data": {"labels": ["RSI(14)"], "values": [round(float(rsi), 2)]},
                }
            )

    return specs


def _compute_indicators_for_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """从 kline 行计算图表所需的指标（close / MA / RSI）。

    独立实现，避免依赖 pandas 与 TechnicalAgent 内部细节；逻辑与
    TechnicalAgent._compute_indicators 一致（简单移动平均 + 标准 RSI）。
    数据点不足（<30）返回 None。
    """
    closes: list[float] = []
    for row in rows:
        value = _safe_float(row.get("close") or row.get("Close"))
        if value is not None:
            closes.append(value)
    if len(closes) < 30:
        return None

    def _ma(window: int) -> float | None:
        if len(closes) < window:
            return None
        return sum(closes[-window:]) / window

    return {
        "close": closes[-1],
        "ma20": _ma(20),
        "ma50": _ma(50),
        "ma200": _ma(200),
        "rsi": _calc_rsi(closes, 14),
    }


def _calc_rsi(closes: list[float], window: int = 14) -> float | None:
    """标准 RSI(14)：基于平均涨幅/跌幅。数据不足返回 None。"""
    if len(closes) < window + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, curr in zip(closes[-(window + 1):-1], closes[-window:]):
        delta = curr - prev
        if delta >= 0:
            gains.append(delta)
        else:
            losses.append(-delta)
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


# ---------------------------------------------------------------------------
#  macro：宏观指标横截面柱状图
# ---------------------------------------------------------------------------
def build_macro_chart_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """宏观图表。

    数据来源：MacroAgent._initial_search 产出的 indicators 列表，每项含
    {key, name, value, unit, source}。这是**横截面快照**（各指标当前读数），
    不含历史时序，因此画横向柱状图而非时序 line（诚实原则）。

    数据不足（无有效数值指标）时返回 []。
    """
    if not isinstance(snapshot, dict):
        return []

    indicators = snapshot.get("indicators")
    if not isinstance(indicators, list):
        return []

    labels: list[str] = []
    values: list[float] = []
    unit_set: set[str] = set()
    for item in indicators:
        if not isinstance(item, dict):
            continue
        value = _safe_float(item.get("value"))
        if value is None:
            continue
        name = str(item.get("name") or item.get("key") or "Indicator").strip()
        if not name:
            continue
        labels.append(name)
        values.append(round(value, 4))
        unit = str(item.get("unit") or "").strip()
        if unit:
            unit_set.add(unit)

    # 至少 2 个指标才值得画对比柱状图
    if len(labels) < 2:
        return []

    data: dict[str, Any] = {"labels": labels, "values": values}
    # 所有指标单位一致时才挂 unit（多数宏观指标都是 %）
    if len(unit_set) == 1:
        data["unit"] = next(iter(unit_set))

    return [
        {
            "type": "bar",
            "title": "US macro indicators",
            "data": data,
        }
    ]


# ---------------------------------------------------------------------------
#  risk：风险维度雷达图 + 综合风险仪表盘
# ---------------------------------------------------------------------------
# 与 RiskAgent.CATEGORY_WEIGHTS 对齐的维度顺序与中文标签
_RISK_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("technical", "技术面"),
    ("fundamental", "基本面"),
    ("macro", "宏观面"),
    ("news", "舆情面"),
    ("data_quality", "数据质量"),
)


def build_risk_chart_specs(
    ticker: str,
    risk_score: float | None,
    risk_level: str | None,
    dimension_scores: dict[str, float] | None,
) -> list[dict[str, Any]]:
    """风险图表。

    数据来源：RiskAgent.research 产出的 RiskAssessment。
    - radar：5 个风险维度（technical/fundamental/macro/news/data_quality）的
      0-100 评分，由各维度信号 severity 聚合而来
    - gauge：综合风险分 0-100

    雷达图采用全量 5 维等尺度展示；至少 3 个维度有真实风险（>0）才画，
    避免退化成单尖刺、失去分布对比意义。综合分缺失时不画仪表盘。
    全部不足时返回 []。
    """
    ticker_label = str(ticker or "Risk").strip().upper() or "Risk"
    specs: list[dict[str, Any]] = []

    # 1) 风险维度雷达图（全量 5 维等尺度，需 >=3 维有真实风险信号才有对比意义）
    if isinstance(dimension_scores, dict):
        labels: list[str] = []
        values: list[float] = []
        for key, label in _RISK_DIMENSIONS:
            score = _safe_float(dimension_scores.get(key)) or 0.0
            labels.append(label)
            values.append(round(max(0.0, min(100.0, score)), 2))
        nonzero_dims = sum(1 for v in values if v > 0)
        if nonzero_dims >= 3:
            specs.append(
                {
                    "type": "radar",
                    "title": f"{ticker_label} risk dimensions",
                    "data": {"labels": labels, "values": values},
                }
            )

    # 2) 综合风险仪表盘
    score_value = _safe_float(risk_score)
    if score_value is not None:
        label = str(risk_level or "risk").strip() or "risk"
        specs.append(
            {
                "type": "gauge",
                "title": f"{ticker_label} risk score",
                "data": {
                    "labels": [label],
                    "values": [round(max(0.0, min(100.0, score_value)), 2)],
                },
            }
        )

    return specs


# ---------------------------------------------------------------------------
#  deep_search：搜索结果时间分布柱状图 + 来源分布饼图
# ---------------------------------------------------------------------------
def _parse_doc_date(value: Any) -> str | None:
    """从文档的 published_date 解析出 YYYY-MM-DD；无法解析返回 None。

    与 DeepSearchAgent._freshness_score 同构的容错策略：兼容尾部 Z、
    纯日期、带时间的 ISO 串。任何异常一律降级为 None（诚实，不编造日期）。
    """
    text = str(value or "").strip()
    if not text:
        return None
    # 优先匹配前缀里的 YYYY-MM-DD（覆盖 "2026-05-01"、"2026-05-01T08:00:00Z" 等）
    prefix = text[:10]
    try:
        from datetime import date as _date

        _date.fromisoformat(prefix)
        return prefix
    except (ValueError, TypeError):
        pass
    # 退路：尝试完整 ISO 解析（兼容尾部 Z）
    try:
        from datetime import datetime as _datetime

        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        return _datetime.fromisoformat(normalized).date().isoformat()
    except (ValueError, TypeError):
        return None


def build_deepsearch_chart_specs(
    docs: list[dict[str, Any]] | None, query: str = ""
) -> list[dict[str, Any]]:
    """深度搜索图表：搜索结果时间分布（bar）+ 来源分布（pie）。

    数据来源：DeepSearchAgent._format_output 传入的 raw_data 文档列表，每项含
    {title, url, snippet, source, published_date, confidence, degraded, ...}。

    - bar：按 published_date(YYYY-MM-DD) 分组计数，只保留最近 14 天；无法解析
      日期的文档归入「未知日期」组，但若全部都是未知日期则不画这张图。
    - pie：按 source 分组计数，仅在 >=2 个不同来源时才画。

    诚实原则：docs 非 list / 为空 / 全部不是 dict / 缺关键字段 → 返回空列表，
    绝不编造数据。
    """
    if not isinstance(docs, list) or not docs:
        return []

    valid_docs = [doc for doc in docs if isinstance(doc, dict)]
    if not valid_docs:
        return []

    specs: list[dict[str, Any]] = []
    query_label = str(query or "").strip()

    # 1) 搜索结果时间分布（bar）：最近 14 天 + 未知日期组
    date_counts: dict[str, int] = {}
    unknown_count = 0
    for doc in valid_docs:
        parsed = _parse_doc_date(doc.get("published_date"))
        if parsed is None:
            unknown_count += 1
        else:
            date_counts[parsed] = date_counts.get(parsed, 0) + 1

    # 已解析日期按时间升序取最近 14 个
    sorted_dates = sorted(date_counts.keys())[-14:]
    has_real_dates = bool(sorted_dates)
    if has_real_dates:
        labels = list(sorted_dates)
        values = [date_counts[d] for d in sorted_dates]
        # 仅当存在真实日期时，未知日期才作为额外一组补在末尾
        if unknown_count > 0:
            labels.append("未知日期")
            values.append(unknown_count)
        title = "搜索结果时间分布"
        if query_label:
            title = f"搜索结果时间分布 · {query_label}"
        specs.append(
            {
                "type": "bar",
                "title": title,
                "data": {"labels": labels, "values": values},
            }
        )

    # 2) 来源分布（pie）：>=2 个不同来源才画
    source_counts: dict[str, int] = {}
    for doc in valid_docs:
        source = str(doc.get("source") or "").strip()
        if not source:
            continue
        source_counts[source] = source_counts.get(source, 0) + 1

    if len(source_counts) >= 2:
        # 按计数降序，计数相同按来源名稳定排序
        ordered = sorted(source_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        specs.append(
            {
                "type": "pie",
                "title": "信息来源分布",
                "data": {
                    "labels": [name for name, _ in ordered],
                    "values": [count for _, count in ordered],
                },
            }
        )

    return specs


__all__ = [
    "build_technical_chart_specs",
    "build_macro_chart_specs",
    "build_risk_chart_specs",
    "build_deepsearch_chart_specs",
]
