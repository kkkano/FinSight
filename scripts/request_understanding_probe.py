# -*- coding: utf-8 -*-
"""生成请求理解层 query matrix 的 Markdown 摘要。"""
from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.nodes.understand_request import understand_request


CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("Q01", "你好", {}),
    ("Q02", "谷歌AI业务进展如何", {}),
    ("Q03", "美联储利率路径对大型科技股估值有什么影响", {}),
    (
        "Q04",
        "你好，今天天气不错，帮我看看谷歌昨天涨了多少，谷歌有什么新闻，"
        "然后微软呢？微软的新闻和涨幅如何？最近有没有发生什么大事影响我的几只股票？"
        "我的调仓要变动吗？",
        {},
    ),
    ("Q05", "早，昨天苹果为什么跌了？微软也是同样原因吗？如果不是，分别列出主要原因。", {}),
    ("Q06", "美联储这周降息概率变了吗？这对QQQ、苹果、微软和我的科技股仓位有什么影响？", {}),
    ("Q07", "先别做长报告，30秒告诉我谷歌和微软今天谁更强，新闻、涨跌幅、风险点各一句。", {}),
    (
        "Q08",
        "做深度研究：NVDA，但只看最近一周新闻、财报和竞争格局，最后给我买入/观望/卖出的理由。",
        {"analysis_depth": "deep_research", "output_mode": "investment_report"},
    ),
    ("Q09", "我持有AAPL、GOOGL、MSFT，现在CPI超预期，对我的组合影响最大的是哪一个？需要怎么调仓？", {}),
    (
        "Q10",
        "看一下这条新闻会不会影响TSLA和我的组合，顺便如果TSLA跌破180提醒我。",
        {"selection": {"type": "news", "id": "n1", "title": "Tesla delivery update"}},
    ),
    ("Q11", "我昨天问的那家公司今天有什么更新？如果你不知道我说的是谁，就按苹果处理。", {}),
    (
        "Q12",
        "这个PDF里的公司和谷歌相比怎么样？重点看收入增长和估值，不要泛泛而谈。",
        {"selection": {"type": "doc", "id": "d1", "title": "research.pdf"}},
    ),
    ("Q13", "最近有什么大事影响半导体？NVDA、AMD、TSM分别怎么看，给表格，不要长篇。", {}),
    ("Q14", "谷歌AI capex 会不会拖累利润率？微软和Meta有没有类似问题？顺便看一下最近市场怎么定价。", {}),
    ("Q15", "不用deep search，快速看下GOOGL和MSFT今天涨跌、新闻、有没有需要我马上注意的风险。", {"analysis_depth": "quick"}),
    ("Q16", "帮我看看苹果今天咋样，然后把刚才说的那个风险也考虑进去。", {"active_symbol": "AAPL"}),
    ("Q17", "如果今天纳指继续跌，AAPL、MSFT、NVDA哪个对我组合拖累最大？我没有组合的话就按等权假设。", {}),
    ("Q18", "请先确认美联储今天有没有公告，再判断这会不会影响我的持仓；如果没持仓，就只讲对大型科技股估值的影响。", {}),
    ("Q19", "GOOGL 和 Apple 今天有什么新闻？", {}),
    ("Q20", "TSLA 跌破 200 提醒我", {}),
]


def _op_name(task: dict[str, Any]) -> str:
    op = task.get("operation")
    if isinstance(op, dict):
        return str(op.get("name") or "qa")
    return "qa"


def _task_label(task: dict[str, Any]) -> str:
    subject = str(task.get("subject_type") or "unknown")
    tickers = task.get("tickers") if isinstance(task.get("tickers"), list) else []
    ticker_label = ",".join(str(ticker) for ticker in tickers) if tickers else "-"
    scope = task.get("time_scope") if isinstance(task.get("time_scope"), dict) else {}
    scope_label = str(scope.get("kind") or "-")
    return f"{subject}:{ticker_label}:{_op_name(task)}:{scope_label}"


async def _run_case(case_id: str, query: str, ui_context: dict[str, Any]) -> dict[str, Any]:
    output_mode = ui_context.get("output_mode") if isinstance(ui_context.get("output_mode"), str) else "brief"
    state: dict[str, Any] = {
        "query": query,
        "ui_context": ui_context,
        "output_mode": output_mode,
        "trace": {},
    }
    understood = await understand_request(state)  # type: ignore[arg-type]
    merged = {**state, **understood}
    route = str((merged.get("understanding") or {}).get("route") or "")
    policy: dict[str, Any] = {}
    plan_steps: list[dict[str, Any]] = []
    if route == "research":
        policy_out = policy_gate(merged)  # type: ignore[arg-type]
        merged = {**merged, **policy_out}
        policy = policy_out.get("policy") or {}
        plan_out = planner_stub(merged)  # type: ignore[arg-type]
        plan_steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    return {
        "id": case_id,
        "query": query,
        "route": route,
        "output_mode": merged.get("output_mode"),
        "tasks": [_task_label(task) for task in (merged.get("tasks") or [])],
        "blocked": [
            f"{item.get('subject_type')}:{item.get('reason')}"
            for item in (merged.get("blocked_tasks") or [])
            if isinstance(item, dict)
        ],
        "tools": list(policy.get("allowed_tools") or [])[:10],
        "steps": [
            f"{step.get('name')}({step.get('inputs')})"
            for step in plan_steps[:10]
            if isinstance(step, dict)
        ],
    }


async def main() -> None:
    rows = [await _run_case(*case) for case in CASES]
    lines = [
        "# Request Understanding Query Matrix Results",
        "",
        "生成命令：`python scripts/request_understanding_probe.py --output docs/reports/2026-05-03_request_understanding_query_results.md`",
        "",
        "| ID | Query | Route | Output | Tasks | Blocked | Planned steps |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        tasks = "<br>".join(row["tasks"]) or "-"
        blocked = "<br>".join(row["blocked"]) or "-"
        steps = "<br>".join(row["steps"]) or "-"
        query = str(row["query"]).replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {query} | {row['route']} | {row['output_mode']} | {tasks} | {blocked} | {steps} |"
        )
    content = "\n".join(lines) + "\n"

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="可选：写入 Markdown 文件")
    args = parser.parse_args()
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    asyncio.run(main())
