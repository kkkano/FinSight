# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/synthesize.py 的 _stub_render_vars（WP3 Task4，零行为变更）。
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from backend.graph.executor import summarize_selection
from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState
from backend.graph.render_vars.model import RenderVars
from backend.graph.render_vars.access import _get_agent_output, _get_tool_output

logger = logging.getLogger(__name__)


def _collect_conflict_disclosure(ctx) -> str:
    """
    Trigger formula:
      detect = deep_report || (success_agents >= 2 && comparable_claims >= 1)

    - deep_report: output_mode == 'investment_report'
    - success_agents: agents that returned non-skipped dict output
    - comparable_claims: number of comparable agent pairs with both sides successful

    Edge cases:
    - 0 successful agents  → skip entirely
    - 1 successful agent   → if deep_report, emit "冲突检测降级（证据不足）"
    - Single price query   → skip (handled by success_agents < 2)
    """
    all_agent_names = ("price_agent", "news_agent", "fundamental_agent", "technical_agent", "macro_agent")

    # 1) Count successful agents and collect their outputs
    success_outputs: dict[str, dict[str, Any]] = {}
    for aname in all_agent_names:
        a_out = _get_agent_output(ctx, aname)
        if isinstance(a_out, dict) and a_out.get("summary"):
            success_outputs[aname] = a_out
    success_count = len(success_outputs)

    # 2) Count comparable claims (pairs where both sides succeeded)
    comparable_claims_count = 0
    comparable_topics: list[str] = []
    for agent_a, agent_b, topic in ctx._COMPARABLE_PAIRS:
        if agent_a in success_outputs and agent_b in success_outputs:
            comparable_claims_count += 1
            comparable_topics.append(topic)

    # 3) Determine if this is a deep report
    is_deep_report = ctx.output_mode == "investment_report"

    # 4) Apply trigger formula: detect = deep_report || (success >= 2 && comparable >= 1)
    should_detect = is_deep_report or (success_count >= 2 and comparable_claims_count >= 1)

    if not should_detect:
        return ""

    # 5) Edge case: deep report with only 1 agent → degraded mode
    if is_deep_report and success_count <= 1:
        return (
            "**冲突检测降级（证据不足）：**\n\n"
            f"仅 {success_count} 个智能体成功返回数据，"
            "无法执行跨维度交叉验证。建议：\n"
            "- 检查数据源连通性（API Key、网络）\n"
            "- 重试以获取更多智能体输出\n"
            "- 当前结论仅基于单一维度，可信度受限\n"
        )

    # 6) Collect actual conflict_flags and conflicting_claims from successful agents
    all_flags: list[str] = []
    all_claims: list[dict[str, Any]] = []
    for aname, a_out in success_outputs.items():
        flags = a_out.get("conflict_flags")
        if isinstance(flags, list):
            for f in flags:
                if isinstance(f, str) and f.strip():
                    all_flags.append(f"[{aname.replace('_agent', '')}] {f.strip()}")
        claims = a_out.get("conflicting_claims")
        if isinstance(claims, list):
            for c in claims:
                if isinstance(c, dict):
                    all_claims.append({**c, "_agent": aname})

    # 7) Build disclosure text
    lines: list[str] = []

    # Header with detection context
    detection_basis = "深度研报模式" if is_deep_report else f"{success_count} 个智能体成功 + {comparable_claims_count} 组可比命题"
    lines.append(f"**冲突检测（{detection_basis}）：**")
    lines.append("")

    if not all_claims:
        # No conflicts found — positive signal
        lines.append(f"✅ 已完成 {comparable_claims_count} 组跨维度交叉验证，未发现显著数据冲突。")
        if comparable_topics:
            lines.append(f"   验证维度：{', '.join(comparable_topics[:6])}")
        return "\n".join(lines)

    lines[0] = f"**跨智能体数据冲突（共 {len(all_claims)} 项，检测基础：{detection_basis}）：**"
    lines.append("")

    for idx, claim in enumerate(all_claims[:8], 1):
        agent_label = str(claim.get("_agent", "")).replace("_agent", "")
        topic = claim.get("claim", "未知")
        src_a = claim.get("source_a", "?")
        val_a = claim.get("value_a", "?")
        src_b = claim.get("source_b", "?")
        val_b = claim.get("value_b", "?")
        severity = claim.get("severity", "medium")
        resolved = claim.get("resolved", False)
        resolution = claim.get("resolution", "")

        severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
        status = f"✅ {resolution}" if resolved and resolution else "❓ 待进一步验证"

        lines.append(f"{idx}. {severity_icon} **{topic}**（{agent_label}）")
        lines.append(f"   - {src_a}: {val_a}")
        lines.append(f"   - {src_b}: {val_b}")
        lines.append(f"   - 裁决: {status}")
        lines.append("")

    unresolved = [c for c in all_claims if not c.get("resolved", False)]
    if unresolved:
        lines.append(f"⚠️ {len(unresolved)} 项冲突未裁决，结论可信度需打折。建议关注后续数据更新。")

    return "\n".join(lines)


