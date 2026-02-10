# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict

from backend.graph.executor import summarize_selection
from backend.graph.event_bus import emit_event
from backend.graph.failure import append_failure, build_runtime, utc_now_iso
from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState
from backend.services.llm_retry import ainvoke_with_rate_limit_retry, is_rate_limit_error

logger = logging.getLogger(__name__)


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else default


def _extract_json_object(text: str) -> str:
    if not text:
        raise ValueError("empty model output")

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no json object found")
    return cleaned[start : end + 1]


_DISALLOWED_SNIPPET_MARKERS = (
    "Search Results",
    "Performance Comparison",
    "get_",
    " output",
    "Notes:",
    "====",
    "```",
    "<inputs>",
    "</inputs>",
    "<output_format>",
    "</output_format>",
)
_DISCLAIMER_PHRASES = ("不构成投资建议", "仅供参考", "历史不代表未来", "非投资建议")


def _sanitize_llm_section(text: str, *, max_lines: int = 8, max_chars: int = 900) -> str:
    if not isinstance(text, str):
        return ""
    cleaned_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(marker in line for marker in _DISALLOWED_SNIPPET_MARKERS):
            continue
        if any(phrase in line for phrase in _DISCLAIMER_PHRASES):
            continue
        cleaned_lines.append(line)
        if len(cleaned_lines) >= max_lines:
            break
    if not cleaned_lines:
        return ""
    normalized = "\n".join([l if l.startswith("-") else f"- {l}" for l in cleaned_lines]).strip()
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars].rstrip()
    return normalized


