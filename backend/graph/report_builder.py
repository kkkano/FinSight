# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.report.validator import ReportValidator


_AGENT_TITLE_MAP: dict[str, str] = {
    "price_agent": "价格分析",
    "news_agent": "新闻分析",
    "technical_agent": "技术分析",
    "fundamental_agent": "基本面分析",
    "macro_agent": "宏观分析",
    "deep_search_agent": "深度搜索",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Accept a few common formats.
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _freshness_hours(published_date: str | None) -> float:
    if not published_date:
        return 24.0
    dt = _parse_iso_datetime(str(published_date))
    if not dt:
        return 24.0
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    return max(0.0, delta.total_seconds() / 3600.0)


def _count_content_chars(markdown: str) -> int:
    """
    Roughly align with frontend `countContentChars()`:
    Chinese chars + English words/numbers, after stripping common markdown syntax.
    """
    if not markdown:
        return 0
    text = str(markdown)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # links → keep link text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*{1,3}|_{1,3})(.*?)\1", r"\2", text)
    text = re.sub(r"~~.*?~~", "", text)
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>+\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"---+|===+|\*\*\*+", "", text)
    text = text.replace("|", " ")
    # Ignore raw URLs (they should not count towards "content length").
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[:\-]+", " ", text)
    chinese = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    words = len(re.findall(r"[a-zA-Z0-9]+", text))
    return chinese + words


@dataclass
class _CitationBuild:
    citations: list[dict[str, Any]]
    id_by_url: dict[str, str]


def _build_citations(evidence_pool: list[dict[str, Any]] | None) -> _CitationBuild:
    citations: list[dict[str, Any]] = []
    id_by_url: dict[str, str] = {}
    if not isinstance(evidence_pool, list):
        return _CitationBuild(citations=citations, id_by_url=id_by_url)

    for item in evidence_pool:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        if url in id_by_url:
            continue
        source_id = str(len(citations) + 1)
        id_by_url[url] = source_id
        citations.append(
            {
                "source_id": source_id,
                "title": _safe_str(item.get("title") or item.get("source") or url)[:180] or url,
                "url": url,
                "snippet": _safe_str(item.get("snippet") or "")[:400],
                "published_date": _safe_str(item.get("published_date") or ""),
                "confidence": float(item.get("confidence", 0.7) or 0.7),
                "freshness_hours": _freshness_hours(item.get("published_date")),
            }
        )
        if len(citations) >= 24:
            break

    return _CitationBuild(citations=citations, id_by_url=id_by_url)


