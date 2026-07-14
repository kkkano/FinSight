# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/synthesize.py 的 _stub_render_vars（WP3 Task4，零行为变更）。
from __future__ import annotations

import json
import os
import re
from typing import Any

from backend.graph.executor import summarize_selection
from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState
from backend.graph.render_vars.model import RenderVars
from backend.graph.intent_contract import is_research_compare_contract
from backend.graph.nodes.compare_gate import (
    has_compare_render_contract,
    should_render_performance_compare,
)
from backend.graph.render_vars.access import _get_agent_output, _get_tool_output
from backend.graph.render_vars.compare import _find_row_for_ticker, _parse_comparison_table, _parse_pct
from backend.graph.render_vars.macro import _fmt_macro_tool
from backend.graph.render_vars.news import _fmt_company_news_summary
from backend.graph.render_vars.price import _fmt_price_snapshot
from backend.graph.render_vars.report_agents import (
    _build_catalysts_from_agents,
    _build_company_overview_from_agents,
    _build_conclusion_from_agents,
    _build_investment_summary_from_agents,
    _build_investment_thesis,
    _build_risks_from_agents,
    _build_valuation_from_agents,
    _collect_conflict_disclosure,
)
from backend.graph.render_vars.technical import _fmt_technical_snapshot
from backend.graph.render_vars.context import RenderVarsCtx