def _coerce_payload_to_strings(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort coercion so RenderVars validation doesn't fail when the LLM returns
    lists/dicts for string fields (e.g. risks: ["...", "..."]).
    """
    if not isinstance(payload, dict):
        return {}

    coerced: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            coerced[key] = ""
            continue

        if isinstance(value, str):
            coerced[key] = value
            continue

        if isinstance(value, list):
            lines: list[str] = []
            for item in value[:20]:
                if item is None:
                    continue
                if isinstance(item, str):
                    line = item.strip()
                else:
                    try:
                        line = json_dumps_safe(item, ensure_ascii=False)
                    except Exception:
                        line = str(item)
                if line:
                    lines.append(line)
            coerced[key] = "\n".join(lines)
            continue

        if isinstance(value, dict):
            try:
                coerced[key] = json_dumps_safe(value, ensure_ascii=False)
            except Exception:
                coerced[key] = str(value)
            continue

        coerced[key] = str(value)

    return coerced


def _format_risks(candidate: Any, *, base_risks: str) -> str:
    base = base_risks.strip() if isinstance(base_risks, str) and base_risks.strip() else "- 注：以上仅供参考，不构成投资建议。"

    if candidate is None:
        return base

    raw_text = candidate.strip() if isinstance(candidate, str) else str(candidate).strip()

    parsed: dict[str, Any] | None = None
    if isinstance(candidate, dict):
        parsed = candidate
    elif isinstance(candidate, str) and raw_text.startswith("{") and raw_text.endswith("}"):
        try:
            obj = json.loads(raw_text)
            if isinstance(obj, dict):
                parsed = obj
        except Exception:
            parsed = None

    if isinstance(parsed, dict):
        lines: list[str] = []
        for k, v in parsed.items():
            if v is None:
                continue
            key = str(k).strip()
            if not key:
                continue
            key_lower = key.lower()
            if "disclaimer" in key_lower or "免责声明" in key:
                continue

            if isinstance(v, str):
                value = v.strip()
            else:
                try:
                    value = json_dumps_safe(v, ensure_ascii=False)
                except Exception:
                    value = str(v)
                value = value.strip()

            if not value:
                continue
            if any(phrase in value for phrase in _DISCLAIMER_PHRASES):
                continue

            # Prefer `AAPL: ...` style when keys look like tickers or named buckets.
            if key_lower in ("risk", "risks"):
                lines.append(f"- {value}")
            else:
                lines.append(f"- {key}：{value}")
            if len(lines) >= 6:
                break

        return "\n".join([*lines, base]).strip() if lines else base

    sanitized = _sanitize_llm_section(raw_text, max_lines=6)
    return "\n".join([sanitized, base]).strip() if sanitized else base


class RenderVars(BaseModel):
    """
    Template injection variables (Phase 4/5).

    NOTE: Keep this model permissive (extra=ignore) so we can evolve templates
    without breaking older model outputs.
    """

    model_config = ConfigDict(extra="ignore")

    # common-ish
    risks: str = ""

    # news
    news_summary: str = ""
    impact_analysis: str = ""
    next_watch: str = ""

    # company
    conclusion: str = ""
    investment_summary: str = ""
    company_overview: str = ""
    catalysts: str = ""
    valuation: str = ""
    price_snapshot: str = ""
    technical_snapshot: str = ""
    comparison_conclusion: str = ""
    comparison_metrics: str = ""

    # filing/doc
    summary: str = ""
    highlights: str = ""
    analysis: str = ""


def _stub_render_vars(state: GraphState) -> dict[str, str]:
    subject = state.get("subject") or {}
    subject_type = subject.get("subject_type") or "unknown"
    query = (state.get("query") or "").strip()
    operation = (state.get("operation") or {}).get("name") or "qa"
    output_mode = state.get("output_mode") or "brief"

    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    selection_payload = selection_payload if isinstance(selection_payload, list) else []

    selection_summary = summarize_selection({"selection": selection_payload, "query": query})

    artifacts = state.get("artifacts") or {}
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    plan_ir = state.get("plan_ir") or {}
    steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else None
    step_index = {s.get("id"): s for s in (steps or []) if isinstance(s, dict) and s.get("id")}

    def _get_tool_output(tool_name: str) -> Any:
        if not isinstance(step_results, dict) or not step_results:
            return None
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if isinstance(output, dict) and output.get("skipped"):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") == "tool" and step.get("name") == tool_name:
                return output
        return None

    def _get_agent_output(agent_name: str) -> dict[str, Any] | None:
        """Read a successful agent's output dict from step_results."""
        if not isinstance(step_results, dict) or not step_results:
            return None
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if isinstance(output, dict) and output.get("skipped"):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") == "agent" and step.get("name") == agent_name:
                return output if isinstance(output, dict) else None
        return None

    def _fmt_price_snapshot() -> str:
        out = _get_tool_output("get_stock_price")
        if out is not None:
            if isinstance(out, (dict, list)):
                return f"- {json_dumps_safe(out, ensure_ascii=False)[:800]}"
            text = str(out).strip()
            return f"- {text}" if text else "- （价格数据为空）"
        # Fallback: use price_agent output when tool not scheduled directly
        agent_out = _get_agent_output("price_agent")
        if isinstance(agent_out, dict) and agent_out.get("summary"):
            return f"- {str(agent_out['summary']).strip()[:500]}"
        return "- （暂无价格数据；如需可启用 live tools）"

    def _fmt_technical_snapshot() -> str:
        out = _get_tool_output("get_technical_snapshot")
        if out is None:
            # Fallback: use technical_agent output when tool not scheduled directly
            agent_out = _get_agent_output("technical_agent")
            if isinstance(agent_out, dict) and agent_out.get("summary"):
                return f"- {str(agent_out['summary']).strip()[:600]}"
            return "- （暂无技术指标；如需可启用 live tools）"

        if isinstance(out, str):
            try:
                out = json.loads(out)
            except Exception:
                out = {"raw": out}

        if not isinstance(out, dict):
            return f"- {str(out)[:800]}"

        if out.get("error"):
            return f"- 技术指标不可用：{out.get('error')}（points={out.get('points','N/A')}）"

        close = out.get("close")
        ma20 = out.get("ma20")
        ma50 = out.get("ma50")
        ma200 = out.get("ma200")
        rsi14 = out.get("rsi14")
        rsi_state = out.get("rsi_state")
        macd = out.get("macd")
        signal = out.get("macd_signal")
        momentum = out.get("momentum")
        trend = out.get("trend")
        as_of = out.get("as_of")

        lines = []
        if as_of:
            lines.append(f"- as_of: {as_of}")
        if close is not None:
            lines.append(f"- close: {close}")
        parts = []
        if ma20 is not None:
            parts.append(f"MA20 {ma20:.2f}" if isinstance(ma20, (int, float)) else f"MA20 {ma20}")
        if ma50 is not None:
            parts.append(f"MA50 {ma50:.2f}" if isinstance(ma50, (int, float)) else f"MA50 {ma50}")
        if ma200 is not None:
            parts.append(f"MA200 {ma200:.2f}" if isinstance(ma200, (int, float)) else f"MA200 {ma200}")
        if parts:
            lines.append("- " + " | ".join(parts))
        if rsi14 is not None:
            if isinstance(rsi14, (int, float)):
                lines.append(f"- RSI(14): {rsi14:.2f} ({rsi_state})")
            else:
                lines.append(f"- RSI(14): {rsi14} ({rsi_state})")
        if macd is not None and signal is not None:
            if isinstance(macd, (int, float)) and isinstance(signal, (int, float)):
                lines.append(f"- MACD: {macd:.4f} vs signal {signal:.4f} ({momentum})")
            else:
                lines.append(f"- MACD: {macd} vs signal {signal} ({momentum})")
        if trend:
            lines.append(f"- trend: {trend}")
        return "\n".join(lines) if lines else "- （技术指标为空）"

    def _fmt_company_news_summary() -> str:
        out = _get_tool_output("get_company_news")
        if out is None:
            return "- （暂无新闻数据）"

        if isinstance(out, str):
            try:
                out = json.loads(out)
            except Exception:
                out = {"raw": out}

        if isinstance(out, dict):
            maybe = out.get("items") or out.get("news") or out.get("results")
            if isinstance(maybe, list):
                out = maybe

        items: list[dict[str, Any]] = []
        if isinstance(out, list):
            for item in out[:10]:
                if isinstance(item, dict):
                    items.append(item)

        if not items:
            return "- （未获取到相关新闻）"

        lines: list[str] = []
        for item in items[:6]:
            title = item.get("title") or item.get("headline") or "(untitled)"
            url = item.get("url")
            source = item.get("source")
            ts = item.get("published_date") or item.get("published_at") or item.get("datetime")
            meta = " / ".join([x for x in [source, ts] if isinstance(x, str) and x.strip()])
            if isinstance(url, str) and url.strip():
                lines.append(f"- [{title}]({url})" + (f"（{meta}）" if meta else ""))
            else:
                lines.append(f"- {title}" + (f"（{meta}）" if meta else ""))

        return "\n".join(lines) if lines else "- （未获取到相关新闻）"

    # Keep stub output useful and non-placeholder.
    base_risks = "- 注：以上仅供参考，不构成投资建议。"

    if subject_type in ("news_item", "news_set"):
        return RenderVars(
            news_summary=selection_summary,
            impact_analysis="\n".join(
                [
                    "- 结论：基于所选新闻做定性分析（非投资建议）。",
                    "- 影响路径：事件 → 市场预期/情绪 → 业绩预期 → 估值/价格。",
                    f"- 当前操作：`{operation}`；如需更深入，请点击“生成研报”。",
                ]
            ),
            next_watch="\n".join(
                [
                    "- 关注点：后续公告/财报指引、监管进展、竞争对手动态。",
                    "- 验证：价格反应是否与叙事一致（量价、成交量、波动）。",
                ]
            ),
            risks=base_risks,
        ).model_dump()

    if subject_type == "company":
        report_hint = "（研报模式）" if output_mode == "investment_report" else "（快评模式）"
        price_snapshot = _fmt_price_snapshot()
        technical_snapshot = _fmt_technical_snapshot()

        tickers = subject.get("tickers") if isinstance(subject, dict) else None
        tickers = tickers if isinstance(tickers, list) else []

        # --- Agent data extraction helpers (stub-mode enrichment) ---
        def _build_investment_summary_from_agents() -> str:
            lines: list[str] = []
            price_out = _get_agent_output("price_agent")
            if isinstance(price_out, dict) and price_out.get("summary"):
                lines.append(f"- {str(price_out['summary']).strip()[:300]}")
            fund_out = _get_agent_output("fundamental_agent")
            if isinstance(fund_out, dict) and fund_out.get("summary"):
                lines.append(f"- {str(fund_out['summary']).strip()[:400]}")
            tech_out = _get_agent_output("technical_agent")
            if isinstance(tech_out, dict) and tech_out.get("summary"):
                lines.append(f"- {str(tech_out['summary']).strip()[:300]}")
            if not lines:
                lines = [
                    '- 研报为结构化交付物：会更长、更全面，但不等于\u201c必须跑全家桶\u201d。',
                    '- 如果缺少关键证据（财报/新闻/数据），会明确标注缺口。',
                ]
            return "\n".join(lines)

        def _build_company_overview_from_agents() -> str:
            # Try get_company_info tool output first
            info_out = _get_tool_output("get_company_info")
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
            fund_out = _get_agent_output("fundamental_agent")
            if isinstance(fund_out, dict) and fund_out.get("summary"):
                return f"- {str(fund_out['summary']).strip()[:600]}"
            return "- 公司概况：暂无数据。"

        def _build_catalysts_from_agents() -> str:
            news_out = _get_agent_output("news_agent")
            if isinstance(news_out, dict) and news_out.get("summary"):
                return f"- {str(news_out['summary']).strip()[:600]}"
            return "\n".join([
                "- 可能催化：财报、产品发布、政策变化、行业景气度变化。",
                "- 将基于新闻/财报证据进一步细化。",
            ])

        def _build_valuation_from_agents() -> str:
            fund_out = _get_agent_output("fundamental_agent")
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

        if operation == "fetch":
            trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
            executor_type = (trace.get("executor") or {}).get("type") if isinstance(trace, dict) else None

            news_summary = _fmt_company_news_summary()
            news_missing = any(x in news_summary for x in ("暂无", "未获取到"))
            impact_lines = [
                "- 如需我解读某条新闻对股价/基本面的影响：回复对应标题即可。",
                "- 若你想要“重大新闻”筛选：请指定维度（财报/监管/诉讼/并购/交付等）与时间范围。",
            ]
            if executor_type == "dry_run" and news_missing:
                impact_lines.append("- 注：当前未开启实时工具，无法拉取最新新闻；如需请开启 live tools。")

            return RenderVars(
                news_summary=news_summary,
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
                risks=base_risks,
            ).model_dump()

        def _parse_comparison_table(text: str) -> dict[str, dict[str, str]]:
            if not text or "Performance Comparison" not in text:
                return {}
            rows: dict[str, dict[str, str]] = {}
            for line in str(text).splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(("Ticker", "-", "Performance", "Notes")):
                    continue
                parts = stripped.split()
                if len(parts) < 4:
                    continue
                label = " ".join(parts[:-3]).strip()
                if not label:
                    continue
                current = parts[-3]
                ytd = parts[-2]
                one_year = parts[-1]
                rows[label] = {"current": current, "ytd": ytd, "1y": one_year}
            return rows

        def _parse_pct(value: str) -> float | None:
            if not isinstance(value, str):
                return None
            cleaned = value.strip()
            if not cleaned or cleaned.upper() == "N/A":
                return None
            cleaned = cleaned.replace("%", "")
            try:
                return float(cleaned)
            except Exception:
                return None

        if operation == "compare" or len(tickers) > 1:
            metrics = _get_tool_output("get_performance_comparison")
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

            tickers_list = [str(t).strip().upper() for t in tickers if isinstance(t, str) and str(t).strip()]
            parsed = _parse_comparison_table(metrics_text)

            # Some planner variants may pass a mapping like {"Apple": "AAPL", "Microsoft": "MSFT"}.
            # The tool output then uses the *label* column (Apple/Microsoft) instead of the ticker.
            # Build a reverse lookup so we can match rows robustly.
            label_by_ticker: dict[str, str] = {}
            if isinstance(steps, list):
                for s in steps:
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
                            label_by_ticker[ticker_u] = label_str
                    break

            def _find_row_for_ticker(ticker: str) -> dict[str, str]:
                if not ticker or not parsed:
                    return {}
                ticker_u = ticker.strip().upper()

                for key, row in parsed.items():
                    if isinstance(key, str) and key.strip().upper() == ticker_u:
                        return row

                label = label_by_ticker.get(ticker_u)
                if isinstance(label, str) and label.strip():
                    label_u = label.strip().upper()
                    for key, row in parsed.items():
                        if isinstance(key, str) and key.strip().upper() == label_u:
                            return row

                return {}

            conclusion_lines: list[str] = []
            metric_lines: list[str] = []
            better_ytd: str | None = None
            better_1y: str | None = None
            if parsed and tickers_list:
                # Prefer displaying the exact tickers from state, in order.
                pairs = []
                for t in tickers_list[:2]:
                    row = _find_row_for_ticker(t)
                    pairs.append((t, row))

                if len(pairs) == 2:
                    t1, r1 = pairs[0]
                    t2, r2 = pairs[1]
                    ytd1, ytd2 = _parse_pct(r1.get("ytd", "")), _parse_pct(r2.get("ytd", ""))
                    one1, one2 = _parse_pct(r1.get("1y", "")), _parse_pct(r2.get("1y", ""))
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
                risks=base_risks,
            ).model_dump()

        # --- Build conclusion from agent insights ---
        def _build_conclusion_from_agents() -> str:
            lines: list[str] = []
            # Confidence overview
            conf_parts: list[str] = []
            for aname in ("fundamental_agent", "price_agent", "news_agent", "technical_agent"):
                a_out = _get_agent_output(aname)
                if isinstance(a_out, dict) and a_out.get("confidence"):
                    conf_parts.append(f"{aname.replace('_agent','')}: {float(a_out['confidence']):.0%}")
            if conf_parts:
                lines.append(f"- 数据覆盖：{', '.join(conf_parts)}")
            # Technical signal
            tech_out = _get_agent_output("technical_agent")
            if isinstance(tech_out, dict) and tech_out.get("summary"):
                ts = str(tech_out["summary"]).strip()
                if "overbought" in ts.lower():
                    lines.append("- 技术面提示：RSI 进入超买区域，短期回撤风险上升。")
                elif "oversold" in ts.lower():
                    lines.append("- 技术面提示：RSI 进入超卖区域，存在反弹可能。")
            # Note
            lines.append("- 以上为多维度数据汇总，不构成投资建议。具体操作请结合个人风险偏好。")
            return "\n".join(lines) if lines else "\n".join([
                f"- {report_hint} 查询：{query or 'N/A'}",
                "- 如果你提供/选择了新闻或财报，可以把结论做得更具体。",
            ])

        # --- Build risks from agent outputs ---
        def _build_risks_from_agents() -> str:
            risk_lines: list[str] = []
            for aname in ("fundamental_agent", "technical_agent", "news_agent", "macro_agent"):
                a_out = _get_agent_output(aname)
                if not isinstance(a_out, dict):
                    continue
                agent_risks = a_out.get("risks")
                if isinstance(agent_risks, list):
                    for r in agent_risks:
                        r_text = str(r).strip()[:150]
                        if r_text and r_text not in risk_lines:
                            risk_lines.append(r_text)
            if risk_lines:
                return "\n".join([f"- {r}" for r in risk_lines[:6]]) + "\n- 注：以上仅供参考，不构成投资建议。"
            return base_risks

        return RenderVars(
            conclusion=_build_conclusion_from_agents(),
            price_snapshot=price_snapshot,
            technical_snapshot=technical_snapshot,
            investment_summary=_build_investment_summary_from_agents(),
            company_overview=_build_company_overview_from_agents(),
            catalysts=_build_catalysts_from_agents(),
            valuation=_build_valuation_from_agents(),
            risks=_build_risks_from_agents(),
        ).model_dump()

    if subject_type in ("filing", "research_doc"):
        return RenderVars(
            summary=selection_summary,
            highlights="\n".join(
                [
                    "- 建议抽取：营收/利润/毛利率、指引、分部表现、一次性项目。",
                    "- 若为公告：关注口径变化、重大事项、潜在法律/监管风险。",
                ]
            ),
            analysis="\n".join(
                [
                    f"- 当前操作：`{operation}`；基于文档内容给出结构化解读与影响路径。",
                    "- 如需更深入章节，请点击“生成研报”。",
                ]
            ),
            risks=base_risks,
        ).model_dump()

    # unknown
    return RenderVars(
        conclusion="\n".join(
            [
                "- (internal) unexpected state: `unknown` subject reached Synthesize.",
                "- Clarify node should have intercepted this request before planning/execution.",
            ]
        ),
        risks=base_risks,
    ).model_dump()