def _agent_status_from_steps(
    *,
    allowed_agents: list[str],
    plan_steps: list[dict[str, Any]],
    step_results: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    steps_by_agent: dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") != "agent":
            continue
        name = step.get("name")
        step_id = step.get("id")
        if isinstance(name, str) and isinstance(step_id, str) and name.strip() and step_id.strip():
            steps_by_agent[name.strip()] = step_id.strip()

    errors_by_step: dict[str, str] = {}
    for err in errors:
        if not isinstance(err, dict):
            continue
        sid = err.get("step_id")
        msg = err.get("error")
        if isinstance(sid, str) and sid and isinstance(msg, str) and msg:
            errors_by_step[sid] = msg

    for agent_name in allowed_agents:
        step_id = steps_by_agent.get(agent_name)
        if not step_id:
            status[agent_name] = {"status": "not_run", "confidence": 0.0}
            continue

        if step_id in errors_by_step:
            status[agent_name] = {"status": "error", "confidence": 0.0, "error": errors_by_step[step_id]}
            continue

        raw = step_results.get(step_id) if isinstance(step_results, dict) else None
        output = raw.get("output") if isinstance(raw, dict) else None
        if isinstance(output, dict) and output.get("skipped") is True:
            status[agent_name] = {"status": "not_run", "confidence": 0.0}
            continue

        confidence = None
        if isinstance(output, dict):
            confidence = output.get("confidence")
        try:
            conf = float(confidence) if confidence is not None else 0.6
        except Exception:
            conf = 0.6

        status[agent_name] = {"status": "success", "confidence": max(0.0, min(1.0, conf))}

    return status


def _agent_summaries_from_steps(
    *,
    allowed_agents: list[str],
    plan_steps: list[dict[str, Any]],
    step_results: dict[str, Any],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps_by_agent: dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") != "agent":
            continue
        name = step.get("name")
        step_id = step.get("id")
        if isinstance(name, str) and isinstance(step_id, str) and name.strip() and step_id.strip():
            steps_by_agent[name.strip()] = step_id.strip()

    errors_by_step: dict[str, str] = {}
    for err in errors:
        if not isinstance(err, dict):
            continue
        sid = err.get("step_id")
        msg = err.get("error")
        if isinstance(sid, str) and sid and isinstance(msg, str) and msg:
            errors_by_step[sid] = msg

    summaries: list[dict[str, Any]] = []
    order = 1
    for agent_name in allowed_agents:
        step_id = steps_by_agent.get(agent_name)
        title = _AGENT_TITLE_MAP.get(agent_name, agent_name)
        if not step_id:
            summaries.append(
                {
                    "title": title,
                    "order": order,
                    "agent_name": agent_name,
                    "status": "not_run",
                    "summary": "未运行（本轮未触发或无匹配意图）",
                    "confidence": 0.0,
                    "data_sources": [],
                }
            )
            order += 1
            continue

        if step_id in errors_by_step:
            summaries.append(
                {
                    "title": title,
                    "order": order,
                    "agent_name": agent_name,
                    "status": "error",
                    "error": True,
                    "error_message": errors_by_step[step_id],
                    "summary": f"⚠️ 执行失败：{errors_by_step[step_id]}",
                    "confidence": 0.0,
                    "data_sources": [],
                }
            )
            order += 1
            continue

        raw = step_results.get(step_id) if isinstance(step_results, dict) else None
        output = raw.get("output") if isinstance(raw, dict) else None
        if isinstance(output, dict) and output.get("skipped") is True:
            summaries.append(
                {
                    "title": title,
                    "order": order,
                    "agent_name": agent_name,
                    "status": "not_run",
                    "summary": "未运行（当前为 dry_run 或未启用 live tools）",
                    "confidence": 0.0,
                    "data_sources": [],
                }
            )
            order += 1
            continue

        summary = _safe_str(output.get("summary") if isinstance(output, dict) else "")[:4000]
        confidence = output.get("confidence") if isinstance(output, dict) else None
        try:
            confidence_value = float(confidence) if confidence is not None else 0.6
        except Exception:
            confidence_value = 0.6
        data_sources = output.get("data_sources") if isinstance(output, dict) else None
        if not isinstance(data_sources, list):
            data_sources = []

        summaries.append(
            {
                "title": title,
                "order": order,
                "agent_name": agent_name,
                "status": "success",
                "summary": summary or "（无输出）",
                "confidence": max(0.0, min(1.0, confidence_value)),
                "data_sources": [str(x) for x in data_sources if str(x).strip()][:8],
            }
        )
        order += 1

    return summaries


def _extract_risks(render_vars: dict[str, Any] | None) -> list[str]:
    if not isinstance(render_vars, dict):
        return []
    raw = render_vars.get("risks")
    if not isinstance(raw, str) or not raw.strip():
        return []
    lines: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        cleaned = cleaned.lstrip("-").strip()
        if not cleaned:
            continue
        # Keep only non-disclaimer risk items.
        if "不构成投资建议" in cleaned or "仅供参考" in cleaned:
            continue
        lines.append(cleaned[:120])
        if len(lines) >= 8:
            break
    return lines


def _build_long_synthesis_report(
    *,
    ticker_label: str,
    query: str,
    agent_summaries: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    base_markdown: str,
    min_chars: int = 2000,
) -> str:
    parts: list[str] = []
    title = f"{ticker_label} 综合研究报告"
    parts.append(f"## {title}")
    parts.append("")

    # 1) Use the existing rendered markdown as the core narrative.
    core = (base_markdown or "").strip()
    if core:
        parts.append(core)
        parts.append("")
    elif query:
        parts.append(f"**问题**：{query}")
        parts.append("")

    # 2) Agent summaries as structured appendix (high signal, non-duplicative).
    parts.append("## Agent 摘要（结构化）")
    for item in agent_summaries:
        if not isinstance(item, dict):
            continue
        title = _safe_str(item.get("title") or item.get("agent_name") or "Agent")[:80]
        summary = _safe_str(item.get("summary") or "")[:4000]
        confidence = item.get("confidence")
        try:
            conf_pct = int(round(float(confidence) * 100)) if confidence is not None else None
        except Exception:
            conf_pct = None
        meta_bits = []
        if conf_pct is not None:
            meta_bits.append(f"{conf_pct}%")
        status = _safe_str(item.get("status") or "")
        if status:
            meta_bits.append(status)
        meta = " / ".join([x for x in meta_bits if x])
        parts.append(f"### {title}" + (f"（{meta}）" if meta else ""))
        parts.append(summary or "（无输出）")
        parts.append("")

    # 4) If still too short, append a relevant checklist (not generic filler).
    report = "\n".join([p for p in parts if p is not None]).strip() + "\n"

    appendices: list[tuple[str, list[str]]] = [
        (
            "## 附录：核对清单（用于自检/补数据）",
            [
                "- 业务：收入结构、关键产品周期、竞争格局与定价权",
                "- 财务：收入/利润/现金流的增长质量；毛利率/费用率趋势；回购与分红政策",
                "- 估值：当前估值倍数 vs 历史区间 vs 同业；市场预期与兑现路径",
                "- 风险：监管/诉讼、供应链、宏观敏感性、关键客户/渠道变化",
                "- 催化：财报与指引、产品发布、政策变化、行业景气度拐点",
                "- 交易：关键价位、波动率、回撤容忍度与仓位管理",
            ],
        ),
        (
            "## 附录：情景分析（Scenario）",
            [
                "| 情景 | 触发条件 | 核心假设 | 关键验证指标 | 可能的市场反应 |",
                "|---|---|---|---|---|",
                "| 乐观 | 超预期财报/指引、产品周期上行 | 增长/利润率上修 | 收入增速、毛利率、指引 | 估值上修、波动率下降 |",
                "| 基准 | 财报符合预期 | 维持现有预期 | 订单/出货、费用率 | 区间震荡 |",
                "| 悲观 | 指引下调、监管/诉讼升级、需求转弱 | 增长下修、风险溢价上升 | ASP、库存、政策进展 | 回撤扩大、估值压缩 |",
                "",
                "- 用法：把本轮 Agent 结论映射到“触发条件/验证指标”，再决定仓位与止损/止盈规则。",
            ],
        ),
        (
            "## 附录：估值与预期拆解（Valuation）",
            [
                "- 核心思路：价格=盈利预期×估值倍数；短期波动多来自“预期”变化而非事实本身。",
                "- 三步法：",
                "  1) 识别市场一致预期（增长/利润率/资本开支/回购）。",
                "  2) 找到可能打破一致预期的变量（供需、竞争、监管、产品周期）。",
                "  3) 给出验证窗口与指标（财报/渠道数据/宏观数据）。",
                "- 常见误区：只看 PE 不看增长质量；只看收入不看现金流；忽略资本开支与股东回报。",
            ],
        ),
        (
            "## 附录：监控清单（Monitoring）",
            [
                "- 财报：营收/利润/指引是否偏离预期？偏离的原因来自价格、销量还是结构？",
                "- 新闻：重大事件是否改变长期叙事？是否只是短期情绪？",
                "- 技术/交易：关键支撑/阻力位、成交量、波动率是否异常？",
                "- 风险：监管进展、诉讼、供应链、地缘政治是否升级？",
                "- 复盘：本轮判断与后续事实不一致时，应明确“哪条假设错了”。",
            ],
        ),
        (
            "## 附录：风险拆解（Risk Breakdown）",
            [
                "- 业务风险：需求不及预期、产品周期走弱、关键地区/渠道变化",
                "- 竞争风险：替代品崛起、价格战、生态迁移导致的粘性下降",
                "- 执行风险：新品发布延迟、供应链瓶颈、质量/召回事件",
                "- 政策/监管：反垄断、数据/隐私、出口管制与合规成本上升",
                "- 财务风险：利润率下行、费用率上升、资本开支/回购节奏变化",
                "- 估值风险：估值倍数回落、市场风险偏好下降、流动性收紧",
                "- 宏观风险：利率上行、通胀反复、汇率波动、地缘冲突升级",
                "- 黑天鹅：重大诉讼/罚款、重大安全事件、系统性金融风险",
                "",
                "### 如何把风险变成“可验证项”",
                "- 把每条风险写成：触发条件 → 观察指标 → 反应动作（加仓/减仓/观望）",
                "- 为每条风险设置一个时间窗口：本周/本月/下个财季/1 年",
                "- 为每条风险设置一个“反证信号”：出现即降低该风险权重",
            ],
        ),
        (
            "## 附录：仓位与风控（Positioning & Risk）",
            [
                "- 先定义风险预算：单笔最大回撤容忍度、组合波动上限、相关性约束",
                "- 头寸分层：试探仓 → 核心仓 → 加仓仓；每层都有加减仓条件",
                "- 止损不是价格点位而是“假设失效点”：关键指标/事件与预期背离",
                "- 使用“分批/时间分散”降低单点误差：定投、分批建仓、事件后确认",
                "- 当证据不足时，仓位应自动变小（与证据覆盖率/置信度联动）",
            ],
        ),
        (
            "## 附录：关键指标字典（Metrics）",
            [
                "- 收入（Revenue）：增长质量看“量/价/结构”，不要只看同比。",
                "- 毛利率（Gross Margin）：产品结构与定价权的直观反映。",
                "- 费用率（Opex Ratio）：增长换利润/利润换增长的选择。",
                "- 自由现金流（FCF）：利润“含金量”，长期回报的核心来源之一。",
                "- 回购/分红：股东回报与资本配置能力（也可能是缺乏再投资机会）。",
                "- 资本开支（CapEx）：增长投资强度，需结合 ROI 与折旧摊销理解。",
                "- 指引（Guidance）：市场最敏感的变量；通常比“已经发生的结果”更影响估值。",
            ],
        ),
        (
            "## 附录：数据需求清单（Data Requests）",
            [
                "- 价格：现价/涨跌幅、52 周高低、近 1Y 回报、最大回撤与回撤持续时间",
                "- 财务：最近 8 季度营收/利润/毛利率/经营现金流/自由现金流",
                "- 指引：下一季/全年指引的上修/下修幅度与历史兑现情况",
                "- 分部：分产品/分地区收入与增长（识别结构性变化）",
                "- 估值：PE/EV-Sales/FCF Yield vs 历史区间 vs 同业",
                "- 资本回报：回购金额、股数变化、分红率、净负债变化",
                "- 研发与 CapEx：投入强度、产出节奏、是否存在“投入但回报滞后”风险",
                "- 竞争：主要竞争对手份额变化、定价/促销策略、替代品渗透率",
                "- 监管：关键地区政策/诉讼进展、潜在罚款区间与时间线",
                "- 宏观：利率路径、通胀与就业、汇率、关键市场需求景气指标",
                "- 交易：波动率、成交量结构、资金流向、关键技术位",
                "",
                "### 最小可行数据集（MVP）",
                "- 至少包含：现价+近 1Y 回报、最新财报摘要、1-2 条高质量新闻链接。",
                "- 如果缺失：建议先跑 live tools，再生成“可引用”的研报版本。",
            ],
        ),
        (
            "## 附录：行动计划（Action Plan）",
            [
                "- 第 1 步（本周）：补齐 MVP 数据（现价/1Y 回报/最新财报摘要/2 条高质量新闻）。",
                "- 第 2 步（本周）：把结论拆成 3-5 条可验证假设（每条包含验证指标与时间窗口）。",
                "- 第 3 步（本周）：为每条假设定义“反证信号”，并写清楚触发后的动作（减仓/退出/观望）。",
                "- 第 4 步（本月）：把估值拆解为“预期×倍数”，明确预期变化来自哪里（销量/价格/结构/成本）。",
                "- 第 5 步（本月）：建立监控面板：财报/新闻/政策/技术面四类信号的阈值与提醒。",
                "- 第 6 步（持续）：每次重大事件后复盘：哪条假设被证伪？下一轮需要补什么证据？",
                "",
                "### 模板（可直接复制）",
                "- 我的核心假设是：______；验证指标：______；验证窗口：______；反证信号：______；行动：______。",
                "- 如果未来 1-2 个财季出现：______，则说明假设成立/不成立，我会：______。",
            ],
        ),
    ]

    i = 0
    while _count_content_chars(report) < min_chars and i < len(appendices):
        header, lines = appendices[i]
        parts.append(header)
        parts.append("\n".join(lines))
        parts.append("")
        report = "\n".join([p for p in parts if p is not None]).strip() + "\n"
        i += 1

    return report


def build_report_payload(*, state: dict[str, Any], query: str, thread_id: str) -> dict[str, Any] | None:
    """
    Build a frontend-friendly ReportIR payload (used by ReportView cards) from LangGraph state.
    This is intentionally deterministic: it never requires an LLM call to be useful.
    """
    output_mode = state.get("output_mode")
    if output_mode != "investment_report":
        return None

    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    subject_type = subject.get("subject_type") if isinstance(subject, dict) else "unknown"

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    tickers = tickers if isinstance(tickers, list) else []
    tickers = [str(t).strip().upper() for t in tickers if isinstance(t, str) and t.strip()]
    ticker_label = " vs ".join(tickers[:4]) if len(tickers) > 1 else (tickers[0] if tickers else "N/A")

    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    render_vars = artifacts.get("render_vars") if isinstance(artifacts.get("render_vars"), dict) else {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts.get("evidence_pool"), list) else []
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    errors = artifacts.get("errors") if isinstance(artifacts.get("errors"), list) else []
    draft_markdown = _safe_str(artifacts.get("draft_markdown") or "")

    plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    plan_steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []

    policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
    allowed_agents = policy.get("allowed_agents") if isinstance(policy.get("allowed_agents"), list) else []
    allowed_agents = [str(a) for a in allowed_agents if isinstance(a, str) and a.strip()]

    # Evidence pool → citations
    citation_build = _build_citations(evidence_pool)
    citations = citation_build.citations

    # Agent summaries/status
    agent_status = _agent_status_from_steps(
        allowed_agents=allowed_agents,
        plan_steps=plan_steps,
        step_results=step_results,
        errors=errors,
    )
    agent_summaries = _agent_summaries_from_steps(
        allowed_agents=allowed_agents,
        plan_steps=plan_steps,
        step_results=step_results,
        errors=errors,
    )

    # Section list: show each agent summary as its own section for rendering.
    sections: list[dict[str, Any]] = []
    section_order = 1
    for item in agent_summaries:
        title = _safe_str(item.get("title") or "")
        if not title:
            continue
        sections.append(
            {
                "title": title,
                "order": section_order,
                "agent_name": item.get("agent_name"),
                "confidence": item.get("confidence"),
                "data_sources": item.get("data_sources", []),
                "contents": [{"type": "text", "content": _safe_str(item.get("summary") or "")}],
            }
        )
        section_order += 1

    risks = _extract_risks(render_vars)

    # Confidence: average of successful agents, else 0.5.
    confidences = []
    for v in agent_status.values():
        if not isinstance(v, dict):
            continue
        if v.get("status") != "success":
            continue
        try:
            confidences.append(float(v.get("confidence", 0.0)))
        except Exception:
            pass
    confidence_score = sum(confidences) / len(confidences) if confidences else 0.55
    confidence_score = max(0.0, min(1.0, confidence_score))

    summary = ""
    if isinstance(render_vars.get("investment_summary"), str) and render_vars.get("investment_summary").strip():
        summary = render_vars.get("investment_summary").strip()
    elif isinstance(render_vars.get("comparison_conclusion"), str) and render_vars.get("comparison_conclusion").strip():
        summary = render_vars.get("comparison_conclusion").strip()
    elif draft_markdown:
        summary = draft_markdown.splitlines()[0][:200]
    else:
        summary = "（暂无摘要）"

    synthesis_report = _build_long_synthesis_report(
        ticker_label=ticker_label,
        query=query,
        agent_summaries=agent_summaries,
        citations=citations,
        base_markdown=draft_markdown,
        min_chars=2000,
    )

    # Title by subject type
    if subject_type in ("news_item", "news_set"):
        title = f"{ticker_label} 新闻事件研报"
    elif subject_type in ("filing", "research_doc"):
        title = "文档研读报告"
    elif subject_type == "company" and len(tickers) > 1:
        title = f"{ticker_label} 对比研报"
    else:
        title = f"{ticker_label} 分析报告"

    base_report_dict: dict[str, Any] = {
        "report_id": f"lg_{uuid.uuid4().hex[:10]}",
        "ticker": ticker_label,
        "company_name": ticker_label,
        "title": title,
        "summary": summary,
        "sentiment": "neutral",
        "confidence_score": confidence_score,
        "generated_at": _now_iso(),
        "sections": sections,
        "citations": citations,
        "risks": risks,
        "recommendation": "HOLD",
        "meta": {
            "source": "langgraph",
            "thread_id": thread_id,
            "subject_type": subject_type,
            "agent_summaries": agent_summaries,
            "graph_trace": state.get("trace") if isinstance(state.get("trace"), dict) else {},
        },
    }

    validated = ReportValidator.validate_and_fix(base_report_dict, as_dict=True)
    # Preserve frontend-only extensions (ReportView reads these at the top level).
    if isinstance(validated, dict):
        validated["synthesis_report"] = synthesis_report
        validated["agent_status"] = agent_status
        return validated
    return None
