from backend.graph.planning.context import PlanContext
from backend.graph.planning.frames import _append_request_frame_steps
from backend.graph.synthesis.structured_orchestration import prepare_chat_task_contract


def _task(task_id="task_1", frame_id="primary_company"):
    return {
        "id": task_id, "request_frame_id": frame_id, "render_group_id": frame_id,
        "render_kind": "single", "order_index": 0, "priority": 20,
        "operation": {"name": "technical"}, "subject_label": "INTC",
        "subject_type": "company", "tickers": ["INTC"],
    }


def _context(tasks, frames):
    ctx = PlanContext(
        query="INTC research", ready_tasks=tasks, request_frames=frames,
        allowed_tools={"get_stock_price", "get_technical_snapshot", "get_performance_comparison",
                       "get_current_datetime", "get_official_macro_releases"},
        allowed_agents=set(), step_id=1,
    )
    ctx.ready_tasks_by_id = {task["id"]: task for task in tasks}
    ctx.ready_task_id_set = set(ctx.ready_tasks_by_id)
    return ctx


def test_primary_company_frame_binds_real_task_and_successful_results():
    task = _task()
    frame = {"frame_id": "primary_company", "subject": {"type": "company", "tickers": ["INTC"]},
             "evidence_obligations": ["price_snapshot", "technical_snapshot"]}
    ctx = _context([task], [frame])
    assert _append_request_frame_steps(ctx)
    assert all(step["task_ids"] == ["task_1"] for step in ctx.steps)
    assert all(step["parallel_group"] == "primary_company" for step in ctx.steps)
    state = {
        "tasks": [task], "plan_ir": {"tasks": [task], "steps": ctx.steps},
        "artifacts": {"step_results": {step["id"]: {"output": "fixture evidence"} for step in ctx.steps}},
    }
    prepared, _ = prepare_chat_task_contract(state, {})
    outcome = prepared["artifacts"]["task_outcomes"][0]
    assert outcome["successful_step_ids"] == [step["id"] for step in ctx.steps]
    assert outcome["status"] != "unavailable"
    assert "no_successful_result" not in outcome["error_codes"]


def test_shared_compare_frame_binds_both_real_tasks():
    tasks = [_task("nvda", "compare_frame"), _task("amd", "compare_frame")]
    ctx = _context(tasks, [{"frame_id": "compare_frame", "subject": {"type": "company", "tickers": ["NVDA", "AMD"]},
                           "evidence_obligations": ["performance_comparison"]}])
    assert _append_request_frame_steps(ctx)
    assert ctx.steps[0]["task_ids"] == ["nvda", "amd"]


def test_macro_frame_uses_task_identity():
    ctx = _context([_task("macro_task", "macro_frame")], [{"frame_id": "macro_frame", "subject": {"type": "macro"},
                                                           "evidence_obligations": ["macro_context"]}])
    assert _append_request_frame_steps(ctx)
    assert all(step["task_ids"] == ["macro_task"] for step in ctx.steps)


def test_unbound_frame_returns_to_task_planner_without_partial_steps():
    ctx = _context([_task()], [{"frame_id": "different_frame", "evidence_obligations": ["price_snapshot"]}])
    assert not _append_request_frame_steps(ctx)
    assert ctx.steps == []


def test_frame_only_legacy_plan_remains_available_without_task_contracts():
    ctx = _context([], [{"frame_id": "legacy", "subject": {"type": "company", "tickers": ["INTC"]},
                        "evidence_obligations": ["price_snapshot"]}])
    assert _append_request_frame_steps(ctx)
    assert ctx.steps[0]["task_ids"] == ["legacy"]
