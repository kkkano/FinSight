import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from multiprocessing import Process, Queue
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from backend.graph.runner import GraphRunner
from backend.graph.report_builder import build_report_payload


@dataclass
class Case:
    name: str
    query: str
    ui_context: Optional[Dict[str, Any]] = None
    output_mode: str = "investment_report"
    thread_id: Optional[str] = None


ALL_CASES: List[Case] = [
    Case(name="price", query="AAPL price now", ui_context={"active_symbol": "AAPL"}),
    Case(name="news", query="AAPL latest news", ui_context={"active_symbol": "AAPL"}),
    Case(name="sentiment", query="AAPL market sentiment today", ui_context={"active_symbol": "AAPL"}),
    Case(name="technical", query="AAPL technical analysis RSI MACD", ui_context={"active_symbol": "AAPL"}),
    Case(name="fundamental", query="AAPL valuation PE EPS revenue", ui_context={"active_symbol": "AAPL"}),
    Case(name="macro", query="AAPL macro impact of CPI and rates", ui_context={"active_symbol": "AAPL"}),
    Case(name="report", query="Deep analysis report on AAPL with macro and technical", ui_context={"active_symbol": "AAPL"}),
    Case(name="comparison", query="Compare AAPL and MSFT fundamentals and technicals", ui_context={"active_symbol": "AAPL"}),
    Case(name="search", query="What happened to Nvidia yesterday", ui_context=None),
]


def _report_ok(report: Dict[str, Any]) -> bool:
    if not isinstance(report, dict):
        return False
    if not (report.get("summary") or "").strip():
        return False
    if not (report.get("synthesis_report") or "").strip():
        return False
    if not (report.get("sections") or []):
        return False
    return True


async def run_case(runner: GraphRunner, case: Case, max_attempts: int = 1, timeout_s: int = 180) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        thread_id = case.thread_id or f"query-matrix-{case.name}-{attempt}"
        t0 = time.perf_counter()
        try:
            state = await asyncio.wait_for(
                runner.ainvoke(
                    thread_id=thread_id,
                    query=case.query,
                    ui_context=case.ui_context or {},
                    output_mode=case.output_mode,
                ),
                timeout=timeout_s,
            )
            elapsed = time.perf_counter() - t0
            clarify = (state.get("clarify") or {}) if isinstance(state, dict) else {}
            if clarify.get("needed"):
                attempts.append({
                    "attempt": attempt,
                    "status": "clarify",
                    "elapsed_s": round(elapsed, 2),
                    "clarify": clarify,
                })
                continue

            report = build_report_payload(state=state, query=case.query, thread_id=thread_id)
            ok = _report_ok(report)
            attempts.append({
                "attempt": attempt,
                "status": "ok" if ok else "bad_report",
                "elapsed_s": round(elapsed, 2),
                "report_id": report.get("report_id") if isinstance(report, dict) else None,
                "summary_len": len((report.get("summary") or "")) if isinstance(report, dict) else 0,
                "sections": len(report.get("sections") or []) if isinstance(report, dict) else 0,
                "citations": len(report.get("citations") or []) if isinstance(report, dict) else 0,
                "synthesis_len": len((report.get("synthesis_report") or "")) if isinstance(report, dict) else 0,
            })

            # Save report json for inspection
            out_dir = os.path.join(ROOT, "scripts", "query_matrix_outputs")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{case.name}-attempt-{attempt}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)

            if ok:
                return {"case": case.name, "query": case.query, "status": "pass", "attempts": attempts}
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - t0
            attempts.append({
                "attempt": attempt,
                "status": "timeout",
                "elapsed_s": round(elapsed, 2),
                "error": f"timeout {timeout_s}s",
            })
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            attempts.append({
                "attempt": attempt,
                "status": "exception",
                "elapsed_s": round(elapsed, 2),
                "error": f"{type(exc).__name__}: {exc}",
            })

    return {"case": case.name, "query": case.query, "status": "fail", "attempts": attempts}


def _run_case_in_subprocess(case: Case, timeout_s: int) -> Dict[str, Any]:
    runner = GraphRunner.create()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(run_case(runner, case, max_attempts=1, timeout_s=timeout_s))
        return result
    finally:
        loop.close()


def _case_worker(case: Case, timeout_s: int, queue: Queue) -> None:
    try:
        queue.put(_run_case_in_subprocess(case, timeout_s))
    except Exception as exc:
        queue.put({
            "case": case.name,
            "query": case.query,
            "status": "fail",
            "attempts": [{
                "attempt": 1,
                "status": "exception",
                "elapsed_s": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }],
        })


def write_markdown(results: List[Dict[str, Any]], path: str) -> None:
    lines: List[str] = []
    lines.append("# Query Matrix Report")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    for res in results:
        lines.append(f"## {res['case']}")
        lines.append("")
        lines.append(f"Query: `{res['query']}`")
        lines.append("")
        lines.append(f"Final status: **{res['status']}**")
        lines.append("")
        lines.append("Attempts:")
        for attempt in res.get("attempts", []):
            status = attempt.get("status")
            lines.append(
                f"- attempt {attempt.get('attempt')}: {status} | elapsed {attempt.get('elapsed_s')}s | "
                f"summary_len={attempt.get('summary_len')} | sections={attempt.get('sections')} | "
                f"citations={attempt.get('citations')} | synthesis_len={attempt.get('synthesis_len')}"
            )
        lines.append("")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _load_existing_results(path: str) -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _save_results(path: str, results: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def main():
    timeout_s = int(os.getenv("QUERY_MATRIX_TIMEOUT_SECONDS", "60"))
    case_filter = os.getenv("QUERY_MATRIX_CASES", "").strip()
    if case_filter:
        wanted = {c.strip().lower() for c in case_filter.split(",") if c.strip()}
        cases = [c for c in ALL_CASES if c.name.lower() in wanted]
    else:
        cases = list(ALL_CASES)

    results_by_case = _load_existing_results(os.path.join(ROOT, "scripts", "query_matrix_results.json"))
    procs: List[Tuple[Case, Process, Queue, float]] = []

    for case in cases:
        queue = Queue()
        proc = Process(target=_case_worker, args=(case, timeout_s, queue))
        proc.start()
        procs.append((case, proc, queue, time.time()))

    for case, proc, queue, start_ts in procs:
        remaining = timeout_s - max(0, int(time.time() - start_ts))
        proc.join(timeout=max(1, remaining))
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            results_by_case[case.name] = {
                "case": case.name,
                "query": case.query,
                "status": "fail",
                "attempts": [{
                    "attempt": 1,
                    "status": "timeout",
                    "elapsed_s": timeout_s,
                    "error": f"timeout {timeout_s}s (process)",
                }],
            }
            continue
        if not queue.empty():
            result = queue.get()
            results_by_case[case.name] = result
        else:
            results_by_case[case.name] = {
                "case": case.name,
                "query": case.query,
                "status": "fail",
                "attempts": [{
                    "attempt": 1,
                    "status": "exception",
                    "elapsed_s": 0,
                    "error": "no result returned from subprocess",
                }],
            }

    out_path = os.path.join(ROOT, "docs", "QUERY_MATRIX_REPORT.md")
    ordered_results = [results_by_case.get(c.name, {"case": c.name, "query": c.query, "status": "missing", "attempts": []}) for c in ALL_CASES]
    write_markdown(ordered_results, out_path)
    _save_results(os.path.join(ROOT, "scripts", "query_matrix_results.json"), results_by_case)
    print(f"Report written: {out_path}")


if __name__ == "__main__":
    main()
