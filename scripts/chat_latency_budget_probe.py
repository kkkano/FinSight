# -*- coding: utf-8 -*-
"""Probe chat UX latency under configurable LLM-planner budgets."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CASES = [
    ("L01", "smalltalk", "你好，你能帮我做什么？", {}),
    ("L02", "oos", "推荐一首适合睡前听的歌。", {}),
    ("L03", "concept", "ROE 是什么意思？用一句话解释。", {}),
    ("L04", "quote", "AAPL 现在多少钱？", {}),
    ("L05", "news", "GOOGL 最近有什么新闻？", {}),
    ("L06", "mixed", "今天挺累的，先告诉我 NVDA 现在多少，再简单说说最近新闻会不会影响它。", {}),
    ("L07", "macro", "美联储降息预期变化会怎么影响大型科技股？", {}),
    ("L08", "deixis", "那它最近有什么新闻？", {"active_symbol": "NVDA", "view": "chat"}),
]

FORBIDDEN = ("本轮问题包含", "分析对象", "get_stock_price", "get_company_news", "问题：", "后续关注：")


def _client():
    from fastapi.testclient import TestClient
    from backend.api.main import app

    return TestClient(app)


def _run_once(client: Any, case: tuple[str, str, str, dict[str, Any]], profile: str) -> dict[str, Any]:
    case_id, label, query, context = case
    payload = {
        "query": query,
        "session_id": f"tenant1:latency_eval:{profile}-{case_id}",
        "context": context,
        "options": {"confirmation_mode": "skip", "output_mode": "chat"},
    }
    started = time.perf_counter()
    resp = client.post("/chat/supervisor", json=payload)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    data = resp.json() if resp.status_code == 200 else {"response": resp.text}
    text = str(data.get("response") or "")
    graph = data.get("graph") if isinstance(data.get("graph"), dict) else {}
    trace = graph.get("trace") if isinstance(graph.get("trace"), dict) else {}
    planner_runtime = trace.get("planner_runtime") if isinstance(trace.get("planner_runtime"), dict) else {}
    hits = [marker for marker in FORBIDDEN if marker in text]
    return {
        "id": case_id,
        "label": label,
        "query": query,
        "status_code": resp.status_code,
        "elapsed_ms": elapsed_ms,
        "output_mode": graph.get("output_mode"),
        "planner_runtime": planner_runtime,
        "forbidden_hits": hits,
        "issues": [] if resp.status_code == 200 else [f"HTTP {resp.status_code}"],
        "response_len": len(text),
        "response": text,
    }


def _apply_profile(profile: dict[str, str]) -> None:
    os.environ["LANGGRAPH_CHECKPOINTER_BACKEND"] = "memory"
    os.environ["LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK"] = "true"
    for key, value in profile.items():
        os.environ[key] = value


def _render(rows: list[dict[str, Any]], profiles: dict[str, dict[str, str]]) -> str:
    lines = [
        "# Chat Latency Budget Probe (2026-05-04)",
        "",
        "## Profiles",
        "",
    ]
    for name, profile in profiles.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("```env")
        for key, value in profile.items():
            lines.append(f"{key}={value}")
        lines.append("```")
        lines.append("")

    lines.extend(["## Summary", "", "| Profile | avg ms | p95-ish ms | max ms | reviews |", "|---|---:|---:|---:|---:|"])
    for profile_name in profiles:
        subset = [row for row in rows if row["profile"] == profile_name]
        elapsed = sorted(row["elapsed_ms"] for row in subset)
        p95 = elapsed[min(len(elapsed) - 1, int(len(elapsed) * 0.95))] if elapsed else 0
        reviews = sum(1 for row in subset if row["elapsed_ms"] > int(profiles[profile_name].get("CHAT_UX_REVIEW_THRESHOLD_MS", "60000")) or row["forbidden_hits"])
        lines.append(
            f"| {profile_name} | {int(mean(elapsed)) if elapsed else 0} | {p95} | {max(elapsed) if elapsed else 0} | {reviews} |"
        )

    lines.extend(["", "## Cases", "", "| Profile | ID | Label | ms | Planner | Hits |", "|---|---|---|---:|---|---|"])
    for row in rows:
        runtime = row.get("planner_runtime") or {}
        planner = f"{runtime.get('mode')}/{runtime.get('fallback')}"
        hits = ", ".join(row["forbidden_hits"]) if row["forbidden_hits"] else "-"
        lines.append(f"| {row['profile']} | {row['id']} | {row['label']} | {row['elapsed_ms']} | {planner} | {hits} |")

    lines.extend(["", "## Full Answers", ""])
    for row in rows:
        lines.append(f"### {row['profile']} / {row['id']} / {row['label']}")
        lines.append("")
        lines.append(f"Elapsed: `{row['elapsed_ms']}ms`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(row.get("planner_runtime") or {}, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append(row["response"].strip() or "(empty)")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/qa/chat-latency-budget-probe-2026-05-04.md")
    args = parser.parse_args()

    os.environ["LANGGRAPH_CHECKPOINTER_BACKEND"] = "memory"
    os.environ["LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK"] = "true"

    profiles = {
        "stub": {
            "LANGGRAPH_PLANNER_MODE": "stub",
            "LANGGRAPH_SYNTHESIZE_MODE": "llm",
            "CHAT_UX_REVIEW_THRESHOLD_MS": "20000",
        },
        "llm-chat-recommended": {
            "LANGGRAPH_PLANNER_MODE": "llm",
            "LANGGRAPH_SYNTHESIZE_MODE": "llm",
            "FINSIGHT_CONTEXT_ROUTER_TIMEOUT_SEC": "90",
            "FINSIGHT_CONTEXT_ROUTER_MAX_TOKENS": "2200",
            "FINSIGHT_CONTEXT_REPLY_TIMEOUT_SEC": "120",
            "FINSIGHT_CONTEXT_REPLY_MAX_TOKENS": "3000",
            "LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC": "150",
            "LANGGRAPH_PLANNER_CHAT_MAX_TOKENS": "3000",
            "LANGGRAPH_PLANNER_CHAT_MAX_ATTEMPTS": "2",
            "LANGGRAPH_PLANNER_CHAT_ACQUIRE_TIMEOUT_SEC": "120",
            "LANGGRAPH_SYNTHESIZE_REPORT_TIMEOUT_SEC": "800",
            "CHAT_UX_REVIEW_THRESHOLD_MS": "180000",
        },
        "llm-chat-generous": {
            "LANGGRAPH_PLANNER_MODE": "llm",
            "LANGGRAPH_SYNTHESIZE_MODE": "llm",
            "FINSIGHT_CONTEXT_ROUTER_TIMEOUT_SEC": "120",
            "FINSIGHT_CONTEXT_ROUTER_MAX_TOKENS": "3000",
            "FINSIGHT_CONTEXT_REPLY_TIMEOUT_SEC": "180",
            "FINSIGHT_CONTEXT_REPLY_MAX_TOKENS": "4000",
            "LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC": "210",
            "LANGGRAPH_PLANNER_CHAT_MAX_TOKENS": "4000",
            "LANGGRAPH_PLANNER_CHAT_MAX_ATTEMPTS": "2",
            "LANGGRAPH_PLANNER_CHAT_ACQUIRE_TIMEOUT_SEC": "180",
            "LANGGRAPH_SYNTHESIZE_REPORT_TIMEOUT_SEC": "800",
            "CHAT_UX_REVIEW_THRESHOLD_MS": "240000",
        },
    }

    client = _client()
    rows: list[dict[str, Any]] = []
    for profile_name, profile in profiles.items():
        _apply_profile(profile)
        for case in CASES:
            print(f"[{profile_name}] {case[0]} {case[1]} {case[2][:42]}", flush=True)
            row = _run_once(client, case, profile_name)
            row["profile"] = profile_name
            rows.append(row)
            print(f"  -> {row['elapsed_ms']}ms planner={(row.get('planner_runtime') or {}).get('mode')}", flush=True)

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render(rows, profiles), encoding="utf-8")
    print(f"[OK] wrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
