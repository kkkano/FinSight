# -*- coding: utf-8 -*-
"""P2-5 英文 claim 中文化 — 中文输出契约测试。

验证两类约束：
1. LLM 分析 prompt 含"中文输出"要求（A 类：prompt 强制中文）。
2. 各 agent 的确定性模板（summary / risks / claim / limitations）不再
   暴露已知的英文模板字符串（B 类：固定英文模板已中文化）。

注：搜索词、外部新闻标题、金融术语缩写（ATR/PCR/IV/Skew/MA）属 C 类原始
数据/术语，保留英文，不在本测试范围内。
"""

import inspect

from backend.agents import base_agent
from backend.agents import fundamental_agent
from backend.agents import macro_agent
from backend.agents import news_agent
from backend.agents import price_agent
from backend.agents import risk_agent


# ── A 类：prompt 含中文输出要求 ──

def test_base_llm_analyze_prompt_requires_chinese():
    """base_agent._llm_analyze 的公共 prompt 必须显式要求中文输出。"""
    src = inspect.getsource(base_agent.BaseFinancialAgent._llm_analyze)
    assert "中文" in src, "公共 _llm_analyze prompt 缺少中文输出要求"


def test_macro_llm_analyze_role_focus_is_chinese():
    """macro agent 的 _llm_analyze role/focus 已中文化。"""
    src = inspect.getsource(macro_agent.MacroAgent)
    assert "资深宏观分析师" in src
    assert "Senior macro analyst" not in src


# ── B 类：确定性英文模板已消除 ──

# 已知应被消除的英文模板片段（出现即视为回归）
_FORBIDDEN_ENGLISH_TEMPLATES = [
    "EPS revisions trend is",
    "Upcoming earnings window",
    "forward earnings expectations may be under pressure",
    "growth quality is",
    "operating cash flow covers net income",
    "EPS revision signal is",
    "liabilities/assets is",
    "Financial-statement snapshot",
    "Cash-flow quality claim",
    "Unable to retrieve macro data",
    "Primary macro sources unavailable",
    "US macro snapshot",
    "Conflicting macro signals detected",
    "Yield-curve inversion warning",
    "Primary macro source unavailable",
    "News source reliability is low",
    "Multiple low-reliability sources",
    "aggregate news sentiment bias is",
    "aggregated news/calendar catalyst events",
    "sentiment-price transmission status is",
    "upcoming scheduled events that can change",
    "news catalyst candidate",
    "secondary news signal or potential noise",
    "aggregate risk score is",
    "factor exposure is elevated",
    "stress-test downside is",
    "Rule-based aggregate risk score",
    "Factor exposure uses model snapshot",
    "Stress test is scenario based",
    "price momentum is",
    "relative strength versus",
    "volume-price confirmation is",
    "volatility regime shows",
    "key level risk centers on",
    "Price momentum uses historical returns",
    "Volume confirmation is a short-horizon",
    "Key levels are derived from recent",
]


def test_no_forbidden_english_templates_in_agents():
    """五个 agent 源码中不应残留已知英文模板字符串。"""
    sources = {
        "fundamental_agent": inspect.getsource(fundamental_agent),
        "macro_agent": inspect.getsource(macro_agent),
        "news_agent": inspect.getsource(news_agent),
        "price_agent": inspect.getsource(price_agent),
        "risk_agent": inspect.getsource(risk_agent),
    }
    offenders = []
    for module_name, src in sources.items():
        for template in _FORBIDDEN_ENGLISH_TEMPLATES:
            if template in src:
                offenders.append(f"{module_name}: {template!r}")
    assert not offenders, "残留英文模板：\n" + "\n".join(offenders)


# ── B 类：确定性方法实际输出为中文 ──

def test_fundamental_eps_signal_text_is_chinese():
    """EPS 修正趋势模板映射为中文。"""
    src = inspect.getsource(fundamental_agent.FundamentalAgent._deterministic_summary)
    assert "EPS 预期修正趋势" in src


def test_macro_deterministic_summary_is_chinese():
    """宏观兜底 summary 各分支为中文。"""
    agent = macro_agent.MacroAgent(None, None, None)
    err = agent._deterministic_summary({"status": "error"})
    assert "无法" in err and "macro" not in err.lower()

    fb = agent._deterministic_summary(
        {"status": "fallback", "indicators": [{"name": "CPI"}]}
    )
    assert "兜底" in fb

    snap = agent._deterministic_summary(
        {"status": "ok", "fed_rate_formatted": "5.5%", "cpi_formatted": "3.0%"}
    )
    assert "美国宏观快照" in snap
    assert "联邦基金利率" in snap


def test_direction_enum_maps_to_chinese():
    """各 agent 方向/等级枚举映射 helper 输出中文。"""
    assert fundamental_agent._direction_cn("positive") == "向好"
    assert fundamental_agent._direction_cn("negative") == "转弱"
    assert news_agent._bias_label_cn("bullish") == "偏多"
    assert news_agent._transmission_status_cn("divergence") == "背离"
    assert risk_agent._risk_level_cn("high") == "高"
    assert price_agent._price_direction_cn("up") == "上行"
    assert price_agent._volume_signal_cn("price_up_volume_confirmed") == "价涨量增确认"
    # 未知值原样返回，不丢数据
    assert fundamental_agent._direction_cn("custom") == "custom"
