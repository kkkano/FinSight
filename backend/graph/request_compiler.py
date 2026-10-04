"""请求理解的唯一出口：由已绑定的任务生成执行与展示共用的合同。"""
from __future__ import annotations

import re
from typing import Any

from backend.config.ticker_mapping import normalize_ticker
from backend.graph.request_frame import compile_request_frame, compile_request_frames
from backend.graph.request_constraints import conditional_impact


def finalize_request_contract(result: dict[str, Any]) -> dict[str, Any]:
    understanding = dict(result.get("understanding") or {})
    ready = [dict(item) for item in result.get("tasks", understanding.get("tasks", [])) if isinstance(item, dict)]
    blocked = [dict(item) for item in result.get("blocked_tasks", understanding.get("blocked_tasks", [])) if isinstance(item, dict)]
    if not ready and not blocked:
        return result
    query = str(understanding.get("original_query") or result.get("query") or "")
    # 同一条件传导链不能拆成失去前提的两次宏观分析；独立公司任务保持各自边界。
    chain = [task for task in ready if task.get('subject_type') in {'macro','commodity','index'}]
    if len(chain) > 1 and conditional_impact(query) and not re.search(r'另外|另一个问题|\bseparately\b', query, re.I):
        lead = chain[0]
        lead['request_text'] = query
        lead['conditional_impact'] = True
        lead['tickers'] = list(dict.fromkeys(ticker for task in chain for ticker in task.get('tickers', [])))
        ready = [task for task in ready if task is lead or task not in chain]
    mode = str(result.get("output_mode") or "chat")
    all_tickers = list(dict.fromkeys(
        normalize_ticker(str(ticker)) for task in ready for ticker in task.get("tickers", [])
        if normalize_ticker(str(ticker))
    ))
    fragments = compile_request_frames(query=query, tickers=all_tickers, output_mode=mode)
    frames: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for order, task in enumerate([*ready, *blocked]):
        task_id = str(task.get("id") or f"task_{order + 1}")
        if task_id in seen_ids:
            raise ValueError("duplicate_request_task_id")
        seen_ids.add(task_id)
        tickers = list(dict.fromkeys(normalize_ticker(str(value)) for value in task.get("tickers", []) if value))
        subject_type = str(task.get("subject_type") or "unknown")
        previous = task.get("operation") if isinstance(task.get("operation"), dict) else {"name": str(task.get("operation") or "qa")}
        name = str(previous.get("name") or "qa")
        params = dict(previous.get("params") or {})
        scoped_query = str(task.get("request_text") or query)
        # 分句仅由 request_frame 编译器解释；不按相似度猜测任务身份。
        if len(all_tickers) > 1 and len(tickers) == 1 and name != "compare":
            candidates = [frame for frame in fragments if set(frame.get("subject", {}).get("tickers", [])) == set(tickers)]
            matching = [frame for frame in candidates if frame.get("legacy_operation", {}).get("name") == name]
            candidates = matching or candidates
            if candidates:
                scoped_query = "；".join(str(frame["query_text"]) for frame in candidates)
        elif subject_type == "macro" and not task.get('conditional_impact'):
            candidates = [frame for frame in fragments if frame.get("subject", {}).get("type") == "macro"]
            if candidates:
                scoped_query = "；".join(str(frame["query_text"]) for frame in candidates)
        frame_id = f"request_{task_id}"
        domain = {"price": "quote", "fetch": "news", "technical": "technical", "macro_brief": "macro"}.get(name, "")
        if subject_type == "macro":
            domain = "macro"
        frame = compile_request_frame(query=scoped_query, tickers=tickers, output_mode=mode,
            comparison_requested=name == "compare", domain_intent=domain,
            subject_type=subject_type, frame_id=frame_id)
        frame["task_ids"] = [task_id]
        frame["subject"]["label"] = str(task.get("subject_label") or ", ".join(tickers) or subject_type)
        contract = frame["intent_contract"]
        if task.get("reason") == "intent_contract_per_ticker_evidence":
            parent = next((item for item in frames if item["render_contract"].get("shape") == "compare"
                           and set(tickers) <= set(item["subject"].get("tickers", []))), None)
            if parent:
                for key in ("required_evidence", "facets", "budget_profile", "evidence_plan"):
                    contract[key] = parent["intent_contract"][key]
                frame["evidence_obligations"] = list(contract["required_evidence"])
                # 比较的逐标的任务仅准备事实；双方解释由父任务一次完成。
                task["evidence_support_for"] = parent["task_ids"][0]
                frame["evidence_support_for"] = parent["task_ids"][0]
                for requirement in frame["render_contract"].get("answer_requirements") or []:
                    requirement["requires_analysis"] = False
                    requirement["kind"] = "fact_attribute"
        projection = dict(frame["legacy_operation"])
        # 文档/持仓及估值计算是显式工作流变体，其证据仍由同一 frame 管理。
        if name in {"holdings", "valuation_sanity"} or subject_type in {"filing", "research_doc", "news_item", "news_set", "portfolio"}:
            projection["name"] = name
            frame["render_contract"]["variant"] = name
        projection["params"] = {**params, **dict(projection.get("params") or {}),
            "required_evidence": list(frame["evidence_obligations"]),
            "facets": list(contract.get("facets") or []), "intent_contract_id": contract["contract_id"],
            "budget_profile": contract.get("budget_profile", "default")}
        projection.setdefault("confidence", previous.get("confidence", 0.75))
        frame["legacy_operation"] = projection
        render_kind = "compare" if frame["render_contract"].get("shape") == "compare" else "single"
        task.update(id=task_id, tickers=tickers, request_text=scoped_query, operation=projection,
            title=str(task.get("title") or frame["subject"]["label"]),
            subject_label=frame["subject"]["label"], order_index=order, request_frame_id=frame_id,
            render_kind=render_kind, render_group_id=frame_id,
            answer_requirements=list(frame["render_contract"].get("answer_requirements") or []),
            required_evidence=list(frame["evidence_obligations"]))
        if frame.get("time_scope"):
            task["time_scope"] = dict(frame["time_scope"])
        task["priority"] = max(0, int(task.get("priority", 50)))
        if order >= len(ready):
            frame["lane"] = "clarify"
            task.setdefault("error_code", str(task.get("reason") or "task_blocked"))
        frames.append(frame)
    contracts = [frame["intent_contract"] for frame in frames]
    understanding.update(tasks=ready, blocked_tasks=blocked, request_frames=frames)
    trace = dict(result.get("trace") or {})
    trace.update(request_frames=frames, intent_contracts=contracts,
        request_compiler={"version": "request_compiler.v1", "task_count": len(ready), "blocked_count": len(blocked)})
    result.update(understanding=understanding, tasks=ready, blocked_tasks=blocked,
        request_frames=frames, intent_contracts=contracts, trace=trace)
    if frames:
        result["request_frame"] = understanding["request_frame"] = trace["request_frame"] = frames[0]
        result["intent_contract"] = trace["intent_contract"] = contracts[0]
    if ready:
        result["operation"] = ready[0]["operation"]
    return result
