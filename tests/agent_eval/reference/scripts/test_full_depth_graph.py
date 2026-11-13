# -*- coding: utf-8 -*-
"""
Ultimate depth test: trigger ALL 6 agents with comprehensive tracking.

Query designed to activate every keyword trigger:
  - "深度分析" → deep_search_agent (required + force_run)
  - "宏观利率" → macro_agent (required)
  - "技术面RSI" → technical_agent (required)
  - "基本面估值" → fundamental_agent (keyword boost)
  - "新闻事件" → news_agent (keyword boost)
  - "AAPL" → company subject → price_agent (required)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── Colour helpers for console ──────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _bar(pct: float, width: int = 30) -> str:
    filled = int(pct * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct:.0%}"


def _agent_icon(status: str) -> str:
    if status == "success":
        return f"{GREEN}✓{RESET}"
    if status == "error":
        return f"{RED}✗{RESET}"
    if status in ("not_run", "skipped"):
        return f"{YELLOW}○{RESET}"
    return "?"


# ── Main test ───────────────────────────────────────────────────────
QUERY = "深度分析 AAPL 苹果公司，综合考虑宏观利率环境对科技股估值的影响，结合技术面RSI和MACD指标，全面评估基本面估值水平，并纳入最新新闻事件催化剂"

EXPECTED_AGENTS = [
    "fundamental_agent",
    "price_agent",
    "news_agent",
    "technical_agent",
    "macro_agent",
    "deep_search_agent",
]


async def main() -> None:
    print(f"\n{'=' * 78}")
    print(f"{BOLD}{CYAN}  [ULTIMATE DEPTH TEST] Full 6-Agent Graph Invocation{RESET}")
    print(f"{'=' * 78}")
    print(f"\n{BOLD}Query:{RESET} {QUERY}")
    print(f"{BOLD}Expected agents:{RESET} {len(EXPECTED_AGENTS)}")
    print(f"{BOLD}Timestamp:{RESET} {_ts()}\n")

    # ── Phase 1: Environment & config check ─────────────────────────
    print(f"{BOLD}[Phase 1] Environment Check{RESET}")
    env_checks = {
        "LANGGRAPH_PLANNER_MODE": ("llm", True),
        "LANGGRAPH_SYNTHESIZE_MODE": ("llm", True),
        "LANGGRAPH_EXECUTE_LIVE_TOOLS": ("true", True),
        "LANGGRAPH_REPORT_MAX_AGENTS": ("6", True),
        "LANGGRAPH_REPORT_MIN_AGENTS": ("2", False),
        "LANGGRAPH_ESCALATION_MIN_CONFIDENCE": ("0.85", False),
        "LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS": ("4", False),
    }
    for key, (expected, required) in env_checks.items():
        val = os.environ.get(key, "")
        ok = val.lower() == expected.lower() if expected else bool(val)
        icon = f"{GREEN}✓{RESET}" if ok else (f"{RED}✗{RESET}" if required else f"{YELLOW}!{RESET}")
        print(f"  {icon} {key} = {val or '(unset)'}")

    api_keys = ["TAVILY_API_KEY", "EXA_API_KEY", "FMP_API_KEY", "FRED_API_KEY",
                "ALPHA_VANTAGE_API_KEY", "FINNHUB_API_KEY"]
    for key in api_keys:
        val = os.environ.get(key, "")
        print(f"  {'✓' if val else '✗'} {key} = {'SET' if val else 'MISSING'}")

    # ── Phase 2: Capability scoring preview ─────────────────────────
    print(f"\n{BOLD}[Phase 2] Agent Capability Scoring Preview{RESET}")
    from backend.graph.capability_registry import (
        REPORT_AGENT_CANDIDATES,
        required_agents_for_request,
        select_agents_for_request,
    )

    mock_state = {
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "operation": {"name": "qa"},
        "output_mode": "investment_report",
        "query": QUERY,
    }
    selection = select_agents_for_request(
        mock_state,
        REPORT_AGENT_CANDIDATES,
        max_agents=6,
        min_agents=2,
    )
    required = required_agents_for_request(mock_state, REPORT_AGENT_CANDIDATES)

    print(f"  Required agents: {required}")
    print(f"  Selected agents: {selection['selected']}")
    for name in EXPECTED_AGENTS:
        score = selection["scores"].get(name, 0)
        reasons = selection["reasons"].get(name, [])
        is_req = "REQUIRED" if name in required else "optional"
        is_sel = "SELECTED" if name in selection["selected"] else "NOT SELECTED"
        print(f"    {name:25s} score={score:.2f} [{is_req:8s}] [{is_sel}]")
        print(f"      reasons: {', '.join(reasons)}")

    missing = set(EXPECTED_AGENTS) - set(selection["selected"])
    if missing:
        print(f"\n  {RED}WARNING: These agents NOT selected: {missing}{RESET}")
        print(f"  The test may not trigger all 6 agents.")

    # ── Phase 3: Graph invocation ───────────────────────────────────
    print(f"\n{BOLD}[Phase 3] Graph Invocation{RESET}")
    print(f"  {_ts()} Creating GraphRunner...")

    from backend.graph.runner import GraphRunner

    runner = GraphRunner.create()
    print(f"  {_ts()} GraphRunner ready (MemorySaver)")

    t0 = time.perf_counter()
    print(f"  {_ts()} Invoking graph...")
    print(f"    query = {QUERY[:80]}...")
    print(f"    output_mode = investment_report")
    print(f"    active_symbol = AAPL")

    result = await runner.ainvoke(
        thread_id="test-full-depth-001",
        query=QUERY,
        ui_context={"active_symbol": "AAPL"},
        output_mode="investment_report",
    )
    elapsed = time.perf_counter() - t0
    print(f"  {_ts()} {GREEN}Graph finished in {elapsed:.1f}s{RESET}")

    state = result if isinstance(result, dict) else {}

    # ── Phase 4: Pipeline trace analysis ────────────────────────────
    print(f"\n{BOLD}[Phase 4] Pipeline Trace Analysis{RESET}")
    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    spans = trace.get("spans") if isinstance(trace.get("spans"), list) else []

    node_timings: dict[str, float] = {}
    for span in spans:
        if not isinstance(span, dict):
            continue
        node = span.get("node") or ""
        dur = span.get("duration_ms") or 0
        node_timings[node] = dur

    pipeline_nodes = [
        "build_initial_state", "normalize_ui_context", "decide_output_mode",
        "resolve_subject", "clarify", "parse_operation", "policy_gate",
        "planner", "execute_plan", "synthesize", "render",
    ]
    total_pipeline_ms = sum(node_timings.get(n, 0) for n in pipeline_nodes)
    print(f"  {'Node':<25s} {'Duration':>10s}  {'%':>6s}  Bar")
    print(f"  {'─' * 25} {'─' * 10}  {'─' * 6}  {'─' * 32}")
    for node in pipeline_nodes:
        ms = node_timings.get(node, 0)
        pct = ms / total_pipeline_ms if total_pipeline_ms > 0 else 0
        print(f"  {node:<25s} {ms:>8.0f}ms  {pct:>5.1%}  {_bar(pct, 20)}")
    print(f"  {'─' * 25} {'─' * 10}")
    print(f"  {'TOTAL':<25s} {total_pipeline_ms:>8.0f}ms")

    # ── Phase 5: Per-agent deep dive ────────────────────────────────
    print(f"\n{BOLD}[Phase 5] Per-Agent Deep Dive{RESET}")
    artifacts = state.get("artifacts") or {}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    plan_ir = state.get("plan_ir") or {}
    steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []
    step_index = {s.get("id"): s for s in steps if isinstance(s, dict) and s.get("id")}

    agent_results: dict[str, dict] = {}
    for step_id, item in step_results.items():
        if not isinstance(item, dict):
            continue
        step = step_index.get(step_id) or {}
        if step.get("kind") != "agent":
            continue
        agent_name = step.get("name") or ""
        output = item.get("output")
        skipped = isinstance(output, dict) and output.get("skipped")
        skip_reason = output.get("reason") if isinstance(output, dict) else None
        duration_ms = item.get("duration_ms") or 0
        parallel_group = step.get("parallel_group") or item.get("parallel_group") or ""

        agent_data = {
            "step_id": step_id,
            "duration_ms": duration_ms,
            "parallel_group": parallel_group,
            "skipped": skipped,
            "skip_reason": skip_reason,
            "optional": step.get("optional", False),
        }

        if isinstance(output, dict) and not skipped:
            agent_data["confidence"] = output.get("confidence", 0)
            agent_data["summary"] = str(output.get("summary") or "")[:200]
            agent_data["evidence_count"] = len(output.get("evidence") or [])
            agent_data["data_sources"] = output.get("data_sources") or []
            agent_data["fallback_used"] = output.get("fallback_used", False)
            agent_data["risks"] = output.get("risks") or []
            agent_data["status"] = "success"

            # Trace events from agent
            agent_trace = output.get("trace") or []
            agent_data["trace_events"] = len(agent_trace) if isinstance(agent_trace, list) else 0
        else:
            agent_data["status"] = "skipped"

        agent_results[agent_name] = agent_data

    # Display each agent
    for name in EXPECTED_AGENTS:
        data = agent_results.get(name)
        if not data:
            print(f"\n  {_agent_icon('not_run')} {BOLD}{name}{RESET} — NOT IN PLAN")
            continue

        status = data.get("status", "unknown")
        icon = _agent_icon(status)
        dur = data.get("duration_ms", 0)
        conf = data.get("confidence", 0)
        pg = data.get("parallel_group", "")
        opt = "optional" if data.get("optional") else "required"
        sid = data.get("step_id", "?")

        print(f"\n  {icon} {BOLD}{name}{RESET} [{sid}] ({status})")
        print(f"    Duration: {dur}ms | Group: {pg} | {opt}")

        if status == "success":
            print(f"    Confidence: {conf:.0%} | Evidence: {data.get('evidence_count', 0)} items")
            print(f"    Data sources: {data.get('data_sources', [])}")
            if data.get("fallback_used"):
                print(f"    {YELLOW}⚠ Fallback used{RESET}")
            risks = data.get("risks", [])
            if risks:
                print(f"    Risks: {risks}")
            print(f"    Trace events: {data.get('trace_events', 0)}")
            summary = data.get("summary", "")
            print(f"    Summary: {summary[:150]}{'...' if len(summary) > 150 else ''}")
        elif status == "skipped":
            print(f"    {YELLOW}Skip reason: {data.get('skip_reason', 'unknown')}{RESET}")

    # ── Phase 6: Evidence pool & citations ──────────────────────────
    print(f"\n{BOLD}[Phase 6] Evidence Pool & Citations{RESET}")
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts.get("evidence_pool"), list) else []
    print(f"  Evidence pool: {len(evidence_pool)} items")

    # Group by source
    by_source: dict[str, int] = {}
    with_url = 0
    for ev in evidence_pool:
        if not isinstance(ev, dict):
            continue
        src = str(ev.get("source") or ev.get("title") or "unknown")[:30]
        by_source[src] = by_source.get(src, 0) + 1
        if ev.get("url"):
            with_url += 1
    print(f"  With URLs: {with_url}/{len(evidence_pool)}")
    for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {src}: {count}")

    # ── Phase 7: Report quality analysis ────────────────────────────
    print(f"\n{BOLD}[Phase 7] Report Quality Analysis{RESET}")
    from backend.graph.report_builder import build_report_payload

    report = build_report_payload(
        state=state,
        query=QUERY,
        thread_id="test-full-depth-001",
    )
    if not report:
        print(f"  {RED}Report build failed{RESET}")
    else:
        print(f"  Report ID: {report.get('report_id')}")
        print(f"  Confidence: {report.get('confidence_score', 0):.1%}")

        sections = report.get("sections") or []
        citations = report.get("citations") or []
        risks = report.get("risks") or []
        sr = report.get("synthesis_report") or ""
        dm = str((state.get("artifacts") or {}).get("draft_markdown") or "")

        print(f"\n  {BOLD}Content Metrics:{RESET}")
        print(f"    draft_markdown:   {len(dm):>6,} chars")
        print(f"    synthesis_report: {len(sr):>6,} chars")
        print(f"    sections:         {len(sections):>6}")
        print(f"    citations:        {len(citations):>6}")
        print(f"    risks:            {len(risks):>6}")

        # Section details
        print(f"\n  {BOLD}Sections:{RESET}")
        for s in sections:
            agent = s.get("agent_name", "?")
            conf = s.get("confidence", 0)
            contents = s.get("contents") or []
            total_chars = sum(len(str(c.get("content", ""))) for c in contents)
            total_refs = sum(len(c.get("citation_refs", [])) for c in contents)
            title = s.get("title", "?")
            print(f"    [{s.get('order', '?')}] {title} ({agent})")
            print(f"        conf={conf:.0%} | chars={total_chars} | citation_refs={total_refs}")

        # Evidence policy
        ep = {}
        meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
        ep = meta.get("evidence_policy") if isinstance(meta.get("evidence_policy"), dict) else {}
        if ep:
            print(f"\n  {BOLD}Evidence Policy:{RESET}")
            print(f"    coverage:       {ep.get('coverage', 0):.1%} ({ep.get('covered_blocks', 0)}/{ep.get('total_blocks', 0)} blocks)")
            print(f"    unique_sources: {ep.get('unique_sources', 0)}")
            print(f"    meets_coverage: {ep.get('meets_coverage', False)}")
            print(f"    meets_sources:  {ep.get('meets_min_sources', False)}")

        # Report content preview
        print(f"\n  {BOLD}Report Content Preview:{RESET}")
        key_sections = ["投资摘要", "公司与业务", "价格快照", "技术面",
                        "关键催化剂", "财务与估值", "风险", "结论"]
        for section_name in key_sections:
            idx = sr.find(f"## {section_name}")
            if idx == -1:
                continue
            end = sr.find("\n## ", idx + 4)
            if end == -1:
                end = min(idx + 500, len(sr))
            content = sr[idx:end].strip()
            lines = content.splitlines()
            header = lines[0] if lines else section_name
            body = "\n".join(lines[1:]).strip()[:200]
            print(f"\n    {CYAN}{header}{RESET}")
            if body:
                for ln in body.splitlines()[:3]:
                    print(f"      {ln}")
                if len(body.splitlines()) > 3:
                    print(f"      ...")

        # Save report JSON
        out_path = os.path.join(os.path.dirname(__file__), "test_full_depth_report.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  Report saved: {out_path}")

        # Save state JSON
        state_path = os.path.join(os.path.dirname(__file__), "test_full_depth_state.json")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        print(f"  State saved: {state_path}")

    # ── Phase 8: Final scorecard ────────────────────────────────────
    print(f"\n{'=' * 78}")
    print(f"{BOLD}  SCORECARD{RESET}")
    print(f"{'=' * 78}")

    succeeded = [n for n, d in agent_results.items() if d.get("status") == "success"]
    skipped = [n for n, d in agent_results.items() if d.get("status") == "skipped"]
    not_in_plan = [n for n in EXPECTED_AGENTS if n not in agent_results]

    print(f"  Total time:      {elapsed:.1f}s")
    print(f"  Agents planned:  {len(agent_results)}")
    print(f"  Agents success:  {GREEN}{len(succeeded)}{RESET} ({', '.join(succeeded)})")
    if skipped:
        print(f"  Agents skipped:  {YELLOW}{len(skipped)}{RESET} ({', '.join(skipped)})")
    if not_in_plan:
        print(f"  NOT in plan:     {RED}{len(not_in_plan)}{RESET} ({', '.join(not_in_plan)})")

    all_6 = len(succeeded) == 6
    print(f"\n  {'🎉' if all_6 else '⚠'} ALL 6 AGENTS TRIGGERED: {GREEN}YES{RESET}" if all_6
          else f"\n  ⚠  ALL 6 AGENTS TRIGGERED: {RED}NO ({len(succeeded)}/6){RESET}")

    if report:
        print(f"  Confidence:      {report.get('confidence_score', 0):.1%}")
        print(f"  Evidence items:  {len(evidence_pool)}")
        print(f"  Citations:       {len(citations)}")
        print(f"  Risks:           {len(risks)}")
        print(f"  Report length:   {len(sr):,} chars")

    # Failures
    failures = trace.get("failures") if isinstance(trace.get("failures"), list) else []
    if failures:
        print(f"\n  {BOLD}Failures:{RESET}")
        for f_item in failures:
            if isinstance(f_item, dict):
                print(f"    {RED}{f_item.get('node', '?')}/{f_item.get('stage', '?')}: {f_item.get('error', '?')}{RESET}")
                if f_item.get("fallback"):
                    print(f"      fallback → {f_item['fallback']}")

    print(f"\n{'=' * 78}\n")


if __name__ == "__main__":
    asyncio.run(main())