def build_render_vars(state: GraphState) -> dict[str, str]:
    """原 synthesize._stub_render_vars 的外壳（分支树逐字搬运，ctx 承载闭包捕获集）。"""
    ctx = RenderVarsCtx()
    ctx.subject = state.get("subject") or {}
    ctx.subject_type = ctx.subject.get("subject_type") or "unknown"
    ctx.query = (state.get("query") or "").strip()
    ctx.operation = (state.get("operation") or {}).get("name") or "qa"
    ctx.output_mode = state.get("output_mode") or "brief"

    ctx.selection_payload = ctx.subject.get("selection_payload") if isinstance(ctx.subject, dict) else None
    ctx.selection_payload = ctx.selection_payload if isinstance(ctx.selection_payload, list) else []

    ctx.selection_summary = summarize_selection({"selection": ctx.selection_payload, "query": ctx.query})

    ctx.artifacts = state.get("artifacts") or {}
    ctx.step_results = ctx.artifacts.get("step_results") if isinstance(ctx.artifacts, dict) else None
    ctx.plan_ir = state.get("plan_ir") or {}
    ctx.steps = ctx.plan_ir.get("steps") if isinstance(ctx.plan_ir, dict) else None
    ctx.step_index = {s.get("id"): s for s in (ctx.steps or []) if isinstance(s, dict) and s.get("id")}



    # --- Cross-agent conflict collection & arbitration ---
    # Comparable-claim matrix: pairs of agents whose outputs can logically conflict.
    # Each tuple: (agent_a, agent_b, comparable_topic)
    ctx._COMPARABLE_PAIRS = [
        ("technical_agent", "fundamental_agent", "方向判断"),
        ("technical_agent", "news_agent", "价格动量 vs 事件冲击"),
        ("technical_agent", "price_agent", "技术信号 vs 实际走势"),
        ("fundamental_agent", "news_agent", "基本面 vs 事件影响"),
        ("fundamental_agent", "macro_agent", "个股基本面 vs 宏观环境"),
        ("news_agent", "macro_agent", "事件情绪 vs 宏观周期"),
        ("price_agent", "news_agent", "价格走势 vs 新闻情绪"),
        ("macro_agent", "technical_agent", "宏观趋势 vs 技术信号"),
    ]









    # Keep stub output useful and non-placeholder.
    ctx.base_risks = "- 注：以上仅供参考，不构成投资建议。"

    if ctx.subject_type in ("news_item", "news_set"):
        return RenderVars(
            news_summary=ctx.selection_summary,
            impact_analysis="\n".join(
                [
                    "- 结论：基于所选新闻做定性分析（非投资建议）。",
                    "- 影响路径：事件 → 市场预期/情绪 → 业绩预期 → 估值/价格。",
                    f"- 当前操作：`{ctx.operation}`；如需更深入，请点击“生成研报”。",
                ]
            ),
            next_watch="\n".join(
                [
                    "- 关注点：后续公告/财报指引、监管进展、竞争对手动态。",
                    "- 验证：价格反应是否与叙事一致（量价、成交量、波动）。",
                ]
            ),
            risks=ctx.base_risks,
        ).model_dump()

    if ctx.subject_type == "macro":
        macro_out = _get_agent_output(ctx, "macro_agent")


        macro_lines: list[str] = []
        if isinstance(macro_out, dict) and macro_out.get("summary"):
            macro_lines.append(f"- MacroAgent: {str(macro_out['summary']).strip()[:900]}")
        macro_lines.extend(_fmt_macro_tool(ctx, "get_official_macro_releases", "官方宏观发布"))
        macro_lines.extend(_fmt_macro_tool(ctx, "get_authoritative_media_news", "权威媒体交叉验证"))
        macro_lines.extend(_fmt_macro_tool(ctx, "search", "开放搜索"))
        macro_context = "\n".join(macro_lines[:6]) or "- 暂未获取到外部证据，以下为基于问题本身的结构化分析框架。"

        risks = [
            "- 利率路径本身具有强不确定性，需持续跟踪 FOMC 表述、通胀和就业数据。",
            "- 大型科技股估值对贴现率敏感，但盈利韧性、AI 资本开支和现金流质量会造成分化。",
            "- 以上仅供研究参考，不构成投资建议。",
        ]
        return RenderVars(
            conclusion="\n".join(
                [
                    f"- 问题：{ctx.query}",
                    "- 核心判断：无 ticker 的宏观/主题问题应走宏观研究路径，而不是要求用户先选公司。",
                    "- 分析框架：利率预期 → 折现率/风险偏好 → 久期资产估值 → 盈利预期与行业分化。",
                ]
            ),
            investment_summary=macro_context,
            investment_thesis="\n".join(
                [
                    "- 若市场预期降息提前，长久期成长股估值通常受益；若利率维持高位或再上修，估值倍数承压。",
                    "- 对大型科技股不能只看利率，还要同步看盈利增速、AI 投资回报周期、监管和美元流动性。",
                ]
            ),
            company_overview=macro_context,
            catalysts="\n".join(
                [
                    "- FOMC 点阵图、主席发布会措辞和核心 PCE/CPI 是主要触发器。",
                    "- 10Y 美债收益率、实际利率和信用利差决定估值压力是否扩散。",
                ]
            ),
            valuation="\n".join(
                [
                    "- 估值传导主要通过贴现率、股权风险溢价和远期盈利折现。",
                    "- 利率下行利好高久期资产，但若来自衰退压力，盈利预期下修会抵消估值扩张。",
                ]
            ),
            price_snapshot="- 宏观/主题研究不绑定单一 ticker；建议结合 NASDAQ 100、10Y 美债收益率和大型科技股篮子观察。",
            technical_snapshot="- 宏观/主题研究不生成单股技术面；可后续指定 QQQ、AAPL、MSFT、GOOGL 等标的再做图表/技术分析。",
            risks="\n".join(risks),
            conflict_disclosure=_collect_conflict_disclosure(ctx),
        ).model_dump()

    if ctx.subject_type == "company":
        ctx.report_hint = "（研报模式）" if ctx.output_mode == "investment_report" else "（快评模式）"
        price_snapshot = _fmt_price_snapshot(ctx)
        technical_snapshot = _fmt_technical_snapshot(ctx)

        ctx.tickers = ctx.subject.get("tickers") if isinstance(ctx.subject, dict) else None
        ctx.tickers = ctx.tickers if isinstance(ctx.tickers, list) else []

        # --- Agent data extraction helpers (stub-mode enrichment) ---





        if ctx.operation == "fetch":
            trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
            executor_type = (trace.get("executor") or {}).get("type") if isinstance(trace, dict) else None

            ctx.news_summary = _fmt_company_news_summary(ctx)
            news_missing = any(x in ctx.news_summary for x in ("暂无", "未获取到"))
            impact_lines = [
                "- 如需我解读某条新闻对股价/基本面的影响：回复对应标题即可。",
                "- 若你想要“重大新闻”筛选：请指定维度（财报/监管/诉讼/并购/交付等）与时间范围。",
            ]
            if executor_type == "dry_run" and news_missing:
                impact_lines.append("- 注：当前未开启实时工具，无法拉取最新新闻；如需请开启 live tools。")

            return RenderVars(
                news_summary=ctx.news_summary,
                conclusion="\n".join(
                    [
                        "- 你想先看哪一条？我可以把事件→影响路径→需要验证的数据点讲清楚。",
                        "- 注：当前未开启实时工具，无法拉取最新新闻；如需请开启 live tools。" if executor_type == "dry_run" and news_missing else "",
                    ]
                ),
                impact_analysis="\n".join(impact_lines),
                next_watch="\n".join(
                    [
                        "- 关注：后续公告/财报指引、交付数据、监管与诉讼进展。",
                        "- 验证：价格反应/成交量/波动是否与叙事一致。",
                    ]
                ),
                risks=ctx.base_risks,
            ).model_dump()



        intent_contract = state.get("intent_contract") if isinstance(state.get("intent_contract"), dict) else {}
        if is_research_compare_contract(intent_contract) or (
            has_compare_render_contract(state) and not should_render_performance_compare(state)
        ):
            render_intent = intent_contract.get("render_intent") if isinstance(intent_contract.get("render_intent"), dict) else {}
            if not render_intent:
                frame = state.get("request_frame") if isinstance(state.get("request_frame"), dict) else {}
                render_intent = frame.get("render_contract") if isinstance(frame.get("render_contract"), dict) else {}
                if not render_intent:
                    frames = state.get("request_frames")
                    if isinstance(frames, list):
                        for item in frames:
                            if not isinstance(item, dict):
                                continue
                            candidate = item.get("render_contract")
                            if isinstance(candidate, dict) and candidate.get("shape") == "compare":
                                render_intent = candidate
                                break
            dimensions = [
                str(item)
                for item in (render_intent.get("dimensions") if isinstance(render_intent, dict) else [])
                if str(item).strip()
            ]
            tickers_list = [str(t).strip().upper() for t in ctx.tickers if isinstance(t, str) and str(t).strip()]
            dimension_labels = {
                "valuation": "估值",
                "valuation_reasonableness": "估值合理性",
                "fundamental": "基本面",
                "earnings": "盈利",
                "technical": "技术面",
                "risk": "风险",
                "news": "新闻",
                "macro": "宏观",
            }
            focus = "、".join(dimension_labels.get(item, "相关证据") for item in (dimensions or ["research"]))
            return RenderVars(
                comparison_conclusion="\n".join(
                    [
                        f"- {', '.join(tickers_list) or '所选标的'}的横向比较重点观察{focus}。",
                        "- 本次比较以各标的研究证据为基础，不使用无关的历史表现替代。",
                    ]
                ),
                comparison_metrics="\n".join(
                    [
                        f"- 证据维度：{focus}。",
                        "- 某个标的缺少数据时会明确披露，不会把缺口伪装成完整比较。",
                    ]
                ),
                risks="- 注：以上仅供参考，不构成投资建议。",
                conclusion="- 对比结论以各标的研究证据为准；若证据存在缺口，则只给出部分比较。",
            ).model_dump()

        if should_render_performance_compare(state):
            metrics = _get_tool_output(ctx, "get_performance_comparison")
            metrics_text = str(metrics).strip() if metrics is not None else ""
            metrics_missing = metrics is None or not metrics_text
            if metrics_missing:
                metrics_text = ""
            if isinstance(metrics, str) and (
                metrics_text.lower().startswith("get_performance_comparison failed")
                or metrics_text.lower().startswith("get_performance_comparison failed:")
            ):
                metrics_missing = True
                metrics_text = ""

            tickers_list = [str(t).strip().upper() for t in ctx.tickers if isinstance(t, str) and str(t).strip()]
            ctx.parsed = _parse_comparison_table(ctx, metrics_text)

            # Some planner variants may pass a mapping like {"Apple": "AAPL", "Microsoft": "MSFT"}.
            # The tool output then uses the *label* column (Apple/Microsoft) instead of the ticker.
            # Build a reverse lookup so we can match rows robustly.
            ctx.label_by_ticker = {}
            if isinstance(ctx.steps, list):
                for s in ctx.steps:
                    if not isinstance(s, dict):
                        continue
                    if s.get("kind") != "tool" or s.get("name") != "get_performance_comparison":
                        continue
                    inputs = s.get("inputs") if isinstance(s.get("inputs"), dict) else {}
                    mapping = inputs.get("tickers") if isinstance(inputs, dict) else None
                    if isinstance(mapping, dict):
                        for label, ticker in mapping.items():
                            if not isinstance(ticker, str):
                                continue
                            ticker_u = ticker.strip().upper()
                            if not ticker_u:
                                continue
                            label_str = label.strip() if isinstance(label, str) and label.strip() else ticker_u
                            ctx.label_by_ticker[ticker_u] = label_str
                    break


            conclusion_lines: list[str] = []
            metric_lines: list[str] = []
            better_ytd: str | None = None
            better_1y: str | None = None
            if ctx.parsed and tickers_list:
                # Prefer displaying the exact tickers from state, in order.
                pairs = []
                for t in tickers_list[:2]:
                    row = _find_row_for_ticker(ctx, t)
                    pairs.append((t, row))

                if len(pairs) == 2:
                    t1, r1 = pairs[0]
                    t2, r2 = pairs[1]
                    ytd1, ytd2 = _parse_pct(ctx, r1.get("ytd", "")), _parse_pct(ctx, r2.get("ytd", ""))
                    one1, one2 = _parse_pct(ctx, r1.get("1y", "")), _parse_pct(ctx, r2.get("1y", ""))
                    if ytd1 is not None and ytd2 is not None:
                        better_ytd = t1 if ytd1 > ytd2 else t2 if ytd2 > ytd1 else "平"
                        metric_lines.append(f"- YTD：{t1} {r1.get('ytd')} vs {t2} {r2.get('ytd')}")
                    if one1 is not None and one2 is not None:
                        better_1y = t1 if one1 > one2 else t2 if one2 > one1 else "平"
                        metric_lines.append(f"- 1Y：{t1} {r1.get('1y')} vs {t2} {r2.get('1y')}")

            # Add an explicit (non-advice) takeaway to answer "which is better" in this dimension.
            if metric_lines and (better_ytd is not None or better_1y is not None):
                non_tie: list[tuple[str, str]] = []
                if better_ytd and better_ytd != "平":
                    non_tie.append(("YTD", better_ytd))
                if better_1y and better_1y != "平":
                    non_tie.append(("1Y", better_1y))

                if len(non_tie) == 2 and non_tie[0][1] == non_tie[1][1]:
                    conclusion_lines.append(f"- 结论（历史回报维度）：{non_tie[0][1]} 相对更强。")
                elif non_tie:
                    conclusion_lines.append(
                        "- 结论（历史回报维度）："
                        + "；".join([f"{metric} 更强={ticker}" for metric, ticker in non_tie])
                        + "。"
                    )
                else:
                    if better_ytd == "平" and better_1y == "平":
                        conclusion_lines.append("- 结论（历史回报维度）：两者表现接近。")
            else:
                if metrics_missing:
                    conclusion_lines.append("- 结论（历史回报维度）：暂无可用的绩效对比数据。")
                else:
                    conclusion_lines.append("- 结论（历史回报维度）：已执行对比工具，但 YTD/1Y 数据不可用或不足。")

            if metric_lines and isinstance(metrics_text, str) and "fallback" in metrics_text.lower():
                metric_lines.append("- 数据源：used fallback price history（可能不是实时行情）。")

            if not metric_lines:
                metric_lines = ["- （暂无绩效对比数据）" if metrics_missing else "- （绩效对比数据不可用或格式异常）"]

            # Add a brief context line (no hard numbers) to help users answer "worth investing".
            if len(tickers_list) >= 2:
                conclusion_lines.append(
                    f"- 对比视角：{' vs '.join(tickers_list)} 各自的商业模式、竞争壁垒和增长驱动力需结合具体业务分析。"
                )
            conclusion_lines.append("- 更值得投资取决于：时间周期、风险偏好与估值/基本面假设。")

            return RenderVars(
                comparison_conclusion="\n".join(
                    [
                        f"- 对比对象：{' vs '.join(tickers_list) or 'N/A'}",
                        *conclusion_lines,
                    ]
                ),
                comparison_metrics="\n".join(metric_lines),
                risks=ctx.base_risks,
            ).model_dump()

        if len(ctx.tickers) >= 2 and ctx.operation == "qa":
            tickers_list = [str(t).strip().upper() for t in ctx.tickers if isinstance(t, str) and str(t).strip()]
            return RenderVars(
                comparison_conclusion="\n".join(
                    [
                        f"- 我先按 {' / '.join(tickers_list[:6])} 这组代表标的理解。",
                        "- 这轮没有足够的实时证据支撑进一步判断，先不硬给排序或投资结论。",
                    ]
                ),
                risks=ctx.base_risks,
            ).model_dump()

        # --- Build conclusion from agent insights ---

        # --- Build risks from agent outputs ---

        return RenderVars(
            conclusion=_build_conclusion_from_agents(ctx),
            price_snapshot=price_snapshot,
            technical_snapshot=technical_snapshot,
            investment_summary=_build_investment_summary_from_agents(ctx),
            investment_thesis=_build_investment_thesis(ctx),
            company_overview=_build_company_overview_from_agents(ctx),
            catalysts=_build_catalysts_from_agents(ctx),
            valuation=_build_valuation_from_agents(ctx),
            risks=_build_risks_from_agents(ctx),
            conflict_disclosure=_collect_conflict_disclosure(ctx),
        ).model_dump()

    if ctx.subject_type in ("filing", "research_doc"):
        return RenderVars(
            summary=ctx.selection_summary,
            highlights="\n".join(
                [
                    "- 建议抽取：营收/利润/毛利率、指引、分部表现、一次性项目。",
                    "- 若为公告：关注口径变化、重大事项、潜在法律/监管风险。",
                ]
            ),
            analysis="\n".join(
                [
                    f"- 当前操作：`{ctx.operation}`；基于文档内容给出结构化解读与影响路径。",
                    "- 如需更深入章节，请点击“生成研报”。",
                ]
            ),
            risks=ctx.base_risks,
        ).model_dump()

    # unknown
    return RenderVars(
        conclusion="\n".join(
            [
                "- (internal) unexpected state: `unknown` subject reached Synthesize.",
                "- Clarify node should have intercepted this request before planning/execution.",
            ]
        ),
        risks=ctx.base_risks,
    ).model_dump()


__all__ = ["build_render_vars"]
