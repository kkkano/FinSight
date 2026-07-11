"""Request and runtime helpers used by the policy gate node."""
from __future__ import annotations

from backend.utils.env import env_bool as _env_bool

import os
import re

from backend.graph.intent_contract import canonical_evidence_kinds
from backend.graph.state import GraphState
from backend.graph.understanding_v2 import (
    VALUATION_COMPARE_LIGHT_PROFILE,
    project_v2_tasks_to_legacy,
)


def _bounded_env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except Exception:
        return default
    return max(min_value, min(max_value, value))


def _is_dashboard_source(ui_context: dict | None) -> bool:
    if not isinstance(ui_context, dict):
        return False
    source = str(ui_context.get("source") or "").strip().lower()
    return bool(source) and source.startswith("dashboard")


def _is_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _agent_research_config(agent_preferences: dict) -> dict[str, int | bool]:
    """Build the per-agent research config.

    ``FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG`` is an ops override for production
    experiments: it wins over stale browser-local preferences that still submit
    ``enableLLMAnalysis=false``.
    """

    forced = _env_bool("FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG", False)
    env_reflections = _bounded_env_int(
        "FINSIGHT_AGENT_REFLECTION_ROUNDS",
        _bounded_env_int("BASE_AGENT_MAX_REFLECTIONS", 3 if forced else 0, min_value=0, max_value=3),
        min_value=0,
        max_value=3,
    )
    env_analysis_timeout = _bounded_env_int(
        "FINSIGHT_AGENT_ANALYSIS_TIMEOUT_SECONDS",
        _bounded_env_int("AGENT_LLM_ANALYZE_CALL_TIMEOUT_SECONDS", 120 if forced else 0, min_value=0, max_value=120),
        min_value=0,
        max_value=120,
    )
    env_token_timeout = _bounded_env_int(
        "FINSIGHT_AGENT_TOKEN_ACQUIRE_TIMEOUT_SECONDS",
        _bounded_env_int("AGENT_LLM_ANALYZE_TIMEOUT_SECONDS", 60 if forced else 0, min_value=0, max_value=60),
        min_value=0,
        max_value=60,
    )

    if forced:
        return {
            "enable_llm_analysis": True,
            "max_reflections": env_reflections,
            "analysis_timeout_seconds": env_analysis_timeout,
            "token_acquire_timeout_seconds": env_token_timeout,
        }

    enable_default = _env_bool("AGENT_LLM_ANALYZE_ENABLED", False)
    pref_enable = agent_preferences.get("enableLLMAnalysis")
    enable_llm = pref_enable if isinstance(pref_enable, bool) else enable_default

    def _pref_int(key: str, default: int, *, min_value: int, max_value: int) -> int:
        raw = agent_preferences.get(key)
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    return {
        "enable_llm_analysis": bool(enable_llm),
        "max_reflections": _pref_int("reflectionRounds", env_reflections, min_value=0, max_value=3),
        "analysis_timeout_seconds": _pref_int(
            "analysisTimeoutSeconds",
            env_analysis_timeout,
            min_value=0,
            max_value=120,
        ),
        "token_acquire_timeout_seconds": _pref_int(
            "tokenAcquireTimeoutSeconds",
            env_token_timeout,
            min_value=0,
            max_value=60,
        ),
    }


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(needle or "").lower() in lowered for needle in needles)


def _append_missing(items: list[str], names: tuple[str, ...]) -> list[str]:
    seen = set(items)
    for name in names:
        if name in seen:
            continue
        items.append(name)
        seen.add(name)
    return items


def _task_param_profiles(tasks: list[dict]) -> set[str]:
    profiles: set[str] = set()
    for task in tasks:
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        for key in ("evidence_profile", "comparison_data_profile", "budget_profile"):
            value = str(params.get(key) or "").strip()
            if value:
                profiles.add(value)
        if str(params.get("evidence_focus") or "").strip().lower() == "valuation":
            profiles.add(VALUATION_COMPARE_LIGHT_PROFILE)
    return profiles


def _infer_market_from_ticker(ticker: str) -> str | None:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return None
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "US"


def _infer_market_from_subject(subject: dict | None) -> str | None:
    if not isinstance(subject, dict):
        return None
    tickers = subject.get("tickers")
    if not isinstance(tickers, list):
        return None
    for ticker in tickers:
        if not isinstance(ticker, str):
            continue
        inferred = _infer_market_from_ticker(ticker)
        if inferred:
            return inferred
    return None


