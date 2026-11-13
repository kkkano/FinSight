# -*- coding: utf-8 -*-
"""
Full graph invocation test script.
Triggers all 6 agents and inspects the report output + trace for issues.
"""
import asyncio
import json
import os
import sys
import time

# Ensure project root is on sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))


async def main():
    print("=" * 70)
    print("[TEST] Full Graph Invocation - All 6 Agents")
    print("=" * 70)

    # --- 1. Verify env vars ---
    print("\n[1/7] Checking environment variables...")
    env_checks = {
        "LANGGRAPH_PLANNER_MODE": os.getenv("LANGGRAPH_PLANNER_MODE"),
        "LANGGRAPH_SYNTHESIZE_MODE": os.getenv("LANGGRAPH_SYNTHESIZE_MODE"),
        "LANGGRAPH_EXECUTE_LIVE_TOOLS": os.getenv("LANGGRAPH_EXECUTE_LIVE_TOOLS"),
        "LANGGRAPH_REPORT_MAX_AGENTS": os.getenv("LANGGRAPH_REPORT_MAX_AGENTS"),
        "LANGGRAPH_REPORT_MIN_AGENTS": os.getenv("LANGGRAPH_REPORT_MIN_AGENTS"),
        "LANGGRAPH_ESCALATION_MIN_CONFIDENCE": os.getenv("LANGGRAPH_ESCALATION_MIN_CONFIDENCE"),
        "LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS": os.getenv("LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS"),
        "TAVILY_API_KEY": ("SET" if os.getenv("TAVILY_API_KEY") else "MISSING"),
        "EXA_API_KEY": ("SET" if os.getenv("EXA_API_KEY") else "MISSING"),
        "FMP_API_KEY": ("SET" if os.getenv("FMP_API_KEY") else "MISSING"),
        "FRED_API_KEY": ("SET" if os.getenv("FRED_API_KEY") else "MISSING"),
        "ALPHA_VANTAGE_API_KEY": ("SET" if os.getenv("ALPHA_VANTAGE_API_KEY") else "MISSING"),
        "FINNHUB_API_KEY": ("SET" if os.getenv("FINNHUB_API_KEY") else "MISSING"),
    }
    for k, v in env_checks.items():
        status = "OK" if v and v not in ("None", "") else "WARN"
        print(f"  {status}: {k} = {v}")

    # --- 2. Check LLM endpoints ---
    print("\n[2/7] Checking LLM endpoint config...")
    try:
        from backend.llm_config import load_user_endpoints
        endpoints = load_user_endpoints()
        for ep in endpoints:
            print(f"  Endpoint: {ep.name} | model={ep.model} | enabled={ep.enabled} | weight={ep.weight}")
        enabled_count = sum(1 for ep in endpoints if ep.enabled)
        print(f"  => {enabled_count}/{len(endpoints)} endpoints enabled")
    except Exception as e:
        print(f"  ERROR loading endpoints: {e}")

    # --- 3. Create GraphRunner ---
    print("\n[3/7] Creating GraphRunner...")
    from backend.graph.runner import GraphRunner
    runner = GraphRunner.create()
    print("  GraphRunner created (MemorySaver)")

    # --- 4. Invoke ---
    query = "deep analysis of AAPL considering macro interest rate environment and technical analysis"
    # Use a Chinese query that should trigger all agents:
    # price_agent, news_agent, fundamental_agent = company subject
    # technical_agent = keyword hint
    # macro_agent = keyword hint
    # deep_search_agent = keyword hint + escalation
    query = "AAPL"
    print(f"\n[4/7] Invoking graph with query: {query!r}")
    print(f"  output_mode=investment_report")
    print(f"  ui_context={{active_symbol: AAPL}}")

    t0 = time.perf_counter()
    try:
        result = await runner.ainvoke(
            thread_id="test-all-agents-001",
            query=query,
            ui_context={"active_symbol": "AAPL"},
            output_mode="investment_report",
        )
    except Exception as e:
        print(f"\n  FATAL: Graph invocation failed: {e}")
        import traceback
        traceback.print_exc()
        return
    elapsed = time.perf_counter() - t0
    print(f"\n  Graph finished in {elapsed:.1f}s")

    # --- 5. Inspect state ---
    print("\n[5/7] Inspecting returned state...")

    # Subject
    subject = result.get("subject") or {}
    print(f"\n  Subject:")
    print(f"    type: {subject.get('subject_type')}")
    print(f"    tickers: {subject.get('tickers')}")

    # Operation
    operation = result.get("operation") or {}
    print(f"\n  Operation:")
    print(f"    name: {operation.get('name')}")
    print(f"    confidence: {operation.get('confidence')}")

    # Output mode
    print(f"\n  Output mode: {result.get('output_mode')}")

    # Clarify
    clarify = result.get("clarify") or {}
    if clarify.get("needed"):
        print(f"\n  CLARIFY NEEDED: {clarify.get('question')}")
        print(f"    reason: {clarify.get('reason')}")
        print("  => Graph stopped at clarify node. Cannot test further.")
        return

    # Policy
    policy = result.get("policy") or {}
    print(f"\n  Policy:")
    print(f"    allowed_agents: {policy.get('allowed_agents')}")
    print(f"    budget_label: {policy.get('budget_label')}")

    # PlanIR
    plan_ir = result.get("plan_ir") or {}
    steps = plan_ir.get("steps") or []
    print(f"\n  PlanIR:")
    print(f"    total steps: {len(steps)}")
    print(f"    rationale: {(plan_ir.get('rationale') or '')[:200]}")

    agent_steps = [s for s in steps if s.get("kind") == "agent"]
    tool_steps = [s for s in steps if s.get("kind") == "tool"]
    llm_steps = [s for s in steps if s.get("kind") == "llm"]
    print(f"    agent steps: {len(agent_steps)}")
    print(f"    tool steps: {len(tool_steps)}")
    print(f"    llm steps: {len(llm_steps)}")

    # Parallel groups
    groups = {}
    for s in steps:
        pg = s.get("parallel_group") or "SERIAL"
        groups.setdefault(pg, []).append(s.get("id"))
    print(f"\n  Parallel groups:")
    for pg, ids in groups.items():
        print(f"    {pg}: {ids}")

    # Agent details
    print(f"\n  Agent steps detail:")
    for s in agent_steps:
        print(f"    {s.get('id')}: {s.get('name')} | parallel_group={s.get('parallel_group')} | optional={s.get('optional')}")

    # --- 6. Inspect artifacts ---
    print("\n[6/7] Inspecting artifacts...")
    artifacts = result.get("artifacts") or {}
    step_results = artifacts.get("step_results") or {}
    errors = artifacts.get("errors") or []
    evidence_pool = artifacts.get("evidence_pool") or []
    render_vars = artifacts.get("render_vars") or {}
    draft_markdown = artifacts.get("draft_markdown") or ""

    print(f"\n  step_results count: {len(step_results)}")
    print(f"  errors count: {len(errors)}")
    print(f"  evidence_pool count: {len(evidence_pool)}")
    print(f"  render_vars keys: {list(render_vars.keys()) if render_vars else '(empty)'}")
    print(f"  draft_markdown length: {len(draft_markdown)} chars")

    # Per-step results
    print(f"\n  Per-step results:")
    for sid, sr in step_results.items():
        if not isinstance(sr, dict):
            continue
        cached = sr.get("cached")
        duration = sr.get("duration_ms")
        status_reason = sr.get("status_reason", "?")
        output = sr.get("output")
        parallel_group = sr.get("parallel_group", "?")

        # Find step name
        step_name = "?"
        for s in steps:
            if s.get("id") == sid:
                step_name = f"{s.get('kind')}:{s.get('name')}"
                break

        skipped = isinstance(output, dict) and output.get("skipped")
        confidence = None
        summary_preview = ""
        if isinstance(output, dict) and not skipped:
            confidence = output.get("confidence")
            summary_text = output.get("summary") or ""
            if isinstance(summary_text, str):
                summary_preview = summary_text[:100].replace("\n", " ")

        line = f"    {sid} ({step_name}): {status_reason} | {duration}ms | pg={parallel_group}"
        if cached:
            line += " | CACHED"
        if skipped:
            line += f" | SKIPPED({output.get('reason')})"
        if confidence is not None:
            line += f" | conf={confidence}"
        print(line)
        if summary_preview:
            print(f"      summary: {summary_preview}...")

    # Errors
    if errors:
        print(f"\n  ERRORS:")
        for err in errors:
            print(f"    {err.get('step_id')}: {err.get('kind')}:{err.get('name')} => {err.get('error')}")
            print(f"      optional={err.get('optional')} | retryable={err.get('retryable')}")

    # Evidence pool
    print(f"\n  Evidence pool ({len(evidence_pool)} items):")
    for i, ev in enumerate(evidence_pool[:10]):
        if isinstance(ev, dict):
            title = (ev.get("title") or ev.get("source") or "?")[:60]
            url = (ev.get("url") or "")[:80]
            conf = ev.get("confidence", "?")
            print(f"    [{i+1}] {title} | conf={conf}")
            if url:
                print(f"         url: {url}")
    if len(evidence_pool) > 10:
        print(f"    ... and {len(evidence_pool) - 10} more")

    # --- 7. Build report and inspect ---
    print("\n[7/7] Building report payload...")
    try:
        from backend.graph.report_builder import build_report_payload
        report = build_report_payload(
            state=result,
            query=query,
            thread_id="test-all-agents-001",
        )
        if report is None:
            print("  report_payload returned None!")
        else:
            print(f"  report_id: {report.get('report_id')}")
            print(f"  title: {report.get('title')}")
            print(f"  ticker: {report.get('ticker')}")
            print(f"  confidence_score: {report.get('confidence_score')}")
            print(f"  summary: {(report.get('summary') or '')[:200]}")
            print(f"  sections count: {len(report.get('sections') or [])}")
            print(f"  citations count: {len(report.get('citations') or [])}")
            print(f"  risks count: {len(report.get('risks') or [])}")
            print(f"  synthesis_report length: {len(report.get('synthesis_report') or '')} chars")

            # Agent status
            agent_status = report.get("agent_status") or {}
            print(f"\n  Agent status:")
            for name, status in agent_status.items():
                if isinstance(status, dict):
                    s = status.get("status", "?")
                    c = status.get("confidence", "?")
                    extra = ""
                    if status.get("skipped_reason"):
                        extra = f" | skipped: {status.get('skipped_reason')}"
                    if status.get("error"):
                        extra = f" | error: {status.get('error')[:80]}"
                    print(f"    {name}: {s} (conf={c}){extra}")

            # Sections detail
            print(f"\n  Sections:")
            for sec in (report.get("sections") or []):
                title = sec.get("title", "?")
                agent = sec.get("agent_name", "?")
                conf = sec.get("confidence", "?")
                contents = sec.get("contents") or []
                content_len = sum(len(c.get("content", "")) for c in contents if isinstance(c, dict))
                print(f"    [{sec.get('order')}] {title} (agent={agent}, conf={conf}, content={content_len} chars)")

            # Save full report to file for manual inspection
            report_file = os.path.join(ROOT, "scripts", "test_graph_report_output.json")
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n  Full report saved to: {report_file}")

    except Exception as e:
        print(f"  ERROR building report: {e}")
        import traceback
        traceback.print_exc()

    # --- Trace ---
    trace = result.get("trace") or {}
    print(f"\n  Trace:")
    print(f"    events count: {len(trace.get('events') or [])}")
    print(f"    failures count: {len(trace.get('failures') or [])}")
    print(f"    timings: {json.dumps(trace.get('timings') or {}, default=str)[:300]}")

    if trace.get("failures"):
        print(f"\n  Trace failures:")
        for f in trace.get("failures") or []:
            print(f"    {f}")

    # Save full state for debugging
    state_file = os.path.join(ROOT, "scripts", "test_graph_state_output.json")
    try:
        # Filter out non-serializable items
        save_state = {}
        for k, v in result.items():
            if k == "messages":
                save_state[k] = [str(m)[:200] for m in (v or [])]
            else:
                save_state[k] = v
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(save_state, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  Full state saved to: {state_file}")
    except Exception as e:
        print(f"\n  Could not save state: {e}")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("[SUMMARY]")
    print(f"  Total time: {elapsed:.1f}s")
    print(f"  Agents selected: {len(agent_steps)}")
    print(f"  Agents succeeded: {sum(1 for v in (report.get('agent_status') or {}).values() if isinstance(v, dict) and v.get('status') == 'success')}")
    print(f"  Agents failed: {sum(1 for v in (report.get('agent_status') or {}).values() if isinstance(v, dict) and v.get('status') == 'error')}")
    print(f"  Agents skipped: {sum(1 for v in (report.get('agent_status') or {}).values() if isinstance(v, dict) and v.get('status') == 'not_run')}")
    print(f"  Evidence items: {len(evidence_pool)}")
    print(f"  Citations: {len(report.get('citations') or [])}")
    print(f"  Errors: {len(errors)}")
    print(f"  Confidence: {report.get('confidence_score')}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
