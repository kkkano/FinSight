# -*- coding: utf-8 -*-
"""验证 2026-05-03「答非所问」修复 — 跑 5 条代表性 query 看回答形态

修复前：
  - "今天微软什么价格" → 输出完整投资研究报告（投资论点+基本面+技术面+估值+风险）
  - "我老婆要我买基金…小米和理想…CPI 影响吗" → 只渲染理想，小米丢失

修复后预期：
  - brief Q&A → 短模板（≤ 1500 chars，不含「投资论点」5 章节硬骨架）
  - 显式 investment_report → narrative 长报告
  - 多任务（≥2 ticker）→ 按 task 分块（per-task sections）

输出: docs/reports/2026-05-03_answer_format_fix_probe.md
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.graph import GraphRunner


CASES: list[tuple[str, str, str, str, dict[str, Any]]] = [
    # (id, label, query, output_mode, ui_ctx)
    ("V01", "brief/price 微软", "今天微软什么价格", "brief", {}),
    ("V02", "brief/fetch NVDA 新闻", "英伟达有什么新闻", "brief", {}),
    ("V03", "brief/multi-task 小米+理想+CPI",
     "我老婆要我买基金，烦死了，对了帮我看下小米和理想汽车，CPI 影响吗", "brief", {}),
    ("V04", "investment_report 长报告", "生成 AAPL 投资研报", "investment_report", {}),
    ("V05", "brief/compare 双股", "GOOGL 和 MSFT 谁更强", "brief", {}),
]


async def _run_one(case_id: str, label: str, query: str, output_mode: str, ui_ctx: dict[str, Any]) -> dict[str, Any]:
    print(f"[{case_id}] {label[:30]:30s} ...", end=" ", flush=True)
    t0 = time.perf_counter()
    try:
        result = await GraphRunner.create().ainvoke(
            thread_id=f"probe-fix-{case_id}",
            query=query,
            ui_context=dict(ui_ctx),
            output_mode=output_mode,
        )
        elapsed = round(time.perf_counter() - t0, 2)
        artifacts = result.get("artifacts") or {}
        draft = artifacts.get("draft_markdown") or ""
        trace = result.get("trace") or {}
        synth_runtime = trace.get("synthesize_runtime") or {}
        mode = synth_runtime.get("mode")
        spans = trace.get("spans") or []
        nodes = [s.get("node") for s in spans]
        tasks = result.get("tasks") or []
        ticker_list = sorted({
            t for tk in tasks for t in (tk.get("tickers") or []) if isinstance(t, str)
        })
        # Heuristic check: 修复后 brief 模式不应包含「投资论点」「基本面分析」5 章节硬骨架
        narrative_marker_hits = sum(
            1 for marker in ("## 投资论点", "## 基本面分析", "## 技术面分析", "## 估值")
            if marker in draft
        )
        # 修复后多任务应该出现 per-task section（## N. ticker / op）
        multi_task_marker_hits = sum(
            1 for marker in ("### 1.", "### 2.", "### 3.")
            if marker in draft
        )
        print(
            f"{elapsed:>5.1f}s  mode={mode!s:9s} draft={len(draft):>5} narrative_5sec={narrative_marker_hits} per_task_sec={multi_task_marker_hits}"
        )
        return {
            "id": case_id,
            "label": label,
            "query": query,
            "output_mode": output_mode,
            "elapsed_s": elapsed,
            "synth_mode": mode,
            "nodes": nodes,
            "draft_len": len(draft),
            "draft_markdown": draft,
            "narrative_5sec_markers": narrative_marker_hits,
            "per_task_section_markers": multi_task_marker_hits,
            "tasks_tickers": ticker_list,
            "exception": None,
        }
    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 2)
        print(f"{elapsed:>5.1f}s  EXCEPTION: {type(exc).__name__}: {exc}")
        return {
            "id": case_id, "label": label, "query": query, "output_mode": output_mode,
            "elapsed_s": elapsed, "synth_mode": None, "nodes": [],
            "draft_len": 0, "draft_markdown": "",
            "narrative_5sec_markers": 0, "per_task_section_markers": 0,
            "tasks_tickers": [], "exception": f"{type(exc).__name__}: {exc}",
        }


async def main() -> None:
    print(f"# Answer-format-fix probe ({len(CASES)} queries)\n")
    rows: list[dict[str, Any]] = []

    out_path = ROOT / "docs" / "reports" / "2026-05-03_answer_format_fix_probe.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_report() -> None:
        lines: list[str] = []
        lines.append("# Answer-format-fix probe (2026-05-03)\n")
        lines.append("> 验证 synthesize 入口按 output_mode + 多任务分流的修复效果。")
        lines.append("> 修复 commit: synthesize.py:2155-2200 mode resolution\n")
        lines.append(f"## 进度: {len(rows)}/{len(CASES)}\n")
        lines.append("## 概览\n")
        lines.append("| ID | 标签 | output_mode | synth_mode | draft len | 5章节命中 | per-task命中 | tickers |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append(
                f"| {r['id']} | {r['label']} | {r['output_mode']} | {r['synth_mode']} | "
                f"{r['draft_len']} | {r['narrative_5sec_markers']} | "
                f"{r['per_task_section_markers']} | {','.join(r['tasks_tickers']) or '-'} |"
            )
        lines.append("")
        lines.append("## 详细回复（含完整 markdown）\n")
        for r in rows:
            lines.append(f"### {r['id']} — {r['label']}\n")
            lines.append(f"**Query**: `{r['query']}`")
            lines.append(f"\n- output_mode: `{r['output_mode']}`")
            lines.append(f"- synth_mode: `{r['synth_mode']}`")
            lines.append(f"- 节点链路: {' → '.join(r['nodes']) or '(none)'}")
            lines.append(f"- tickers: {','.join(r['tasks_tickers']) or '-'}")
            lines.append(f"- 耗时: {r['elapsed_s']}s")
            if r["exception"]:
                lines.append(f"\n**EXCEPTION**: `{r['exception']}`")
            if r["draft_markdown"]:
                lines.append(f"\n**回复（{r['draft_len']} chars）**:\n\n---\n")
                lines.append(r["draft_markdown"])
                lines.append("\n---\n")
            else:
                lines.append("\n（无 draft_markdown）\n")
        out_path.write_text("\n".join(lines), encoding="utf-8")

    for case in CASES:
        rows.append(await _run_one(*case))
        # Incremental write so we don't lose data if a later case crashes the process
        _write_report()

    # Verdict
    print("\n=== Verdict ===")
    for r in rows:
        v = []
        if r["exception"]:
            v.append("EXCEPTION")
        elif r["output_mode"] == "brief":
            if r["narrative_5sec_markers"] >= 3:
                v.append("BAD: brief 仍出 5 章节研报")
            elif r["draft_len"] > 3000:
                v.append(f"BAD: brief draft 太长 ({r['draft_len']})")
            else:
                v.append("OK: brief 短回答")
            # 多 ticker 时检查 per-task
            if len(r["tasks_tickers"]) >= 2:
                if r["per_task_section_markers"] >= 2:
                    v.append("OK: per-task 分块")
                else:
                    v.append(f"WARN: 多 ticker 但 per-task markers={r['per_task_section_markers']}")
        elif r["output_mode"] == "investment_report":
            if r["synth_mode"] == "narrative" and r["draft_len"] > 1500:
                v.append("OK: narrative 长报告保留")
            else:
                v.append(f"WARN: investment_report 期望 narrative, got mode={r['synth_mode']}")
        print(f"  {r['id']:>4} {r['label'][:30]:30s} | mode={r['synth_mode']:>9s} draft={r['draft_len']:>5}  {' / '.join(v)}")

    out_path = ROOT / "docs" / "reports" / "2026-05-03_answer_format_fix_probe.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Answer-format-fix probe (2026-05-03)\n")
    lines.append("> 验证 synthesize 入口按 output_mode + 多任务分流的修复效果。")
    lines.append("> 修复 commit: synthesize.py:2155-2200 mode resolution\n")
    lines.append("## 概览\n")
    lines.append("| ID | 标签 | output_mode | synth_mode | draft len | 5章节命中 | per-task命中 | tickers |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['label']} | {r['output_mode']} | {r['synth_mode']} | "
            f"{r['draft_len']} | {r['narrative_5sec_markers']} | "
            f"{r['per_task_section_markers']} | {','.join(r['tasks_tickers']) or '-'} |"
        )
    lines.append("")
    lines.append("## 详细回复（含完整 markdown）\n")
    for r in rows:
        lines.append(f"### {r['id']} — {r['label']}\n")
        lines.append(f"**Query**: `{r['query']}`")
        lines.append(f"\n- output_mode: `{r['output_mode']}`")
        lines.append(f"- synth_mode: `{r['synth_mode']}`")
        lines.append(f"- 节点链路: {' → '.join(r['nodes']) or '(none)'}")
        lines.append(f"- tickers: {','.join(r['tasks_tickers']) or '-'}")
        lines.append(f"- 耗时: {r['elapsed_s']}s")
        if r["exception"]:
            lines.append(f"\n**EXCEPTION**: `{r['exception']}`")
        if r["draft_markdown"]:
            lines.append(f"\n**回复（{r['draft_len']} chars）**:\n\n---\n")
            lines.append(r["draft_markdown"])
            lines.append("\n---\n")
        else:
            lines.append("\n（无 draft_markdown）\n")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] report → {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