def _build_conclusion_from_agents(ctx) -> str:
    """
    Generate a substantive conclusion with actionable insights,
    not just a list of confidence percentages.
    """
    ticker_label = ", ".join(ctx.tickers) if ctx.tickers else "标的"
    lines: list[str] = []

    # 1) Overall signal summary
    tech_out = _get_agent_output(ctx, "technical_agent")
    fund_out = _get_agent_output(ctx, "fundamental_agent")
    price_out = _get_agent_output(ctx, "price_agent")
    macro_out = _get_agent_output(ctx, "macro_agent")

    # Technical takeaway
    if isinstance(tech_out, dict) and tech_out.get("summary"):
        ts = str(tech_out["summary"]).strip()
        ts_lower = ts.lower()
        if "overbought" in ts_lower:
            lines.append(f"**技术面**：{ticker_label} RSI 进入超买区域，短期存在回调概率。建议关注支撑位和成交量变化，若缩量上涨则回调风险加大。")
        elif "oversold" in ts_lower:
            lines.append(f"**技术面**：{ticker_label} RSI 处于超卖区域，存在技术性反弹可能。关注能否放量突破关键阻力位。")
        elif "sideways" in ts_lower:
            lines.append(f"**技术面**：{ticker_label} 趋势偏震荡，缺乏明确方向。适合区间操作或等待突破信号。")
        elif "bullish" in ts_lower:
            lines.append(f"**技术面**：{ticker_label} 技术指标偏多，MACD 呈多头排列。关注能否延续趋势。")
        elif "bearish" in ts_lower:
            lines.append(f"**技术面**：{ticker_label} 技术指标偏空，注意防范进一步下行风险。")

    # Fundamental takeaway
    if isinstance(fund_out, dict):
        evidence = fund_out.get("evidence")
        if isinstance(evidence, list) and len(evidence) >= 2:
            growth_signals: list[str] = []
            for ev in evidence:
                if not isinstance(ev, dict):
                    continue
                meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
                yoy = meta.get("yoy")
                text = str(ev.get("text") or "")
                if isinstance(yoy, (int, float)) and abs(yoy) > 0.03:
                    short_label = text.split(":")[0].strip()[:30] if ":" in text else text[:30]
                    growth_signals.append(f"{short_label} (YoY {yoy:+.1%})")
            if growth_signals:
                lines.append(f"**基本面**：关键财务指标 — {'; '.join(growth_signals[:3])}。{'整体增长态势良好。' if sum(1 for g in growth_signals if '+' in g) > len(growth_signals) / 2 else '部分指标承压，需关注趋势。'}")

    # Macro context
    if isinstance(macro_out, dict) and macro_out.get("summary"):
        ms = str(macro_out["summary"]).strip()
        if ms and len(ms) > 20:
            lines.append(f"**宏观环境**：{ms[:600]}")

    # 2) Action items / watch points
    watch_items: list[str] = []
    watch_items.append("关注下一财报季的营收指引和利润率变化")
    if isinstance(tech_out, dict) and tech_out.get("summary"):
        ts_lower = str(tech_out["summary"]).lower()
        if "overbought" in ts_lower or "bearish" in ts_lower:
            watch_items.append("设定止损位，控制回撤风险")
        elif "oversold" in ts_lower or "bullish" in ts_lower:
            watch_items.append("可考虑分批建仓，关注成交量配合")
    watch_items.append("跟踪行业政策和竞争格局变化")

    if watch_items:
        lines.append("")
        lines.append("**后续关注：**")
        for w in watch_items[:4]:
            lines.append(f"- {w}")

    if not lines:
        lines = [
            f"- {ctx.report_hint} 查询：{ctx.query or 'N/A'}",
            "- 当前数据不足以给出明确结论，建议补充更多信息源后重新分析。",
        ]
    return "\n".join(lines)


