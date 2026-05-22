# -*- coding: utf-8 -*-
"""Deterministic eval gate for Skill/Python policy-planner routing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_set(value: Any) -> set[str]:
    return {str(item or "").strip() for item in _as_list(value) if str(item or "").strip()}


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    dataset_path = Path(path)
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(cases, list):
        raise ValueError(f"dataset must be a list or object with cases: {dataset_path}")
    result: list[dict[str, Any]] = []
    for item in cases:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id") or "").strip()
        if not case_id:
            raise ValueError("every eval case requires id")
        if not str(item.get("query") or "").strip():
            raise ValueError(f"eval case requires query: {case_id}")
        result.append(item)
    return result


def _build_state(case: dict[str, Any]) -> dict[str, Any]:
    ticker = str(case.get("ticker") or "").strip().upper()
    operation = str(case.get("operation") or "qa").strip() or "qa"
    subject = {
        "subject_type": str(case.get("subject_type") or "company"),
        "tickers": [ticker] if ticker else [],
        "selection_ids": [],
        "selection_types": [],
        "selection_payload": [],
    }
    task = {
        "id": "task_1",
        "subject_type": subject["subject_type"],
        "subject_label": ticker,
        "tickers": [ticker] if ticker else [],
        "operation": {"name": operation, "confidence": 0.9, "params": {}},
        "status": "ready",
    }
    ui_context = case.get("ui_context") if isinstance(case.get("ui_context"), dict) else {}
    return {
        "query": str(case.get("query") or ""),
        "operation": {"name": operation, "confidence": 0.9, "params": {}},
        "output_mode": str(case.get("output_mode") or "chat"),
        "subject": subject,
        "tasks": [task],
        "ui_context": ui_context,
    }


def collect_case_contract(case: dict[str, Any]) -> dict[str, Any]:
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate

    state = _build_state(case)
    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    policy = _as_dict(policy_out.get("policy"))
    plan_ir = _as_dict(plan_out.get("plan_ir"))
    steps = [step for step in _as_list(plan_ir.get("steps")) if isinstance(step, dict)]
    tool_steps = [step for step in steps if step.get("kind") == "tool"]
    agent_steps = [step for step in steps if step.get("kind") == "agent"]
    skill_selection = _as_dict(policy.get("skill_selection"))

    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "operation": _as_dict(state.get("operation")).get("name"),
        "selected_skill": skill_selection.get("selected_skill") or skill_selection.get("name"),
        "selected_agents": list(_as_list(policy.get("allowed_agents"))),
        "allowed_tools": list(_as_list(policy.get("allowed_tools"))),
        "step_tools": [str(step.get("name") or "") for step in tool_steps],
        "step_agents": [str(step.get("name") or "") for step in agent_steps],
        "python_steps": [step for step in tool_steps if str(step.get("name") or "") == "run_python_compute"],
        "budget": _as_dict(policy.get("budget")),
        "skill_selection": skill_selection,
    }


def _grade_case(case: dict[str, Any]) -> dict[str, Any]:
    contract = collect_case_contract(case)
    expect = _as_dict(case.get("expect"))
    issues: list[str] = []

    expected_operation = str(expect.get("operation") or "").strip()
    if expected_operation and contract.get("operation") != expected_operation:
        issues.append(f"operation {contract.get('operation')} != {expected_operation}")

    selected_skill = str(contract.get("selected_skill") or "").strip()
    expected_skill = str(expect.get("selected_skill") or "").strip()
    if expected_skill and selected_skill != expected_skill:
        issues.append(f"selected_skill {selected_skill or '<none>'} != {expected_skill}")
    if expect.get("forbid_skill") and selected_skill:
        issues.append(f"selected_skill should be empty, got {selected_skill}")

    selected_agents = set(contract.get("selected_agents") or [])
    step_agents = set(contract.get("step_agents") or [])
    required_agents = _as_set(expect.get("required_agents"))
    missing_agents = required_agents - selected_agents - step_agents
    if missing_agents:
        issues.append(f"missing required agents: {sorted(missing_agents)}")
    forbidden_agents = _as_set(expect.get("forbidden_agents"))
    leaked_agents = forbidden_agents.intersection(selected_agents.union(step_agents))
    if leaked_agents:
        issues.append(f"forbidden agents selected: {sorted(leaked_agents)}")

    allowed_tools = set(contract.get("allowed_tools") or [])
    step_tools = set(contract.get("step_tools") or [])
    required_tools = _as_set(expect.get("required_tools"))
    missing_tools = required_tools - allowed_tools - step_tools
    if missing_tools:
        issues.append(f"missing required tools: {sorted(missing_tools)}")
    forbidden_tools = _as_set(expect.get("forbidden_tools"))
    leaked_tools = forbidden_tools.intersection(allowed_tools.union(step_tools))
    if leaked_tools:
        issues.append(f"forbidden tools selected: {sorted(leaked_tools)}")

    python_expected = expect.get("python_expected")
    python_steps = _as_list(contract.get("python_steps"))
    if python_expected is True and not python_steps:
        issues.append("run_python_compute step missing")
    if python_expected is False and python_steps:
        issues.append("run_python_compute should not run")

    return {
        "id": case.get("id"),
        "verdict": "PASS" if not issues else "FAIL",
        "issues": issues,
        "contract": contract,
    }


def evaluate_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [_grade_case(case) for case in cases]
    return [row for row in rows if row["verdict"] != "PASS"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="tests/eval/skill_python_query_cases.json")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    failures = evaluate_cases(cases)
    payload = {"case_count": len(cases), "fail_count": len(failures), "failures": failures}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