def _ready_understanding_tasks(state: GraphState) -> list[dict]:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        tasks = project_v2_tasks_to_legacy(state.get("understanding_v2"))
    if not isinstance(tasks, list):
        return []
    ready: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "ready").strip().lower()
        if status == "blocked":
            continue
        ready.append(task)
    return ready


def _state_contains_url_reference(state: GraphState, ui_context: dict) -> bool:
    query = str(state.get("query") or "")
    if re.search(r"https?://[^\s<>\]\)\"']+", query, re.IGNORECASE):
        return True
    raw_selections = ui_context.get("selections")
    if not raw_selections and isinstance(ui_context.get("selection"), dict):
        raw_selections = [ui_context["selection"]]
    if not isinstance(raw_selections, list):
        return False
    for item in raw_selections:
        if isinstance(item, dict) and str(item.get("url") or "").startswith(("http://", "https://")):
            return True
    return False


def _task_operation_name(task: dict) -> str:
    operation = task.get("operation")
    if isinstance(operation, dict):
        name = operation.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "qa"


def _task_subject_type(task: dict) -> str:
    value = task.get("subject_type")
    return str(value).strip().lower() if isinstance(value, str) and value.strip() else "unknown"


def _has_ready_operation(tasks: list[dict], operation_name: str) -> bool:
    target = str(operation_name or "").strip().lower()
    if not target:
        return False
    return any(_task_operation_name(task).strip().lower() == target for task in tasks)


def _operation_params(operation: object) -> dict:
    if isinstance(operation, dict) and isinstance(operation.get("params"), dict):
        return operation.get("params") or {}
    return {}


def _required_evidence_from_state(
    *,
    intent_contract: dict,
    operation: object,
    ready_tasks: list[dict],
) -> list[str]:
    required: list[str] = []
    contract_required = intent_contract.get("required_evidence") if isinstance(intent_contract, dict) else []
    if isinstance(contract_required, list):
        required.extend(str(item) for item in contract_required if str(item).strip())
    op_required = _operation_params(operation).get("required_evidence")
    if isinstance(op_required, list):
        required.extend(str(item) for item in op_required if str(item).strip())
    for task in ready_tasks:
        task_operation = task.get("operation")
        task_required = _operation_params(task_operation).get("required_evidence")
        if isinstance(task_required, list):
            required.extend(str(item) for item in task_required if str(item).strip())
        task_params = task.get("params")
        if isinstance(task_params, dict) and isinstance(task_params.get("required_evidence"), list):
            required.extend(str(item) for item in task_params.get("required_evidence") if str(item).strip())
    return canonical_evidence_kinds(required)


def _request_frames_from_state(state: GraphState) -> list[dict]:
    frames: list[dict] = []
    raw_frames = state.get("request_frames")
    if isinstance(raw_frames, list):
        frames.extend(item for item in raw_frames if isinstance(item, dict))
    raw_frame = state.get("request_frame")
    if isinstance(raw_frame, dict) and raw_frame not in frames:
        frames.append(raw_frame)
    return frames


def _request_frame_evidence_from_state(state: GraphState) -> list[str]:
    required: list[str] = []
    for frame in _request_frames_from_state(state):
        raw = frame.get("evidence_obligations")
        if isinstance(raw, list):
            required.extend(str(item) for item in raw if str(item).strip())
    return canonical_evidence_kinds(required)


def _request_frame_results_from_state(state: GraphState) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for frame in _request_frames_from_state(state):
        raw_results = frame.get("required_results")
        if isinstance(raw_results, list):
            for item in raw_results:
                value = str(item or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                results.append(value)
        workflow_action = frame.get("workflow_action")
        if isinstance(workflow_action, dict) and isinstance(workflow_action.get("required_results"), list):
            for item in workflow_action.get("required_results") or []:
                value = str(item or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                results.append(value)
    return results


def _infer_market_from_task(task: dict, fallback: str) -> str:
    tickers = task.get("tickers")
    if isinstance(tickers, list):
        for ticker in tickers:
            if not isinstance(ticker, str):
                continue
            inferred = _infer_market_from_ticker(ticker)
            if inferred:
                return inferred
    return fallback
