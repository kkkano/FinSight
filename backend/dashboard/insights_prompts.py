"""
Prompt templates for Dashboard Digest Agents.

Each template receives pre-fetched dashboard data and produces
a structured JSON InsightCard output.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Shared preamble
# ---------------------------------------------------------------------------

_JSON_INSTRUCTION = """\
严格输出以下 JSON 格式（无任何前缀、后缀或 markdown 标记）:
{
  "score": <0-10 float, 保留1位小数>,
  "score_label": "<弱势|偏空|中性|偏多|强势>",
  "summary": "<200-400字中文分析摘要，必须引用具体数值>",
  "key_points": ["<要点1>", "<要点2>", "<要点3>"],
  "key_metrics": [
    {"label": "<指标名称>", "value": "<具体数值含单位>"},
    {"label": "<指标名称>", "value": "<具体数值含单位>"}
  ],
  "risks": ["<风险1>"]
}

评分标准:
1-3: 明显偏空/不利
4-6: 中性或信号混合
7-10: 明显偏多/有利

约束:
- key_points 3-5 条，risks 1-3 条
- key_metrics 2-4 个，必须为 data 中真实存在的数值指标（如 {label:"市盈率", value:"33.24"}, {label:"RSI", value:"55.3"}）
- 禁止编造不存在于 data 中的数值
- summary 须引用具体数值（如"PE 28.5"，"RSI 55"）
"""


def _truncate_data(data: Any, max_chars: int = 3000) -> str:
    """Serialize data to compact JSON, truncating if too long."""
    try:
        text = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(data)
    if len(text) > max_chars:
        text = text[:max_chars] + "...(truncated)"
    return text


# ---------------------------------------------------------------------------
# Technical Digest Prompt
# ---------------------------------------------------------------------------

def build_technical_prompt(ticker: str, data: dict[str, Any]) -> str:
    return f"""\
<role>资深技术分析师 — 快速诊断模式</role>

<task>
基于以下已计算的 {ticker} 技术指标数据，给出快速技术面诊断。
</task>

<data>
{_truncate_data(data)}
</data>

<output_format>
{_JSON_INSTRUCTION}
</output_format>

<scoring_guide>
1-3: 技术面明显偏空（下降趋势 + RSI超卖/超买 + MACD空头排列）
4-6: 技术面中性或信号混合
7-10: 技术面明显偏多（上升趋势 + 均线多头排列 + MACD金叉）
</scoring_guide>"""


# ---------------------------------------------------------------------------
# Financial Digest Prompt
# ---------------------------------------------------------------------------

def build_financial_prompt(ticker: str, data: dict[str, Any]) -> str:
    return f"""\
<role>资深财务分析师 — 快速诊断模式</role>

<task>
基于以下 {ticker} 的财务报表和估值数据，给出快速财务健康诊断。
重点评估：盈利质量、财务杠杆、估值合理性、现金流状况。
</task>

<data>
{_truncate_data(data)}
</data>

<output_format>
{_JSON_INSTRUCTION}
</output_format>

<scoring_guide>
1-3: 财务状况明显不佳（亏损 + 高杠杆 + 现金流紧张）
4-6: 财务状况中等或存在隐忧
7-10: 财务状况优秀（持续盈利 + 低杠杆 + 充裕现金流 + 合理估值）
</scoring_guide>"""


# ---------------------------------------------------------------------------
# News Digest Prompt
# ---------------------------------------------------------------------------

def build_news_prompt(ticker: str, data: dict[str, Any]) -> str:
    return f"""\
<role>资深财经新闻分析师 — 快速诊断模式</role>

<task>
基于以下 {ticker} 的近期新闻数据，给出新闻情绪诊断和风险预警。
重点关注：重大事件、情绪倾向、潜在风险信号。
</task>

<data>
{_truncate_data(data)}
</data>

<output_format>
{_JSON_INSTRUCTION}
</output_format>

<scoring_guide>
1-3: 负面消息密集（重大利空事件、监管风险、业绩暴雷）
4-6: 新闻中性或正负参半
7-10: 正面消息主导（业绩超预期、产品突破、机构增持）
</scoring_guide>"""


# ---------------------------------------------------------------------------
# Peers Digest Prompt
# ---------------------------------------------------------------------------

def build_peers_prompt(ticker: str, data: dict[str, Any]) -> str:
    return f"""\
<role>行业分析师 — 快速同行对比模式</role>

<task>
基于以下 {ticker} 与同行业公司的对比数据，评估其在行业中的竞争力排名。
重点对比：估值水平、成长性、盈利能力。
</task>

<data>
{_truncate_data(data)}
</data>

<output_format>
{_JSON_INSTRUCTION}
</output_format>

<scoring_guide>
1-3: 明显落后于同行（估值偏高 + 增速落后 + 盈利能力弱）
4-6: 与同行处于相似水平
7-10: 明显优于同行（估值合理 + 增速领先 + 盈利能力强）
</scoring_guide>"""


# ---------------------------------------------------------------------------
# Overview Digest Prompt
# ---------------------------------------------------------------------------

def build_overview_prompt(
    ticker: str,
    data: dict[str, Any],
    sub_scores: dict[str, float] | None = None,
) -> str:
    scores_section = ""
    if sub_scores:
        scores_section = f"""
<dimension_scores>
技术面: {sub_scores.get('technical', 5.0):.1f} / 财务面: {sub_scores.get('financial', 5.0):.1f} / 舆情: {sub_scores.get('news', 5.0):.1f} / 同行: {sub_scores.get('peers', 5.0):.1f}
</dimension_scores>
"""

    return f"""\
<role>首席投资策略师 — 快速综合评估模式</role>

<task>
基于以下 {ticker} 的多维度数据和各维度评分，给出整体投资综合评估。
综合考量技术面、财务面、新闻舆情、同行对比四个维度。
</task>

<data>
{_truncate_data(data, max_chars=2000)}
</data>
{scores_section}
<output_format>
{_JSON_INSTRUCTION}
</output_format>

<scoring_guide>
1-3: 多维度信号共振偏空，不建议当前介入
4-6: 信号分歧较大或整体中性，需要更多信息
7-10: 多维度信号共振偏多，投资前景良好
</scoring_guide>"""
