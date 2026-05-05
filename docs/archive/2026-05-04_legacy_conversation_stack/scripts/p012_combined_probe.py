# -*- coding: utf-8 -*-
"""P0/P1/P2 联合验证脚本

构造 20 条混合复杂 query，覆盖：
  - P0 金融词表扩展（中文公司名 / 宏观词应 0ms 直通）
  - P1 crypto + 中文 ADR 别名（比特币 / 台积电 / 腾讯 / 美团 ...）
  - P2 弱兜底（vague deixis + active_symbol）
  - 兜底鲁棒性（无 active_symbol、显式 ticker、闲聊不误激活）

跑完整 chat_respond → understand_request → policy_gate → planner_stub
链路并写报告到 docs/reports/2026-05-03_p012_combined_test.md。
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

from backend.graph.nodes.chat_respond import chat_respond
from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.nodes.understand_request import understand_request


# 20 条针对 P0/P1/P2 的新 query
CASES: list[tuple[str, str, str, dict[str, Any]]] = [
    # === P0 金融词表扩展验证（之前会走 5-12s LLM, 现在应 0ms）===
    ("Q01", "P0/中文公司名", "苹果今天涨了多少？", {}),
    ("Q02", "P0/中文公司名+情绪", "我心情不好，谷歌财报怎么样？", {}),
    ("Q03", "P0/宏观缩写", "CPI 数据出了吗？影响哪些板块？", {}),
    ("Q04", "P0/宏观+多公司", "PMI 上行对半导体板块和英伟达有什么影响？", {}),
    ("Q05", "P0/操作动词", "套牢了，要割肉还是补仓？", {}),

    # === P1 crypto + CN ADR ===
    ("Q06", "P1/crypto", "比特币现在多少？要不要买点？", {}),
    ("Q07", "P1/多 crypto+对比", "比特币、以太坊、索拉纳哪个最近最强？", {}),
    ("Q08", "P1/crypto+commodity", "黄金还是比特币该买哪个？", {}),
    ("Q09", "P1/CN ADR 台积电", "台积电封测业务怎么看？", {}),
    ("Q10", "P1/CN ADR 腾讯+网易", "腾讯和网易游戏业务对比一下", {}),
    ("Q11", "P1/CN ADR 美团+小米", "美团外卖增长和小米汽车销量哪个对市值影响大", {}),

    # === P2 弱兜底验证 ===
    ("Q12", "P2/弱兜底命中", "这只票今天怎么了，要不要跑？", {"active_symbol": "AAPL"}),
    ("Q13", "P2/弱兜底命中-长形式", "刚才那个公司今天涨了多少", {"active_symbol": "TSLA"}),
    ("Q14", "P2/弱兜底命中-英文", "is this stock worth holding?", {"active_symbol": "GOOGL"}),
    ("Q15", "P2/兜底安全降级-无active", "这只票今天怎么了", {}),
    ("Q16", "P2/显式胜出-不误覆盖", "帮我看苹果", {"active_symbol": "GOOGL"}),

    # === 综合复杂 query ===
    ("Q17", "综合/P0+P1", "今天通胀压力大，比特币和台积电谁能扛住？", {}),
    ("Q18", "综合/P0+P2", "这家公司财报怎么看？", {"active_symbol": "NVDA"}),
    ("Q19", "综合/原 mixed Q01 重跑", "今天天气不错，谷歌现在多少了？要不要跑路？微软呢？", {}),
    ("Q20", "综合/极端混合", "我老婆要我买基金，烦死了，对了帮我看下小米和理想汽车，CPI 影响吗？", {}),
]


def _task_label(task: dict[str, Any]) -> str:
    subject = str(task.get("subject_type") or "?")
    tickers = task.get("tickers") if isinstance(task.get("tickers"), list) else []
    ticker_label = ",".join(str(t) for t in tickers) if tickers else "-"
    op = task.get("operation")
    op_name = str(op.get("name") if isinstance(op, dict) else "qa") or "qa"
    return f"{subject}:{ticker_label}:{op_name}"


async def _run_one(case_id: str, label: str, query: str, ui_ctx: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "query": query,
        "messages": [],
        "ui_context": ui_ctx,
        "output_mode": ui_ctx.get("output_mode") or "brief",
        "trace": {},
    }

    t0 = time.perf_counter()
    chat_out = await chat_respond(state)
    chat_ms = round((time.perf_counter() - t0) * 1000, 1)

    if chat_out.get("chat_responded"):
        artifacts = chat_out.get("artifacts") or {}
        cls = artifacts.get("intent_classification")
        return {
            "id": case_id, "label": label, "query": query, "ui_ctx": ui_ctx,
            "stopped_at": "chat_respond",
            "chat_ms": chat_ms,
            "tier": "tier2_llm_oos" if cls else "tier1_rule",
            "classification": cls,
            "reply": artifacts.get("draft_markdown"),
            "route": None, "tasks": [], "blocked": [], "fallback_assumptions": [],
        }

    state.update(chat_out)
    t1 = time.perf_counter()
    understood = await understand_request(state)
    understand_ms = round((time.perf_counter() - t1) * 1000, 1)
    merged = {**state, **understood}
    understanding = merged.get("understanding") or {}
    route = str(understanding.get("route") or "")

    result: dict[str, Any] = {
        "id": case_id, "label": label, "query": query, "ui_ctx": ui_ctx,
        "stopped_at": "understand_request" if route in ("direct", "clarify") else "policy_gate",
        "chat_ms": chat_ms, "understand_ms": understand_ms,
        "tier": "passthrough", "classification": None,
        "route": route,
        "tasks": [_task_label(t) for t in (merged.get("tasks") or [])],
        "blocked": [
            f"{b.get('subject_type')}:{b.get('reason')}"
            for b in (merged.get("blocked_tasks") or [])
            if isinstance(b, dict)
        ],
        "fallback_assumptions": list(understanding.get("fallback_assumptions") or []),
        "reply": understanding.get("user_visible_summary") or "(no direct reply)",
    }

    if route in ("research", "mixed"):
        try:
            t2 = time.perf_counter()
            policy_out = policy_gate(merged)
            merged = {**merged, **policy_out}
            plan_out = planner_stub(merged)
            steps = (plan_out.get("plan_ir") or {}).get("steps") or []
            result["plan_steps"] = [
                f"{s.get('name')}({list((s.get('inputs') or {}).keys())})"
                for s in steps[:6] if isinstance(s, dict)
            ]
            result["plan_ms"] = round((time.perf_counter() - t2) * 1000, 1)
            result["stopped_at"] = "planner"
        except Exception as exc:
            result["plan_error"] = f"{type(exc).__name__}: {exc}"

    return result


def _emoji(stopped_at: str, tier: str) -> str:
    return {
        "tier1_rule": "T1", "tier2_llm_oos": "T2",
    }.get(tier, {
        "understand_request": "UR", "policy_gate": "PG", "planner": "PL",
    }.get(stopped_at, "?"))


async def main() -> None:
    print(f"# P0/P1/P2 combined verification — {len(CASES)} queries\n")
    rows: list[dict[str, Any]] = []
    for i, case in enumerate(CASES, 1):
        r = await _run_one(*case)
        rows.append(r)
        print(f"[{i:02d}/{len(CASES)}] {_emoji(r['stopped_at'], r['tier']):>3} "
              f"chat={r['chat_ms']:>6.0f}ms "
              f"under={r.get('understand_ms', 0):>6.0f}ms "
              f"  {case[1]:30s} {case[2]!r}")
        if r.get("tasks"):
            print(f"        tasks: {', '.join(r['tasks'])}")
        if r.get("fallback_assumptions"):
            print(f"        fallback: {' | '.join(r['fallback_assumptions'])}")

    out_path = ROOT / "docs" / "reports" / "2026-05-03_p012_combined_test.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# P0/P1/P2 联合验证报告 (2026-05-03)\n")
    lines.append("> 脚本：`scripts/p012_combined_probe.py`")
    lines.append("> 验证：P0 金融词表扩展 / P1 crypto+ADR / P2 弱兜底")
    lines.append("> 对比基线：`docs/reports/2026-05-03_mixed_complex_query_test.md`\n")

    # 延迟统计
    chat_times = [r["chat_ms"] for r in rows if r["chat_ms"] is not None]
    pruned = [r for r in rows if r["chat_ms"] < 100 and r["stopped_at"] != "chat_respond"]
    not_pruned = [r for r in rows if r["chat_ms"] >= 100]
    lines.append("## 关键指标\n")
    lines.append(f"- **总 query 数**: {len(rows)}")
    lines.append(f"- **chat_respond 平均延迟**: {sum(chat_times)/len(chat_times):.1f} ms")
    lines.append(f"- **0ms 提前剪枝命中**: {len(pruned)}/{len(rows)} （P0+P1 直通）")
    lines.append(f"- **触发 LLM Tier-2**: {len(not_pruned)}/{len(rows)}")
    lines.append(f"- **P2 弱兜底命中**: {sum(1 for r in rows if r['fallback_assumptions'])} 条\n")

    # 终止节点
    stops: dict[str, int] = {}
    for r in rows:
        stops[r["stopped_at"]] = stops.get(r["stopped_at"], 0) + 1
    lines.append("## 终止节点分布\n")
    lines.append("| 节点 | 数量 |")
    lines.append("|---|---|")
    for k, v in sorted(stops.items(), key=lambda x: -x[1]):
        lines.append(f"| `{k}` | {v} |")
    lines.append("")

    # 概览
    lines.append("## 概览（20 条）\n")
    lines.append("| ID | 标签 | chat_ms | 节点 | Tier/Route | Tasks | Fallback |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        tier_route = r['tier'] if r['tier'] in ('tier1_rule', 'tier2_llm_oos') else (r.get('route') or '-')
        tasks = "<br>".join(r['tasks']) or "-"
        fb = "<br>".join(r['fallback_assumptions']) or "-"
        lines.append(f"| {r['id']} | {r['label']} | {r['chat_ms']} | {r['stopped_at']} | {tier_route} | {tasks} | {fb} |")
    lines.append("")

    # 详细
    lines.append("## 详细记录\n")
    for r in rows:
        lines.append(f"### {r['id']} — {r['label']}\n")
        lines.append(f"**Query**: `{r['query']}`")
        if r['ui_ctx']:
            lines.append(f"**UI Context**: `{r['ui_ctx']}`")
        lines.append(f"\n- **终止节点**: `{r['stopped_at']}`")
        lines.append(f"- **Tier/Route**: `{r['tier']}` / `{r.get('route') or '-'}`")
        lines.append(f"- **延迟**: chat={r['chat_ms']}ms, understand={r.get('understand_ms', 0)}ms")
        if r.get("classification"):
            cls = r["classification"]
            lines.append(f"- **LLM 分类**: `{cls.get('category')}` conf={cls.get('confidence')} reason={cls.get('reason')!r}")
        if r["tasks"]:
            lines.append(f"- **任务** ({len(r['tasks'])}):")
            for t in r["tasks"]:
                lines.append(f"  - `{t}`")
        if r["blocked"]:
            lines.append(f"- **阻塞**: {', '.join('`' + b + '`' for b in r['blocked'])}")
        if r["fallback_assumptions"]:
            lines.append(f"- **🛡️ 弱兜底提示**:")
            for fa in r["fallback_assumptions"]:
                lines.append(f"  - `{fa}`")
        if r.get("plan_steps"):
            lines.append(f"- **计划步骤** ({len(r['plan_steps'])}):")
            for s in r["plan_steps"]:
                lines.append(f"  - `{s}`")
        if r.get("reply") and r["reply"] != "(no direct reply)":
            lines.append(f"\n**回复**: {r['reply']}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] report written to {out_path.relative_to(ROOT)}")
    print(f"  0ms pruning hits: {len(pruned)}/{len(rows)}, fallback hits: {sum(1 for r in rows if r['fallback_assumptions'])}")


if __name__ == "__main__":
    asyncio.run(main())
