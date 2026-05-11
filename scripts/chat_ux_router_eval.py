# -*- coding: utf-8 -*-
"""Run configurable chat router UX eval cases through /chat/supervisor.

The dataset is intentionally data-driven so new weird UX cases can be added
without changing the evaluator.  Hard expectations produce FAIL; softer
expectations produce REVIEW.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ERROR_MARKERS = ("403", "401", "forbidden", "unauthorized", "timeout", "rejected", "tool_error")


def _make_client() -> Any:
    from fastapi.testclient import TestClient
    from backend.api.main import app

    return TestClient(app)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(cases, list):
        raise SystemExit(f"Dataset must be a list or object with cases: {path}")
    return [case for case in cases if isinstance(case, dict)]


def _payload(case: dict[str, Any], run_id: str) -> dict[str, Any]:
    session = str(case.get("session") or case.get("id") or uuid4().hex[:8])
    payload = {
        "query": case.get("query") or "",
        "session_id": f"tenant1:router_eval:{session}-{run_id}",
        "context": case.get("context") or {},
        "options": {"confirmation_mode": "skip"},
    }
    if isinstance(case.get("options"), dict):
        payload["options"].update(case["options"])
    return payload


def _plan_steps(graph: dict[str, Any], trace: dict[str, Any]) -> list[dict[str, Any]]:
    plan_ir = graph.get("plan_ir") if isinstance(graph.get("plan_ir"), dict) else {}
    steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []
    if steps:
        return [step for step in steps if isinstance(step, dict)]
    spans = trace.get("spans") if isinstance(trace.get("spans"), list) else []
    for span in spans:
        if not isinstance(span, dict) or span.get("node") != "planner":
            continue
        data = span.get("data") if isinstance(span.get("data"), dict) else {}
        span_steps = data.get("steps") if isinstance(data.get("steps"), list) else []
        if span_steps:
            return [step for step in span_steps if isinstance(step, dict)]
    return []


def _all_tasks(graph: dict[str, Any], trace: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for source in (graph.get("tasks"), (trace.get("understanding") or {}).get("tasks") if isinstance(trace.get("understanding"), dict) else None):
        if isinstance(source, list):
            tasks.extend(item for item in source if isinstance(item, dict))
    return tasks


def _task_tickers(tasks: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for task in tasks:
        for ticker in task.get("tickers") or []:
            if isinstance(ticker, str) and ticker.strip():
                result.add(ticker.strip().upper())
    return result


def _is_citable_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text.startswith(("http://", "https://")):
        return False
    lowered = text.lower()
    non_article_markers = (
        "google.com/search",
        "finance.yahoo.com/search",
        "finance.yahoo.com/quote/",
        "benzinga.com/search",
        "reuters.com/site-search",
        "cnbc.com/search",
        "marketwatch.com/search",
    )
    return not any(marker in lowered for marker in non_article_markers)


def _response_urls(text: str) -> list[str]:
    return [match.rstrip(").,，。]") for match in re.findall(r"https?://[^\s)]+", text)]


def _evidence_urls(evidence_pool: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("url") or "").strip()
        for item in evidence_pool
        if isinstance(item, dict) and str(item.get("url") or "").strip()
    ]


def _has_link(text: str, evidence_pool: list[dict[str, Any]]) -> bool:
    if any(_is_citable_url(url) for url in _response_urls(text)):
        return True
    return any(_is_citable_url(url) for url in _evidence_urls(evidence_pool))


def _has_non_citable_link(text: str, evidence_pool: list[dict[str, Any]]) -> bool:
    urls = _response_urls(text) + _evidence_urls(evidence_pool)
    return any(url.startswith(("http://", "https://")) and not _is_citable_url(url) for url in urls)


def _verdict(case: dict[str, Any], data: dict[str, Any]) -> tuple[str, list[str]]:
    graph = data.get("graph") if isinstance(data.get("graph"), dict) else {}
    trace = graph.get("trace") if isinstance(graph.get("trace"), dict) else {}
    contract = trace.get("reply_contract") if isinstance(trace.get("reply_contract"), dict) else {}
    artifacts = graph.get("artifacts") if isinstance(graph.get("artifacts"), dict) else {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts.get("evidence_pool"), list) else []
    steps = _plan_steps(graph, trace)
    step_names = {str(step.get("name") or "") for step in steps}
    response_text = str(data.get("response") or "")
    expected = case.get("expect") if isinstance(case.get("expect"), dict) else {}
    issues: list[str] = []
    hard = bool(case.get("hard"))

    expected_lane = expected.get("lane")
    if expected_lane and contract.get("lane") != expected_lane:
        issues.append(f"lane expected {expected_lane}, got {contract.get('lane')}")

    if expected.get("forbid_report") and (graph.get("output_mode") == "investment_report" or contract.get("lane") == "report_generation"):
        issues.append("ordinary chat entered report mode")

    if expected.get("require_report") and contract.get("lane") != "report_generation":
        issues.append("explicit report request did not enter report_generation")

    if expected.get("require_url_fetch") and "fetch_url_content" not in step_names:
        issues.append("URL/article request did not plan fetch_url_content")

    if expected.get("forbid_news_tools"):
        from backend.graph.request_task_contract import NEWS_TOOL_NAMES

        leaked = sorted(step_names.intersection(NEWS_TOOL_NAMES))
        if leaked:
            issues.append(f"news tools planned despite no-news constraint: {leaked}")

    forbidden_tools = {
        str(tool or "").strip()
        for tool in expected.get("forbid_tools") or []
        if str(tool or "").strip()
    }
    if forbidden_tools:
        leaked_tools = sorted(step_names.intersection(forbidden_tools))
        if leaked_tools:
            issues.append(f"forbidden tool(s) planned: {leaked_tools}")

    if expected.get("require_links") and not _has_link(response_text, evidence_pool):
        issues.append("link-required answer had no URL in response or evidence")

    if expected.get("require_links") and _has_non_citable_link(response_text, evidence_pool):
        issues.append("link-required answer used search/listing URL instead of article/source URL")

    if expected.get("forbid_error_evidence"):
        joined = " ".join(
            str(item.get("title") or "") + " " + str(item.get("snippet") or "")
            for item in evidence_pool
            if isinstance(item, dict)
        ).lower()
        if any(marker in joined for marker in ERROR_MARKERS):
            issues.append("tool error marker was promoted to evidence")

    expected_ticker = str(expected.get("ticker") or "").strip().upper()
    context_binding = contract.get("context_binding") if isinstance(contract.get("context_binding"), dict) else {}
    binding_text = " ".join(
        str(context_binding.get(key) or "") for key in ("subject_hint", "ticker", "symbol", "reason")
    ).upper()
    if (
        expected_ticker
        and expected_ticker not in _task_tickers(_all_tasks(graph, trace))
        and expected_ticker not in response_text.upper()
        and expected_ticker not in binding_text
    ):
        issues.append(f"expected ticker {expected_ticker} not bound in tasks or answer")

    forbidden_tickers = {
        str(ticker or "").strip().upper()
        for ticker in expected.get("forbid_tickers") or []
        if str(ticker or "").strip()
    }
    if forbidden_tickers:
        observed_tickers = _task_tickers(_all_tasks(graph, trace))
        leaked_tickers = sorted(observed_tickers.intersection(forbidden_tickers))
        if leaked_tickers:
            issues.append(f"forbidden ticker(s) bound in tasks: {leaked_tickers}")

    if not issues:
        return "PASS", []
    return ("FAIL" if hard else "REVIEW"), issues


def _run_case(client: Any, case: dict[str, Any], run_id: str) -> dict[str, Any]:
    payload = _payload(case, run_id)
    started = time.perf_counter()
    response = client.post("/chat/supervisor", json=payload)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        data: dict[str, Any] = {"response": response.text[:4000], "status_code": response.status_code}
        verdict, issues = "FAIL", [f"HTTP {response.status_code}"]
    else:
        data = response.json()
        verdict, issues = _verdict(case, data)
    graph = data.get("graph") if isinstance(data.get("graph"), dict) else {}
    trace = graph.get("trace") if isinstance(graph.get("trace"), dict) else {}
    return {
        "case": case,
        "payload": payload,
        "elapsed_ms": elapsed_ms,
        "status_code": response.status_code,
        "reply_contract": trace.get("reply_contract") if isinstance(trace, dict) else None,
        "output_mode": graph.get("output_mode"),
        "route": (trace.get("understanding") or {}).get("route") if isinstance(trace.get("understanding"), dict) else None,
        "plan_steps": [{"kind": step.get("kind"), "name": step.get("name"), "inputs": step.get("inputs")} for step in _plan_steps(graph, trace)],
        "response": data.get("response") or "",
        "verdict": verdict,
        "issues": issues,
    }


def _render(rows: list[dict[str, Any]], *, started_at: str, elapsed_s: float) -> str:
    pass_count = sum(1 for row in rows if row["verdict"] == "PASS")
    review_count = sum(1 for row in rows if row["verdict"] == "REVIEW")
    fail_count = sum(1 for row in rows if row["verdict"] == "FAIL")
    lines = [
        "# Chat UX Router Acceptance Eval",
        "",
        f"- Started at: `{started_at}`",
        f"- Result: `{pass_count}` PASS, `{review_count}` REVIEW, `{fail_count}` FAIL",
        f"- Elapsed: `{elapsed_s:.1f}s`",
        "",
        "| ID | Category | Verdict | Lane | Mode | Route | ms | Issues |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        case = row["case"]
        contract = row.get("reply_contract") if isinstance(row.get("reply_contract"), dict) else {}
        issues = "<br>".join(row["issues"]) if row["issues"] else "-"
        lines.append(
            f"| {case.get('id')} | {case.get('category')} | {row['verdict']} | {contract.get('lane') or '-'} | "
            f"{row.get('output_mode') or '-'} | {row.get('route') or '-'} | {row['elapsed_ms']} | {issues} |"
        )
    lines.extend(["", "## Full Rows", "", "```json", json.dumps(rows, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tests/eval/chat_router_100.json")
    parser.add_argument("--out", default="docs/qa/chat-router-100-eval.md")
    parser.add_argument("--json-out", default="docs/qa/chat-router-100-eval.json")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--ids", default="")
    args = parser.parse_args()

    os.environ["LANGGRAPH_CHECKPOINTER_BACKEND"] = "memory"
    os.environ["LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK"] = "true"
    os.environ["LANGFUSE_ENABLED"] = "false"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["OTEL_TRACES_EXPORTER"] = "none"
    os.environ.setdefault("FINSIGHT_CONTEXT_ROUTER_TIMEOUT_SEC", "90")
    os.environ.setdefault("FINSIGHT_CONTEXT_REPLY_TIMEOUT_SEC", "120")
    os.environ.setdefault("LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC", "150")
    os.environ.setdefault("LANGGRAPH_SYNTHESIZE_REPORT_TIMEOUT_SEC", "800")

    run_id = args.run_id.strip() or datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:6]
    selected = {item.strip().upper() for item in args.ids.split(",") if item.strip()}
    cases = _load_cases(ROOT / args.dataset)
    cases = [case for case in cases if not selected or str(case.get("id") or "").upper() in selected]
    if selected and len(cases) != len(selected):
        missing = sorted(selected - {str(case.get("id") or "").upper() for case in cases})
        raise SystemExit(f"Unknown case ids: {', '.join(missing)}")

    started_at = datetime.now().isoformat(timespec="seconds")
    started = time.perf_counter()
    client = _make_client()
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        print(f"[{index:02d}/{len(cases)}] {case.get('id')} {case.get('category')}: {str(case.get('query'))[:70]}", flush=True)
        row = _run_case(client, case, run_id)
        rows.append(row)
        print(f"       {row['verdict']} lane={(row.get('reply_contract') or {}).get('lane') if isinstance(row.get('reply_contract'), dict) else None} ms={row['elapsed_ms']}", flush=True)

    elapsed_s = time.perf_counter() - started
    out_path = ROOT / args.out
    json_path = ROOT / args.json_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render(rows, started_at=started_at, elapsed_s=elapsed_s), encoding="utf-8")
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {out_path.relative_to(ROOT)}")
    print(f"[OK] wrote {json_path.relative_to(ROOT)}")
    if any(row["verdict"] == "FAIL" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
