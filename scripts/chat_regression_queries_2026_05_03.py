import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from backend.graph.runner import GraphRunner


@dataclass
class Case:
    name: str
    query: str
    output_mode: str = "brief"
    timeout_s: int = 90


CASES = [
    Case("multi_xiaomi_li_cpi", "小米和理想汽车，CPI 影响吗"),
    Case("nvda_news", "英伟达有什么新闻"),
    Case("msft_price", "今天微软什么价格"),
    Case("li_news_impact", "理想汽车最近新闻对股价影响是什么"),
    Case("macro_cpi", "CPI 对科技股有什么影响"),
    Case("compare_aapl_msft", "对比 AAPL 和 MSFT 最新表现，哪个风险更高", timeout_s=150),
    Case("tesla_news", "特斯拉最新关键新闻及影响"),
    Case("xiaomi_ev_news", "小米汽车有什么新闻"),
]


def _extract_answer(state: dict[str, Any]) -> str:
    artifacts = state.get("artifacts") if isinstance(state, dict) else {}
    if isinstance(artifacts, dict):
        draft = artifacts.get("draft_markdown")
        if isinstance(draft, str) and draft.strip():
            return draft.strip()
    return ""


async def run_case(runner: GraphRunner, case: Case) -> dict[str, Any]:
    started = time.perf_counter()
    thread_id = f"chat-regression-2026-05-03-{case.name}"
    try:
        state = await asyncio.wait_for(
            runner.ainvoke(
                thread_id=thread_id,
                query=case.query,
                ui_context={},
                output_mode=case.output_mode,
            ),
            timeout=case.timeout_s,
        )
        answer = _extract_answer(state)
        return {
            "name": case.name,
            "query": case.query,
            "status": "ok" if answer else "empty_answer",
            "elapsed_s": round(time.perf_counter() - started, 2),
            "answer": answer,
            "has_markdown_link": "](" in answer and "http" in answer,
            "has_final_answer_heading": "最终答案" in answer,
            "contains_process_brief": "我把这轮问题拆成" in answer or "本轮简报" in answer,
        }
    except Exception as exc:
        return {
            "name": case.name,
            "query": case.query,
            "status": "error",
            "elapsed_s": round(time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
            "answer": "",
            "has_markdown_link": False,
            "has_final_answer_heading": False,
            "contains_process_brief": False,
        }


def write_markdown(results: list[dict[str, Any]], path: str) -> None:
    lines: list[str] = [
        "# Chat Query Regression Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for item in results:
        lines.extend([
            f"## {item['name']}",
            "",
            f"- Query: `{item['query']}`",
            f"- Status: `{item['status']}`",
            f"- Elapsed: `{item['elapsed_s']}s`",
            f"- Markdown link present: `{item['has_markdown_link']}`",
            f"- Final-answer heading present: `{item['has_final_answer_heading']}`",
            f"- Process-brief wording present: `{item['contains_process_brief']}`",
            "",
            "### Answer",
            "",
            item.get("answer") or item.get("error") or "(empty)",
            "",
        ])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def main() -> None:
    runner = GraphRunner.create()
    out_dir = os.path.join(ROOT, "docs", "qa")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "chat_regression_queries_2026_05_03.json")
    md_path = os.path.join(out_dir, "chat_regression_queries_2026_05_03.md")

    results_by_name: dict[str, dict[str, Any]] = {}
    if os.path.exists(json_path):
        try:
            existing = json.load(open(json_path, "r", encoding="utf-8"))
            if isinstance(existing, list):
                results_by_name = {
                    str(item.get("name")): item
                    for item in existing
                    if isinstance(item, dict) and item.get("name")
                }
        except Exception:
            results_by_name = {}
    case_filter = os.getenv("CHAT_REGRESSION_CASES", "").strip()
    if case_filter:
        wanted = {item.strip() for item in case_filter.split(",") if item.strip()}
        cases = [case for case in CASES if case.name in wanted]
    else:
        cases = CASES
    for case in cases:
        print(f"[query] {case.name}: {case.query}", flush=True)
        result = await run_case(runner, case)
        print(f"[result] {case.name}: {result['status']} {result['elapsed_s']}s", flush=True)
        results_by_name[case.name] = result

    order = [case.name for case in CASES]
    results = [results_by_name[name] for name in order if name in results_by_name]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    write_markdown(results, md_path)
    print(md_path)


if __name__ == "__main__":
    asyncio.run(main())