def _build_investment_summary_from_agents(ctx) -> str:
    """Brief bullet summary of each agent's key finding."""
    lines: list[str] = []
    price_out = _get_agent_output(ctx, "price_agent")
    if isinstance(price_out, dict) and price_out.get("summary"):
        lines.append(f"- {str(price_out['summary']).strip()[:800]}")
    fund_out = _get_agent_output(ctx, "fundamental_agent")
    if isinstance(fund_out, dict) and fund_out.get("summary"):
        lines.append(f"- {str(fund_out['summary']).strip()[:800]}")
    tech_out = _get_agent_output(ctx, "technical_agent")
    if isinstance(tech_out, dict) and tech_out.get("summary"):
        lines.append(f"- {str(tech_out['summary']).strip()[:800]}")
    if not lines:
        lines = [
            '- 研报为结构化交付物：会更长、更全面，但不等于\u201c必须跑全家桶\u201d。',
            '- 如果缺少关键证据（财报/新闻/数据），会明确标注缺口。',
        ]
    return "\n".join(lines)


def _build_investment_thesis(ctx) -> str:
    """
    Cross-reference ALL agent outputs to produce a high-value
    investment thesis: directional view, key drivers, and watch-points.
    """
    ticker_label = ", ".join(ctx.tickers) if ctx.tickers else "标的"
    sections: list[str] = []

    # --- 1. Aggregate signals ---
    bullish_factors: list[str] = []
    bearish_factors: list[str] = []
    neutral_notes: list[str] = []

    # Price agent
    price_out = _get_agent_output(ctx, "price_agent")
    if isinstance(price_out, dict) and price_out.get("summary"):
        ps = str(price_out["summary"]).strip()
        if "up" in ps.lower() or "上涨" in ps:
            bullish_factors.append("近期股价呈上行趋势")
        elif "down" in ps.lower() or "下跌" in ps:
            bearish_factors.append("近期股价承压下行")

    # Technical agent
    tech_out = _get_agent_output(ctx, "technical_agent")
    tech_trend = ""
    if isinstance(tech_out, dict) and tech_out.get("summary"):
        ts = str(tech_out["summary"]).strip().lower()
        if "overbought" in ts:
            bearish_factors.append("RSI 显示超买，短期存在回调压力")
            tech_trend = "超买"
        elif "oversold" in ts:
            bullish_factors.append("RSI 显示超卖，技术面存在反弹机会")
            tech_trend = "超卖"
        if "bullish" in ts:
            bullish_factors.append("MACD 呈多头信号")
            if not tech_trend:
                tech_trend = "偏多"
        elif "bearish" in ts:
            bearish_factors.append("MACD 呈空头信号")
            if not tech_trend:
                tech_trend = "偏空"
        if "sideways" in ts:
            neutral_notes.append("技术面趋势偏横盘震荡")
            if not tech_trend:
                tech_trend = "震荡"

    # Fundamental agent
    fund_out = _get_agent_output(ctx, "fundamental_agent")
    if isinstance(fund_out, dict):
        evidence = fund_out.get("evidence")
        if isinstance(evidence, list):
            for ev in evidence:
                if not isinstance(ev, dict):
                    continue
                meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
                yoy = meta.get("yoy")
                text = str(ev.get("text") or "").lower()
                if isinstance(yoy, (int, float)):
                    if "revenue" in text or "营收" in text:
                        if yoy > 0.05:
                            bullish_factors.append(f"营收同比增长 {yoy:+.1%}，增长动能良好")
                        elif yoy < -0.05:
                            bearish_factors.append(f"营收同比下降 {yoy:+.1%}，增长承压")
                    if "net income" in text or "净利润" in text:
                        if yoy > 0.1:
                            bullish_factors.append(f"净利润同比增长 {yoy:+.1%}，盈利能力改善")
                        elif yoy < -0.1:
                            bearish_factors.append(f"净利润同比下降 {yoy:+.1%}，盈利能力恶化")

    # Macro agent
    macro_out = _get_agent_output(ctx, "macro_agent")
    if isinstance(macro_out, dict) and macro_out.get("summary"):
        ms = str(macro_out["summary"]).strip()
        if ms and len(ms) > 20:
            neutral_notes.append(f"宏观环境：{ms[:600]}")

    # News agent
    news_out = _get_agent_output(ctx, "news_agent")
    if isinstance(news_out, dict) and news_out.get("summary"):
        ns = str(news_out["summary"]).strip()
        if ns and len(ns) > 20:
            neutral_notes.append(f"近期事件：{ns[:600]}")

    # --- 2. Determine directional view ---
    bull_count = len(bullish_factors)
    bear_count = len(bearish_factors)
    if bull_count >= bear_count + 2:
        direction = "偏多（Bullish）"
        direction_detail = "多数维度信号偏积极"
    elif bear_count >= bull_count + 2:
        direction = "偏空（Bearish）"
        direction_detail = "多数维度信号偏谨慎"
    elif bull_count > bear_count:
        direction = "中性偏多（Slightly Bullish）"
        direction_detail = "积极信号略占优，但需关注风险因素"
    elif bear_count > bull_count:
        direction = "中性偏空（Slightly Bearish）"
        direction_detail = "谨慎信号略占优，短期不宜激进"
    else:
        direction = "中性（Neutral）"
        direction_detail = "多空信号交织，建议观望或分批操作"

    sections.append(f"**{ticker_label} 综合研判：{direction}**")
    sections.append(f"")
    sections.append(f"{direction_detail}。以下为多维度交叉验证结论：")
    sections.append("")

    # --- 3. Key factors ---
    if bullish_factors:
        sections.append("**利多因素：**")
        for f in bullish_factors[:4]:
            sections.append(f"- ✅ {f}")
        sections.append("")

    if bearish_factors:
        sections.append("**利空因素：**")
        for f in bearish_factors[:4]:
            sections.append(f"- ⚠️ {f}")
        sections.append("")

    if neutral_notes:
        sections.append("**背景与参考：**")
        for n in neutral_notes[:3]:
            sections.append(f"- {n}")
        sections.append("")

    # --- 4. Data quality note ---
    agent_names = ["fundamental_agent", "price_agent", "news_agent", "technical_agent", "macro_agent"]
    coverage: list[str] = []
    for aname in agent_names:
        a_out = _get_agent_output(ctx, aname)
        if isinstance(a_out, dict) and a_out.get("confidence"):
            try:
                conf = float(a_out["confidence"])
                label = aname.replace("_agent", "")
                coverage.append(f"{label} {conf:.0%}")
            except (ValueError, TypeError):
                logger.debug("agent confidence is not numeric", exc_info=True)
    if coverage:
        sections.append(f"**数据置信度：** {' | '.join(coverage)}")
        sections.append("")

    return "\n".join(sections)