async def synthesize(state: GraphState) -> dict:
    """
    Phase 4.4 Synthesize node.

    Modes:
    - LANGGRAPH_SYNTHESIZE_MODE=stub (default): deterministic render_vars
    - LANGGRAPH_SYNTHESIZE_MODE=llm: LLM fills render_vars JSON; validate; fallback to stub
    """
    mode = _env_str("LANGGRAPH_SYNTHESIZE_MODE", "stub").lower()
    trace = state.get("trace") or {}

    if mode != "llm":
        logger.info("[Synthesize] Running in STUB mode (set LANGGRAPH_SYNTHESIZE_MODE=llm for LLM synthesis)")
        render_vars = _stub_render_vars(state)
        trace.update(
            {
                "synthesize_runtime": {
                    **build_runtime(mode="stub", fallback=False),
                    "keys": sorted(render_vars.keys()),
                }
            }
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    try:
        from backend.llm_config import create_llm

        _synth_temp = float(os.getenv("LANGGRAPH_SYNTHESIZE_TEMPERATURE", "0.2"))
        llm = create_llm(temperature=_synth_temp)
        llm_factory = lambda: create_llm(temperature=_synth_temp)  # noqa: E731
    except Exception as exc:
        render_vars = _stub_render_vars(state)
        append_failure(
            trace,
            node="synthesize",
            stage="llm_init",
            error=str(exc),
            fallback="synthesize_stub",
            retryable=False,
        )
        trace.update(
            {
                "synthesize_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason=f"llm_unavailable: {exc}",
                    retry_attempts=0,
                )
            }
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    subject = state.get("subject") or {}
    operation = state.get("operation") or {}
    output_mode = state.get("output_mode") or "brief"
    artifacts = state.get("artifacts") or {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts, dict) else None
    rag_context = artifacts.get("rag_context") if isinstance(artifacts, dict) else None
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None

    inputs = {
        "query": state.get("query") or "",
        "subject": subject,
        "operation": operation,
        "output_mode": output_mode,
        "evidence_pool": evidence_pool if isinstance(evidence_pool, list) else [],
        "rag_context": rag_context if isinstance(rag_context, list) else [],
        "step_results": step_results if isinstance(step_results, dict) else {},
    }

    prompt = f"""<role>FinSight Synthesis</role>

<task>
Fill template variables for the finance assistant response.
Return JSON ONLY. No markdown, no commentary.
</task>

<inputs>
{json_dumps_safe(inputs, ensure_ascii=False, indent=2)}
</inputs>

<output_format>
Return a single JSON object. Keys should be a subset of:
news_summary, impact_analysis, next_watch, risks,
conclusion, investment_summary, company_overview, catalysts, valuation,
price_snapshot, technical_snapshot,
comparison_conclusion, comparison_metrics,
summary, highlights, analysis.
</output_format>

<constraints>
1) Use rag_context/evidence_pool/step_results when available; if insufficient, state assumptions explicitly.
2) Do NOT include raw tool outputs / search dumps / trace-like logs in any field.
3) Avoid repeating disclaimers; put at most 1 short disclaimer in `risks`.
4) Keep each field concise (<= 6 bullet lines when possible).
5) Do NOT include placeholder phrases like "待实现".
6) Output must be valid JSON object.
</constraints>
"""

    retry_attempts = 0

    def _on_retry(attempt: int, _exc: BaseException) -> None:
        nonlocal retry_attempts
        retry_attempts = max(retry_attempts, int(attempt))

    try:
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_start",
                "message": "synthesize",
                "timestamp": utc_now_iso(),
            }
        )
        resp = await ainvoke_with_rate_limit_retry(
            llm,
            [HumanMessage(content=prompt)],
            llm_factory=llm_factory,
            acquire_token=True,
            on_retry=_on_retry,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_done",
                "message": "synthesize",
                "timestamp": utc_now_iso(),
            }
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        payload = json.loads(_extract_json_object(str(content)))
        if not isinstance(payload, dict):
            raise ValueError("render_vars payload must be a JSON object")

        payload = _coerce_payload_to_strings(payload)
        llm_render_vars = RenderVars.model_validate(payload).model_dump()
        # Merge with deterministic stub defaults so omitted keys never fall back
        # to template placeholders. Some keys are "data sections" that must stay
        # evidence-driven; keep the stub version to avoid hallucinated metrics.
        stub_render_vars = _stub_render_vars(state)
        base_risks = str(stub_render_vars.get("risks") or "- 注：以上仅供参考，不构成投资建议。").strip()
        protected_keys = {"news_summary", "comparison_metrics", "price_snapshot", "technical_snapshot"}
        render_vars: dict[str, str] = {}
        for key, stub_value in stub_render_vars.items():
            if key in protected_keys:
                render_vars[key] = stub_value
                continue
            candidate = llm_render_vars.get(key)
            if key == "risks":
                render_vars[key] = _format_risks(candidate, base_risks=base_risks)
                continue
            if key in (
                "comparison_conclusion",
                "conclusion",
                "impact_analysis",
                "next_watch",
                "investment_summary",
                "company_overview",
                "catalysts",
                "valuation",
                "summary",
                "highlights",
                "analysis",
            ):
                if isinstance(candidate, str) and candidate.strip():
                    sanitized = _sanitize_llm_section(candidate, max_lines=8)
                    render_vars[key] = sanitized if sanitized else stub_value
                else:
                    render_vars[key] = stub_value
                continue

            if isinstance(candidate, str) and candidate.strip():
                render_vars[key] = candidate
            else:
                render_vars[key] = stub_value
        for key, candidate in llm_render_vars.items():
            if key not in render_vars:
                render_vars[key] = candidate
        if any("待实现" in str(v) for v in render_vars.values()):
            raise ValueError("render_vars contains placeholder tokens")

        trace.update(
            {
                "synthesize_runtime": {
                    **build_runtime(mode="llm", fallback=False, retry_attempts=retry_attempts),
                    "keys": sorted(render_vars.keys()),
                }
            }
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}
    except Exception as exc:
        retryable = is_rate_limit_error(exc)
        logger.warning(
            "[Synthesize] LLM call FAILED (retryable=%s, attempts=%d): %s — falling back to stub",
            retryable, retry_attempts, exc,
        )
        append_failure(
            trace,
            node="synthesize",
            stage="llm_call",
            error=str(exc),
            fallback="synthesize_stub",
            retryable=retryable,
            retry_attempts=retry_attempts,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_error",
                "message": "synthesize failed; fallback to stub",
                "timestamp": utc_now_iso(),
            }
        )
        render_vars = _stub_render_vars(state)
        trace.update(
            {
                "synthesize_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason="llm_output_invalid",
                    retry_attempts=retry_attempts,
                )
            }
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}


__all__ = ["synthesize", "RenderVars"]
