# -*- coding: utf-8 -*-
"""Long-form narrative synthesis implementation."""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage

from backend.graph.failure import append_failure, utc_now_iso
from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState
from backend.graph.synthesis.normalization import (
    _format_conversation_history_for_synth,
    _format_memory_context_for_synth,
    _scrub_unverified_future_claims,
)
from backend.report.verifier import (
    _apply_verifier_redactions,
    _compute_unresolved_unsupported_claims,
)

logger = logging.getLogger(__name__)


def _skill_perspective_block(state: GraphState) -> str:
    """视角型 skill：把「解读视角」拼成 prompt 段落。

    skill 系统原本只控数据/agent，不控解读视角。此处从 policy.skill_selection
    读取 perspective，注入合成 prompt。无 skill / 无视角时返回空（向后兼容）。
    """
    skill_sel = (state.get("policy") or {}).get("skill_selection")
    skill_sel = skill_sel if isinstance(skill_sel, dict) else {}
    perspective = str(skill_sel.get("perspective") or "").strip()
    if not perspective:
        return ""
    display = str(skill_sel.get("display_name") or skill_sel.get("selected_skill") or "").strip()
    label = f"「{display}」" if display else ""
    return (
        "<analysis_perspective>\n"
        f"本次分析采用{label}视角，请在以下各章节解读中始终贯彻该视角的方法与侧重：\n"
        f"{perspective}\n"
        "</analysis_perspective>\n\n"
    )