def _build_company_overview_from_agents(ctx) -> str:
    # Try get_company_info tool output first
    info_out = _get_tool_output(ctx, "get_company_info")
    if isinstance(info_out, dict):
        name = info_out.get("name") or info_out.get("shortName") or ""
        sector = info_out.get("sector") or ""
        industry = info_out.get("industry") or ""
        mkt_cap = info_out.get("marketCap") or info_out.get("market_cap") or ""
        desc = info_out.get("longBusinessSummary") or info_out.get("description") or ""
        lines: list[str] = []
        if name:
            header_parts = [name]
            if sector:
                header_parts.append(sector)
            if industry:
                header_parts.append(industry)
            lines.append("- " + " | ".join(header_parts))
        if mkt_cap:
            lines.append(f"- Market Cap: {mkt_cap}")
        if desc:
            lines.append(f"- {str(desc).strip()[:500]}")
        if lines:
            return "\n".join(lines)
    elif isinstance(info_out, str) and info_out.strip():
        # Tool returned a formatted string (e.g. "Company Profile (AAPL):\n...")
        text = info_out.strip()[:800]
        # Convert each line to bullet format if not already
        lines = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            if ln.startswith("- "):
                lines.append(ln)
            elif ln.startswith("Company Profile"):
                continue  # skip header line
            else:
                lines.append(f"- {ln}")
        if lines:
            return "\n".join(lines)
    # Fallback: use fundamental_agent summary
    fund_out = _get_agent_output(ctx, "fundamental_agent")
    if isinstance(fund_out, dict) and fund_out.get("summary"):
        return f"- {str(fund_out['summary']).strip()[:1200]}"
    return "- 公司概况：暂无数据。"


