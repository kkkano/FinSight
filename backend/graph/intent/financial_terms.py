"""金融术语定义的确定性解析与渲染。"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from backend.graph.state import GraphState


class FinancialTermMatch(BaseModel):
    schema_version: Literal["2026-07-14.financial-term.v1"] = "2026-07-14.financial-term.v1"
    terms: tuple[Literal["pe", "pb", "ps", "peg", "eps", "roe", "roa", "ev_ebitda"], ...] = Field(min_length=1)
    language: Literal["zh", "en"]
    normalized_query: str = Field(min_length=1)


_TERMS: dict[str, dict[str, Any]] = {
    "pe": {
        "aliases": ("市盈率", "p/e", "pe"), "zh": "市盈率", "en": "Price-to-Earnings Ratio (P/E)",
        "definition_zh": "衡量股价相对于每股收益的估值倍数。", "definition_en": "A valuation multiple comparing share price with earnings per share.",
        "formula_zh": "股价 / 每股收益（EPS）", "formula_en": "Share price / earnings per share (EPS)",
        "meaning_zh": "表示投资者为每单位公司盈利支付的价格。", "meaning_en": "It shows how much investors pay for each unit of company earnings.",
        "limit_zh": "EPS 为负或接近 0 时倍数可能无意义；TTM 与 Forward 口径不同。", "limit_en": "The multiple may be meaningless when EPS is negative or near zero; trailing and forward measures differ.",
    },
    "pb": {
        "aliases": ("市净率", "p/b", "pb"), "zh": "市净率", "en": "Price-to-Book Ratio (P/B)",
        "definition_zh": "衡量股价相对于每股净资产的估值倍数。", "definition_en": "A valuation multiple comparing share price with book value per share.",
        "formula_zh": "股价 / 每股净资产", "formula_en": "Share price / book value per share",
        "meaning_zh": "表示市场给予公司账面净资产的定价倍数。", "meaning_en": "It shows the market valuation assigned to a company's net assets.",
        "limit_zh": "轻资产与高商誉行业的横向可比性有限。", "limit_en": "Cross-company comparison is limited for asset-light or goodwill-heavy industries.",
    },
    "ps": {
        "aliases": ("市销率", "p/s", "ps"), "zh": "市销率", "en": "Price-to-Sales Ratio (P/S)",
        "definition_zh": "衡量公司市值相对于营业收入的估值倍数。", "definition_en": "A valuation multiple comparing market capitalization with revenue.",
        "formula_zh": "市值 / 营业收入", "formula_en": "Market capitalization / revenue",
        "meaning_zh": "表示市场为每单位收入支付的价格。", "meaning_en": "It shows how much the market pays for each unit of revenue.",
        "limit_zh": "不反映利润率、资本开支和现金流质量。", "limit_en": "It does not reflect margins, capital expenditure, or cash-flow quality.",
    },
    "peg": {
        "aliases": ("市盈增长比", "peg"), "zh": "市盈增长比", "en": "PEG Ratio",
        "definition_zh": "将市盈率与预期盈利增长率结合的估值指标。", "definition_en": "A valuation measure relating the P/E ratio to expected earnings growth.",
        "formula_zh": "市盈率 / 预期盈利增长率", "formula_en": "P/E ratio / expected earnings growth rate",
        "meaning_zh": "用于观察估值倍数是否与预期增长相匹配。", "meaning_en": "It indicates whether a valuation multiple is aligned with expected growth.",
        "limit_zh": "增长率口径和单位必须一致；负增长时通常不适用。", "limit_en": "Growth definitions and units must be consistent; it is usually unsuitable for negative growth.",
    },
    "eps": {
        "aliases": ("每股收益", "eps"), "zh": "每股收益", "en": "Earnings per Share (EPS)",
        "definition_zh": "衡量归属于每股普通股的公司盈利。", "definition_en": "A measure of profit attributable to each weighted-average common share.",
        "formula_zh": "归属于普通股股东的净利润 / 加权平均普通股股数", "formula_en": "Net income attributable to common shareholders / weighted-average common shares",
        "meaning_zh": "表示公司在每股口径上创造的会计利润。", "meaning_en": "It expresses accounting profit on a per-share basis.",
        "limit_zh": "Basic 与 Diluted 口径不同，非经常项目会影响可比性。", "limit_en": "Basic and diluted measures differ, and non-recurring items affect comparability.",
    },
    "roe": {
        "aliases": ("股东权益回报率", "净资产收益率", "roe"), "zh": "净资产收益率", "en": "Return on Equity (ROE)",
        "definition_zh": "衡量公司使用股东权益创造净利润的效率。", "definition_en": "A profitability ratio measuring net income generated from shareholder equity.",
        "formula_zh": "净利润 / 平均股东权益", "formula_en": "Net income / average shareholder equity",
        "meaning_zh": "表示每单位平均股东权益产生的净利润。", "meaning_en": "It shows net income generated per unit of average shareholder equity.",
        "limit_zh": "高杠杆或回购会机械抬高 ROE。", "limit_en": "High leverage or share buybacks can mechanically increase ROE.",
    },
    "roa": {
        "aliases": ("总资产收益率", "资产回报率", "roa"), "zh": "总资产收益率", "en": "Return on Assets (ROA)",
        "definition_zh": "衡量公司使用全部资产创造净利润的效率。", "definition_en": "A profitability ratio measuring net income generated from total assets.",
        "formula_zh": "净利润 / 平均总资产", "formula_en": "Net income / average total assets",
        "meaning_zh": "表示每单位平均资产产生的净利润。", "meaning_en": "It shows net income generated per unit of average assets.",
        "limit_zh": "资产密集度不同的行业不宜直接横比。", "limit_en": "Industries with different asset intensity should not be compared directly.",
    },
    "ev_ebitda": {
        "aliases": ("企业价值倍数", "ev/ebitda"), "zh": "企业价值/息税折旧摊销前利润", "en": "EV/EBITDA",
        "definition_zh": "衡量企业价值相对于息税折旧摊销前利润的倍数。", "definition_en": "A valuation multiple comparing enterprise value with EBITDA.",
        "formula_zh": "企业价值（EV）/ EBITDA", "formula_en": "Enterprise value (EV) / EBITDA",
        "meaning_zh": "用于在一定程度上弱化资本结构差异后比较企业估值。", "meaning_en": "It helps compare enterprise valuations while reducing some capital-structure differences.",
        "limit_zh": "忽略资本开支与营运资本变化，金融企业通常不适用。", "limit_en": "It ignores capital expenditure and working-capital changes and is usually unsuitable for financial firms.",
    },
}

_ZH_ALLOWED = (
    "用一句话", "如何计算", "怎么理解", "是什么意思", "什么意思", "分别", "各自", "以及", "还有",
    "请问", "麻烦", "帮我", "简单", "简要", "是什么", "怎么算", "含义", "定义", "公式", "解释", "一下", "请", "和", "与",
)
_EN_ALLOWED = (
    "in one sentence", "how are calculated", "how is calculated", "meaning of", "what are", "what is",
    "respectively", "briefly", "please", "explain", "define", "each", "and",
)
_DEFINITION_PHRASES = {
    "是什么", "是什么意思", "什么意思", "含义", "定义", "怎么算", "如何计算", "公式", "怎么理解", "解释",
    "what is", "what are", "define", "meaning of", "explain", "how is calculated", "how are calculated",
}
_PUNCTUATION_RE = re.compile(r"[\s,，、。.!！?？:：;；()（）\[\]{}'\"`]+")
_HAN_RE = re.compile(r"[\u3400-\u9fff]")


def _normalize(query: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(query or "")).strip()).lower()


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias.lower())
    if re.fullmatch(r"[a-z0-9/]+", alias.lower()):
        return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def resolve_financial_term_definition(
    query: str,
    output_mode: str,
    *,
    forced_agent: bool = False,
) -> FinancialTermMatch | None:
    if forced_agent or str(output_mode or "chat").lower() == "investment_report":
        return None
    normalized = _normalize(query)
    if not normalized:
        return None

    candidates: list[tuple[int, int, str]] = []
    aliases = sorted(
        ((alias, key) for key, item in _TERMS.items() for alias in item["aliases"]),
        key=lambda pair: len(pair[0]), reverse=True,
    )
    occupied: list[tuple[int, int]] = []
    for alias, key in aliases:
        for match in _alias_pattern(alias).finditer(normalized):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            candidates.append((span[0], span[1], key))
    if not candidates:
        return None
    candidates.sort()

    remainder_chars = list(normalized)
    terms: list[str] = []
    for start, end, key in candidates:
        remainder_chars[start:end] = " " * (end - start)
        if key not in terms:
            terms.append(key)
    remainder = "".join(remainder_chars)

    consumed_phrases: list[str] = []
    phrases = sorted((*_ZH_ALLOWED, *_EN_ALLOWED), key=len, reverse=True)
    changed = True
    while changed:
        changed = False
        remainder = _PUNCTUATION_RE.sub(" ", remainder).strip()
        for phrase in phrases:
            pattern = _alias_pattern(phrase) if re.fullmatch(r"[a-z ]+", phrase) else re.compile(re.escape(phrase))
            match = pattern.search(remainder)
            if match:
                remainder = remainder[:match.start()] + " " + remainder[match.end():]
                consumed_phrases.append(phrase)
                changed = True
                break
    if _PUNCTUATION_RE.sub("", remainder) or not any(phrase in _DEFINITION_PHRASES for phrase in consumed_phrases):
        return None
    language = "zh" if _HAN_RE.search(normalized) or any(phrase in _ZH_ALLOWED for phrase in consumed_phrases) else "en"
    return FinancialTermMatch(terms=tuple(terms), language=language, normalized_query=normalized)


def render_financial_term_definition(match: FinancialTermMatch) -> str:
    blocks: list[str] = []
    for key in match.terms:
        item = _TERMS[key]
        if match.language == "zh":
            blocks.append("\n".join((
                f"### {item['zh']}", f"定义：{item['definition_zh']}", f"公式：{item['formula_zh']}",
                f"如何理解：{item['meaning_zh']}", f"口径/限制：{item['limit_zh']}",
            )))
        else:
            blocks.append("\n".join((
                f"### {item['en']}", f"Definition: {item['definition_en']}", f"Formula: {item['formula_en']}",
                f"Interpretation: {item['meaning_en']}", f"Scope/limitations: {item['limit_en']}",
            )))
    return "\n\n".join(blocks)


def build_financial_term_direct_result(state: GraphState, match: FinancialTermMatch) -> dict[str, Any]:
    query = str(state.get("query") or "")
    output_mode = str(state.get("output_mode") or "chat")
    rendered_text = render_financial_term_definition(match)
    frame = {
        "schema_version": "intent_frame/v1", "route": "direct", "query": query, "output_mode": output_mode,
        "language": match.language, "tasks": [], "blocked": [], "context_refs": [], "fallback_assumptions": [],
        "reply_plan": {}, "confidence": 1.0, "source": "deterministic_term_resolver",
    }
    understanding = {
        "route": "direct", "original_query": query, "cleaned_query": query, "language": match.language,
        "user_visible_summary": "固定术语定义", "tasks": [], "blocked_tasks": [], "context_refs": [],
        "fallback_assumptions": [], "confidence": 1.0, "output_mode": output_mode, "intent_frame": frame,
    }
    trace = dict(state.get("trace") or {})
    events = list(trace.get("events") or [])
    events.append({
        "schema_version": match.schema_version, "terms": list(match.terms), "matched": True,
        "event": "financial_term_resolved", "duration_ms": 0,
    })
    trace["events"] = events
    return {
        "messages": [AIMessage(content=rendered_text)], "output_mode": output_mode, "understanding": understanding,
        "tasks": [], "blocked_tasks": [], "chat_responded": True,
        "artifacts": {**dict(state.get("artifacts") or {}), "draft_markdown": rendered_text}, "trace": trace,
    }


__all__ = [
    "FinancialTermMatch", "build_financial_term_direct_result", "render_financial_term_definition",
    "resolve_financial_term_definition",
]