async def generate_narrative_draft(
    state: GraphState,
    render_vars: dict[str, str],
    trace: dict[str, Any],
    *,
    emit_event_fn,
    ainvoke_fn,
    verifier_fn,
    is_rate_limit_error_fn,
) -> tuple[str, dict[str, Any] | None]:
    """
    Call LLM to produce a complete markdown research report (narrative mode).

    Returns:
    - markdown string on success (or empty string on failure)
    - optional verifier result payload
    """
    from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm

    _synth_temp = float(os.getenv("LANGGRAPH_SYNTHESIZE_TEMPERATURE", "0.3"))
    call_context = LLMCallContext.create(
        stage="report_synthesize", agent="report_synthesizer", layer="synthesis", max_provider_attempts=3,
    )

    artifacts = state.get("artifacts") or {}
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts, dict) else None
    query = (state.get("query") or "").strip()
    subject = state.get("subject") or {}
    tickers = subject.get("tickers") if isinstance(subject, dict) else []
    tickers = tickers if isinstance(tickers, list) else []
    ticker_label = ", ".join(str(t) for t in tickers) if tickers else "标的"

    # -- Collect agent summaries and evidence for the prompt context --
    agent_sections: list[str] = []
    if isinstance(step_results, dict):
        plan_ir = state.get("plan_ir") or {}
        steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else None
        step_index = {s.get("id"): s for s in (steps or []) if isinstance(s, dict) and s.get("id")}

        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if isinstance(output, dict) and output.get("skipped"):
                continue
            step_meta = step_index.get(step_id) or {}
            agent_name = step_meta.get("name") or step_id
            kind = step_meta.get("kind") or "unknown"

            section_lines = [f"### {agent_name} ({kind})"]
            if isinstance(output, dict):
                summary = output.get("summary")
                if summary:
                    section_lines.append(f"摘要: {str(summary).strip()[:2000]}")
                evidence = output.get("evidence")
                if isinstance(evidence, list):
                    for ev in evidence[:15]:
                        if isinstance(ev, dict):
                            ev_text = str(ev.get("text") or "").strip()
                            if ev_text:
                                section_lines.append(f"- {ev_text[:400]}")
                        elif isinstance(ev, str) and ev.strip():
                            section_lines.append(f"- {ev.strip()[:400]}")
                risks = output.get("risks")
                if isinstance(risks, list):
                    for r in risks[:6]:
                        section_lines.append(f"- [风险] {str(r).strip()[:300]}")
            elif output is not None:
                section_lines.append(str(output).strip()[:1500])

            agent_sections.append("\n".join(section_lines))

    # -- Collect cross-agent conflict information for narrative context --
    # Apply same trigger formula: deep_report || (success >= 2 && comparable >= 1)
    _NARRATIVE_COMPARABLE_PAIRS = [
        ("technical_agent", "fundamental_agent"),
        ("technical_agent", "news_agent"),
        ("technical_agent", "price_agent"),
        ("fundamental_agent", "news_agent"),
        ("fundamental_agent", "macro_agent"),
        ("news_agent", "macro_agent"),
        ("price_agent", "news_agent"),
        ("macro_agent", "technical_agent"),
    ]
    narrative_success_agents: set[str] = set()
    if isinstance(step_results, dict):
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if not isinstance(output, dict) or output.get("skipped"):
                continue
            a_name = (step_index.get(step_id) or {}).get("name") or ""
            if a_name and isinstance(output.get("summary"), str) and output["summary"].strip():
                narrative_success_agents.add(a_name)

    narrative_comparable_count = sum(
        1 for a, b in _NARRATIVE_COMPARABLE_PAIRS
        if a in narrative_success_agents and b in narrative_success_agents
    )
    output_mode_raw = state.get("output_mode") or ""
    is_narrative_deep = output_mode_raw == "investment_report"
    should_collect_conflicts = is_narrative_deep or (
        len(narrative_success_agents) >= 2 and narrative_comparable_count >= 1
    )

    conflict_context_lines: list[str] = []
    if should_collect_conflicts and isinstance(step_results, dict):
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if not isinstance(output, dict):
                continue
            a_name = (step_index.get(step_id) or {}).get("name") or step_id
            flags = output.get("conflict_flags")
            claims = output.get("conflicting_claims")
            if isinstance(flags, list):
                for f in flags:
                    if isinstance(f, str) and f.strip():
                        conflict_context_lines.append(f"- [{a_name}] {f.strip()}")
            if isinstance(claims, list):
                for c in claims:
                    if isinstance(c, dict):
                        claim_text = c.get("claim", "")
                        src_a = c.get("source_a", "?")
                        val_a = c.get("value_a", "?")
                        src_b = c.get("source_b", "?")
                        val_b = c.get("value_b", "?")
                        resolved = c.get("resolved", False)
                        resolution = c.get("resolution", "")
                        status = f"已裁决: {resolution}" if resolved else "未裁决"
                        conflict_context_lines.append(
                            f"- [{a_name}] {claim_text}: {src_a}={val_a} vs {src_b}={val_b} ({status})"
                        )
        # Edge case: deep report with ≤1 agent → add degraded notice to prompt
        if is_narrative_deep and len(narrative_success_agents) <= 1:
            conflict_context_lines.insert(
                0, f"- [系统] 冲突检测降级：仅 {len(narrative_success_agents)} 个智能体成功，无法交叉验证"
            )
    conflict_context = "\n".join(conflict_context_lines) if conflict_context_lines else ""

    evidence_text = ""
    if isinstance(evidence_pool, list) and evidence_pool:
        ev_lines: list[str] = []
        for ev in evidence_pool[:20]:
            if isinstance(ev, dict):
                text = str(ev.get("text") or "").strip()
                source = str(ev.get("source") or "").strip()
                if text:
                    ev_lines.append(f"- [{source}] {text[:400]}" if source else f"- {text[:400]}")
            elif isinstance(ev, str) and ev.strip():
                ev_lines.append(f"- {ev.strip()[:400]}")
        if ev_lines:
            evidence_text = "\n".join(ev_lines)

    conversation_history = _format_conversation_history_for_synth(state)
    memory_context_block = _format_memory_context_for_synth(state)
    current_date = utc_now_iso()[:10]
    narrative_grounding_text = "\n".join(
        part for part in [evidence_text, conflict_context, "\n".join(agent_sections)] if part
    )
    perspective_block = _skill_perspective_block(state)

    prompt = f"""<role>FinSight 叙事报告引擎 — 资深卖方分析师视角，将多智能体分析结果合成为专业级投资研究报告</role>

<task>
基于以下多个分析智能体的输出，撰写一份完整、深度的中文 Markdown 投资研究报告。
查询: {query}
标的: {ticker_label}
</task>

{perspective_block}<time_anchor>
当前日期: {current_date}
你的知识可能过时。涉及日期/发布/并购/监管等事件时，仅可使用本提示中明确提供的证据内容。
</time_anchor>

{conversation_history}{memory_context_block}<agent_outputs>
{chr(10).join(agent_sections) if agent_sections else "(无智能体输出)"}
</agent_outputs>

{"<evidence_pool>" + chr(10) + evidence_text + chr(10) + "</evidence_pool>" if evidence_text else ""}

{"<cross_agent_conflicts>" + chr(10) + conflict_context + chr(10) + "</cross_agent_conflicts>" if conflict_context else ""}

<report_structure>
严格按以下结构撰写，使用 Markdown 标题。每个章节必须包含实质性分析段落，禁止仅列出数据点：

## 投资论点
2-3 段话。第一段给出核心判断（偏多/偏空/中性），附置信度和关键驱动因素。第二段阐述投资逻辑链条：事件 → 基本面影响 → 估值变化 → 价格预期。如有分歧信号，需明确说明矛盾点和权衡逻辑。

## 基本面分析
3-4 段话。必须涵盖：
- 盈利能力：营收规模、增速（YoY/QoQ）、利润率趋势
- 财务健康：杠杆率、现金流状况、资本配置
- 增长质量：增长驱动来源（量价/新业务/并购）、可持续性评估
- 与同业或历史水平的对比。每个论点引用具体数字。

## 技术面分析
2-3 段话。必须涵盖：
- 趋势判断：均线系统（MA20/MA50/MA200）排列与价格位置
- 动量指标：RSI 区间判断、MACD 信号方向
- 关键价位：支撑位与阻力位，以及触及后的操作含义
- 技术面与基本面信号的一致性/背离分析

## 催化剂与风险
分别列出催化剂和风险，各 2-4 条。

**催化剂**：每条必须包含：
1. 事件描述（具体事件/日期/来源）
2. 影响路径（事件 → 预期/情绪 → 业绩预期 → 估值/价格）
3. 概率和影响程度评估
此外，每个催化剂必须标注事件状态：【已确认】（有官方公告/明确日期）、【预期】（市场普遍预期但未官宣）、【传言】（未经证实的消息）。
格式：- 【已确认】2026-06-15 财报发布：预期 EPS $1.2 vs 共识 $1.15
禁止列出无法标注状态的模糊催化剂。

**风险**：每条风险必须包含可追踪的触发条件（指标+阈值），禁止"宏观环境波动""市场情绪变化"这类无法验证的空话。
格式：- 毛利率风险：若下季度毛利率跌破 40%（当前 42.3%），估值逻辑需重估
若证据中缺少具体阈值数据，标注"[阈值待补：缺少基线数据]"，但仍需指明应追踪的指标。

## 结论
2 段话。第一段综合研判，给出明确的操作建议框架（观望/逢低关注/逢高减仓等，附前提条件）。第二段必须以"观察点清单"结尾：3-5 个具体观察点，每个包含指标名称、观察窗口、触发阈值、触发后的含义。
格式（Markdown 表格）：
| 观察点 | 窗口 | 阈值 | 触发含义 |
| --- | --- | --- | --- |
| 数据中心收入增速 | Q3 财报 | <50% YoY | 增长叙事弱化 |
禁止"建议持续关注""密切跟踪"这类无行动指引的模糊表述。
</report_structure>

<constraints>
1) 总长度 4000-6000 字符。这是严格要求，不可少于 4000 字符。
2) 每句话必须有数据支撑或逻辑推导，禁止空洞套话和模板化表述。
3) 跨智能体交叉引用：技术面与基本面信号对比、新闻事件与价格走势关联、宏观环境对个股的传导路径。
4) **冲突处理（关键）**：如 <cross_agent_conflicts> 中存在未裁决冲突，必须在相关章节中：(a) 明确说明冲突点和双方数据来源；(b) 给出裁决依据（优先采信哪方、为什么）；(c) 标注剩余不确定性。已裁决冲突也需简要提及裁决结论。
5) 有证据来源时标注引用编号 [1][2]。
6) 数据不足时明确标注"[数据缺失]"，不编造数字。
7) 直接输出 Markdown，禁止 JSON 包装、代码块包裹或开场白。
8) 末尾附一行免责声明："*以上内容仅供参考，不构成投资建议。*"
9) 禁止出现"补充分析"、"核心发现"等附录性标题，所有内容必须融入上述五大章节中。
10) **可选可视化**：当可视化确实有助于读者理解时，可在正文中插入图表标签（每篇报告最多 4 个，按章节需要自适应；不滥用）：
    - **真实数据优先且不可降级为模型数组**：价格、行情、成交量、技术指标和财务时间序列一律输出 `<chart_ref>`，例如 `<chart_ref type="price_volume" source="market_chart" fields="ohlcv" title="量价走势"/>`；source 仅限 peers / financials / valuation / market_chart / technicals / news / earnings。拿不到真实字段时省略图表并在正文标注数据缺失，禁止改用 `<chart>` 编造序列。
    - `<chart>` 仅允许表达没有真实数据源的概念关系、流程或情景示意，示例：`<chart type="pie" title="情景权重示意">{{"labels":["基准","乐观"],"values":[60,40]}}</chart>`。每个 inline 图表标签后必须紧跟一句：`（示意图，非真实数据）`；不得把价格、行情、财务数字或任何看似真实的时间序列放进 `<chart>`。
    - Chart catalog: bar / line / pie / scatter / gauge / candlestick / price_volume / rs_line / waterfall / heatmap / radar / valuation_band / bubble / drawdown / scenario。
    - 图种选择规则：价格/趋势/技术面优先 candlestick / price_volume / rs_line / drawdown；同行对比优先 bubble / heatmap / bar；财务结构优先 waterfall / 多序列 line / bar；估值优先 valuation_band / bar；风险/情景优先 scenario / drawdown；综合评分优先 radar / gauge。
    - 图表只辅助文字分析，不替代结论、证据解释和风险说明。
11) **严格闭卷原则（高优先级）**：你唯一可用的信息来源仅限本提示中的 <agent_outputs>、<evidence_pool>、<cross_agent_conflicts>。
12) 禁止引用任何未在上述标签中出现的具体事实（尤其是产品发布时间、并购、监管进展、公司战略计划、竞争对手具体动态）。
13) 如需提及行业背景，仅允许使用泛化表述（如"行业竞争加剧"），禁止输出具体日期+事件断言。
14) 违反闭卷原则视为编造数据，与编造财务数字同级错误。
</constraints>"""

    retry_attempts = 0

    def _on_retry(attempt: int, _exc: BaseException) -> None:
        nonlocal retry_attempts
        retry_attempts = max(retry_attempts, int(attempt))

    try:
        await emit_event_fn(
            {
                "type": "thinking",
                "stage": "llm_call_start",
                "message": "synthesize_narrative",
                "timestamp": utc_now_iso(),
            }
        )
        resp = await ainvoke_configured_llm(
            [HumanMessage(content=prompt)],
            context=call_context,
            temperature=_synth_temp,
            acquire_token=True,
        )
        await emit_event_fn(
            {
                "type": "thinking",
                "stage": "llm_call_done",
                "message": "synthesize_narrative",
                "timestamp": utc_now_iso(),
            }
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        draft = str(content).strip()

        # Strip accidental code-fence wrapping
        draft = re.sub(r"^```(?:markdown|md)?\s*", "", draft, flags=re.IGNORECASE)
        draft = re.sub(r"\s*```$", "", draft)
        draft = draft.strip()
        draft = _scrub_unverified_future_claims(draft, narrative_grounding_text)

        verifier_result = await verifier_fn(
            state=state,
            generated_text=draft,
            grounding_text=narrative_grounding_text,
        )
        unsupported_claims = (
            verifier_result.get("unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        if isinstance(unsupported_claims, list) and unsupported_claims:
            draft = _apply_verifier_redactions(draft, unsupported_claims)
        unresolved_claims = (
            _compute_unresolved_unsupported_claims(draft, unsupported_claims)
            if isinstance(unsupported_claims, list)
            else []
        )
        if isinstance(verifier_result, dict):
            verifier_result["unresolved_unsupported_claims"] = unresolved_claims

        if len(draft) < 500:
            logger.warning("[Synthesize/narrative] LLM output too short (%d chars), discarding", len(draft))
            return "", verifier_result

        logger.info("[Synthesize/narrative] Generated %d-char narrative draft (retries=%d)", len(draft), retry_attempts)
        return draft, verifier_result

    except Exception as exc:
        retryable = is_rate_limit_error_fn(exc)
        logger.warning(
            "[Synthesize/narrative] LLM call FAILED (retryable=%s, attempts=%d): %s — will use template fallback",
            retryable, retry_attempts, exc,
        )
        append_failure(
            trace,
            node="synthesize",
            stage="narrative_llm_call",
            error=str(exc),
            fallback="template_draft",
            retryable=retryable,
            retry_attempts=retry_attempts,
        )
        await emit_event_fn(
            {
                "type": "thinking",
                "stage": "llm_call_error",
                "message": "synthesize_narrative failed; fallback to template",
                "timestamp": utc_now_iso(),
            }
        )
        return "", None