def _build_catalysts_from_agents(ctx) -> str:
    news_out = _get_agent_output(ctx, "news_agent")
    if isinstance(news_out, dict) and news_out.get("summary"):
        return f"- {str(news_out['summary']).strip()[:1200]}"
    return "\n".join([
        "- 可能催化：财报、产品发布、政策变化、行业景气度变化。",
        "- 将基于新闻/财报证据进一步细化。",
    ])


def _build_valuation_from_agents(ctx) -> str:
    fund_out = _get_agent_output(ctx, "fundamental_agent")
    if isinstance(fund_out, dict):
        # Prefer structured evidence for clean line items
        evidence = fund_out.get("evidence")
        if isinstance(evidence, list) and evidence:
            lines: list[str] = []
            for ev in evidence:
                if not isinstance(ev, dict):
                    continue
                text = str(ev.get("text") or "").strip()
                if not text:
                    continue
                meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
                yoy = meta.get("yoy")
                if isinstance(yoy, (int, float)):
                    text += f" (YoY {yoy:+.1%})"
                lines.append(f"- {text}")
            if lines:
                return "\n".join(lines[:10])
        # Fallback to summary but filter out company header
        summary = str(fund_out.get("summary") or "").strip()
        if summary:
            lines = []
            for part in summary.split(". "):
                part = part.strip()
                if not part:
                    continue
                # Skip company header parts (name | sector | industry)
                if "|" in part and any(kw in part for kw in ("Technology", "Consumer", "Healthcare", "Financial")):
                    continue
                lines.append(f"- {part}")
            if lines:
                return "\n".join(lines[:8])
    return "\n".join([
        "- 估值与财务：暂无数据。",
        "- 常见框架：增长 vs 估值倍数、盈利质量、现金流与风险溢价。",
    ])


def _build_risks_from_agents(ctx) -> str:
    risk_lines: list[str] = []
    for aname in ("fundamental_agent", "technical_agent", "news_agent", "macro_agent"):
        a_out = _get_agent_output(ctx, aname)
        if not isinstance(a_out, dict):
            continue
        agent_risks = a_out.get("risks")
        if isinstance(agent_risks, list):
            for r in agent_risks:
                r_text = str(r).strip()[:300]
                if r_text and r_text not in risk_lines:
                    risk_lines.append(r_text)
    if risk_lines:
        return "\n".join([f"- {r}" for r in risk_lines[:6]])
    return ctx.base_risks
