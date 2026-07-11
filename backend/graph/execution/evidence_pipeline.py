# -*- coding: utf-8 -*-
"""Execution result normalization into task-scoped evidence."""
from __future__ import annotations

import json
import os
from typing import Any

from backend.graph.execution.evidence_tools import append_tool_evidence
from backend.graph.request_task_contract import build_tool_diagnostic, output_is_error_like
from backend.graph.state import GraphState


def normalize_execution_evidence(
    *,
    state: GraphState,
    plan_ir: dict[str, Any],
    artifacts: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    # Phase 4: build a unified evidence_pool from selection (ephemeral, request-scoped).
    subject = state.get("subject") or {}
    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    evidence_pool: list[dict[str, Any]] = []
    existing_evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts, dict) else None
    if isinstance(existing_evidence_pool, list):
        evidence_pool.extend([dict(item) for item in existing_evidence_pool if isinstance(item, dict)])
    tool_diagnostics: list[dict[str, Any]] = []

    def _clean_strings(value: Any) -> list[str]:
        values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for raw in values:
            cleaned = str(raw or "").strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    def _clean_urls(value: Any) -> list[str]:
        return [
            url.rstrip(".,，。；;!?！？")
            for url in _clean_strings(value)
            if url.startswith(("http://", "https://"))
        ]

    def _collect_selection_identity(
        value: Any,
        *,
        include_plain_id: bool = True,
    ) -> tuple[set[str], set[str]]:
        ids: set[str] = set()
        urls: set[str] = set()
        if isinstance(value, list):
            for item in value:
                nested_ids, nested_urls = _collect_selection_identity(
                    item,
                    include_plain_id=include_plain_id,
                )
                ids.update(nested_ids)
                urls.update(nested_urls)
            return ids, urls
        if not isinstance(value, dict):
            return ids, urls
        ids.update(_clean_strings(value.get("selection_ids")))
        ids.update(_clean_strings(value.get("selection_id")))
        if include_plain_id:
            ids.update(_clean_strings(value.get("id")))
        for key in ("url", "link", "article_url", "final_url", "urls"):
            urls.update(_clean_urls(value.get(key)))
        for key in ("selection", "selections", "selection_payload"):
            nested_ids, nested_urls = _collect_selection_identity(value.get(key))
            ids.update(nested_ids)
            urls.update(nested_urls)
        return ids, urls

    def _task_candidates() -> list[dict[str, Any]]:
        tasks_by_id: dict[str, dict[str, Any]] = {}
        understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
        sources = [
            plan_ir.get("tasks") if isinstance(plan_ir, dict) else None,
            understanding.get("tasks"),
            state.get("tasks"),
        ]
        for source_tasks in sources:
            if not isinstance(source_tasks, list):
                continue
            for task in source_tasks:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("id") or "").strip()
                if not task_id:
                    continue
                tasks_by_id[task_id] = {**tasks_by_id.get(task_id, {}), **task}
        return list(tasks_by_id.values())

    selection_tasks = _task_candidates()

    def _selection_task_ids(item: dict[str, Any]) -> list[str]:
        direct_task_ids = _clean_strings(item.get("task_ids"))
        direct_task_ids.extend(
            task_id
            for task_id in _clean_strings(item.get("task_id"))
            if task_id not in direct_task_ids
        )
        matched = list(direct_task_ids)
        item_ids, item_urls = _collect_selection_identity(item)
        for task in selection_tasks:
            task_id = str(task.get("id") or "").strip()
            if not task_id or task_id in matched:
                continue
            task_ids, task_urls = _collect_selection_identity(task, include_plain_id=False)
            operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
            for payload in (task.get("params"), operation.get("params")):
                nested_ids, nested_urls = _collect_selection_identity(payload)
                task_ids.update(nested_ids)
                task_urls.update(nested_urls)
            if item_ids.intersection(task_ids) or item_urls.intersection(task_urls):
                matched.append(task_id)
        if not matched and len(selection_tasks) == 1:
            subject_ids, subject_urls = _collect_selection_identity(subject)
            if item_ids.intersection(subject_ids) or item_urls.intersection(subject_urls):
                matched.append(str(selection_tasks[0].get("id") or "").strip())
        return [task_id for task_id in matched if task_id]

    if isinstance(selection_payload, list) and selection_payload:
        for item in selection_payload:
            if not isinstance(item, dict):
                continue
            evidence_pool.append(
                {
                    "title": item.get("title") or item.get("headline") or "",
                    "url": item.get("url"),
                    "snippet": item.get("snippet") or item.get("summary"),
                    "source": item.get("source") or "selection",
                    "published_date": item.get("ts") or item.get("datetime") or item.get("published_at"),
                    "confidence": item.get("confidence", 0.7),
                    "type": item.get("type") or "selection",
                    "id": item.get("id"),
                    "task_ids": _selection_task_ids(item),
                }
            )

    # Phase 4.2+: merge tool outputs into evidence_pool (best-effort normalization).
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else None
    step_index = {s.get("id"): s for s in (steps or []) if isinstance(s, dict) and s.get("id")}

    def _step_task_ids(step: dict[str, Any]) -> list[str]:
        raw = step.get("task_ids")
        values = raw if isinstance(raw, list) else []
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            task_id = str(value or "").strip()
            if task_id and task_id not in seen:
                seen.add(task_id)
                result.append(task_id)
        single = str(step.get("task_id") or "").strip()
        if single and single not in seen:
            result.insert(0, single)
        return result

    jina_enrich_enabled = str(os.getenv("JINA_ENRICH_EVIDENCE", "true")).strip().lower() in {"1", "true", "yes", "on"}

    def _maybe_enrich_snippet_from_jina(url: str | None, snippet: Any) -> Any:
        if not jina_enrich_enabled:
            return snippet
        target = str(url or "").strip()
        snippet_text = str(snippet or "").strip()
        if not target.startswith(("http://", "https://")):
            return snippet
        if len(snippet_text) >= 80:
            return snippet
        if "news.google.com" in target:
            return snippet
        try:
            from backend.tools.jina_reader import fetch_via_jina
        except Exception:
            return snippet
        try:
            jina_text = fetch_via_jina(target)
            if jina_text and len(jina_text) > len(snippet_text):
                return jina_text[:800]
        except Exception:
            return snippet
        return snippet

    def _append_agent_evidence(agent_name: str, step_id: str, output: Any) -> None:
        if output is None:
            return
        if isinstance(output, dict) and output.get("skipped"):
            return

        if isinstance(output, str):
            try:
                output = json.loads(output)
            except Exception:
                output = {"summary": output}

        if not isinstance(output, dict):
            evidence_pool.append(
                {
                    "title": f"{agent_name} output",
                    "url": None,
                    "snippet": str(output)[:800],
                    "source": agent_name,
                    "published_date": None,
                    "confidence": 0.5,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}",
                }
            )
            return

        summary = output.get("summary")
        confidence_base = output.get("confidence", 0.6)
        as_of = output.get("as_of")

        if isinstance(summary, str) and summary.strip():
            evidence_pool.append(
                {
                    "title": f"{agent_name} summary",
                    "url": None,
                    "snippet": summary.strip()[:800],
                    "source": agent_name,
                    "published_date": as_of,
                    "confidence": confidence_base if isinstance(confidence_base, (int, float)) else 0.6,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}:summary",
                }
            )

        evidence = output.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return

        for i, item in enumerate(evidence[:10]):
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            snippet = item.get("text") or item.get("snippet") or item.get("summary")
            if not snippet:
                continue
            url = item.get("url")
            snippet = _maybe_enrich_snippet_from_jina(url, snippet)
            source = item.get("source") or agent_name
            evidence_pool.append(
                {
                    "title": item.get("title") or f"{agent_name} evidence {i+1}",
                    "url": url,
                    "snippet": str(snippet).strip()[:800],
                    "source": source,
                    "published_date": item.get("timestamp") or as_of,
                    "confidence": item.get("confidence", confidence_base if isinstance(confidence_base, (int, float)) else 0.6),
                    "type": "agent",
                    "id": item.get("id") or f"{agent_name}:{step_id}:{i+1}",
                }
            )

    if isinstance(step_results, dict) and step_results:
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") != "tool":
                if step.get("kind") == "agent":
                    agent_name = step.get("name") or ""
                    if agent_name:
                        before_count = len(evidence_pool)
                        _append_agent_evidence(str(agent_name), str(step_id), item.get("output"))
                        for evidence in evidence_pool[before_count:]:
                            if isinstance(evidence, dict):
                                evidence["step_id"] = str(step_id)
                                evidence["task_ids"] = _step_task_ids(step)
                continue
            tool_name = step.get("name") or ""
            if not tool_name:
                continue
            output = item.get("output")
            if output_is_error_like(output):
                tool_diagnostics.append(
                    build_tool_diagnostic(
                        tool_name=str(tool_name),
                        step_id=str(step_id),
                        task_ids=_step_task_ids(step),
                        output=output,
                    )
                )
                continue
            before_count = len(evidence_pool)
            append_tool_evidence(evidence_pool, str(tool_name), str(step_id), output)
            for evidence in evidence_pool[before_count:]:
                if isinstance(evidence, dict):
                    evidence["step_id"] = str(step_id)
                    evidence["task_ids"] = _step_task_ids(step)

    # 按 URL、显式 ID 或内容去重，并合并 task / step provenance。
    def _provenance_values(item: dict[str, Any], plural: str, singular: str) -> list[str]:
        raw_values = item.get(plural) if isinstance(item.get(plural), list) else []
        values = [str(value or "").strip() for value in raw_values if str(value or "").strip()]
        single = str(item.get(singular) or "").strip()
        if single and single not in values:
            values.insert(0, single)
        return values

    def _dedupe_key(item: dict[str, Any]) -> str:
        url = str(item.get("url") or "").strip()
        if url:
            return f"url:{url}"
        explicit_id = str(item.get("id") or item.get("source_id") or "").strip()
        if explicit_id:
            return f"id:{explicit_id}"
        content = (
            item.get("snippet")
            or item.get("summary")
            or item.get("text")
            or item.get("content")
            or item.get("description")
            or ""
        )
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
        return "content:{title}|{source}|{content}|{published}".format(
            title=str(item.get("title") or item.get("headline") or "").strip(),
            source=str(item.get("source") or "").strip(),
            content=content.strip(),
            published=str(item.get("published_date") or item.get("published_at") or "").strip(),
        )

    seen: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for raw_evidence in evidence_pool:
        if not isinstance(raw_evidence, dict):
            continue
        e = dict(raw_evidence)
        key = _dedupe_key(e)
        existing = seen.get(key)
        if existing is not None:
            for plural, singular in (("task_ids", "task_id"), ("step_ids", "step_id")):
                merged = _provenance_values(existing, plural, singular)
                for value in _provenance_values(e, plural, singular):
                    if value not in merged:
                        merged.append(value)
                if merged:
                    existing[plural] = merged
            continue
        task_ids = _provenance_values(e, "task_ids", "task_id")
        step_ids = _provenance_values(e, "step_ids", "step_id")
        if task_ids:
            e["task_ids"] = task_ids
        if step_ids:
            e["step_ids"] = step_ids
        seen[key] = e
        deduped.append(e)
    artifacts["evidence_pool"] = deduped
    evidence_by_task: dict[str, list[dict[str, Any]]] = {}
    for evidence in deduped:
        task_ids = evidence.get("task_ids") if isinstance(evidence, dict) else None
        for task_id in [str(value or "").strip() for value in (task_ids if isinstance(task_ids, list) else [])]:
            if not task_id:
                continue
            evidence_by_task.setdefault(task_id, []).append(dict(evidence))
    artifacts["evidence_by_task"] = evidence_by_task
    if tool_diagnostics:
        artifacts["tool_diagnostics"] = tool_diagnostics

    # Phase P0-3c: collect per-agent fallback diagnostics into artifacts
    # so synthesize/render can surface degradation info to the user.
    agent_diagnostics: dict[str, dict[str, Any]] = {}
    if isinstance(step_results, dict):
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") != "agent":
                continue
            agent_name = step.get("name") or step_id
            output = item.get("output")
            if not isinstance(output, dict):
                continue
            diag: dict[str, Any] = {
                "status": output.get("status", "unknown"),
                "duration_ms": output.get("duration_ms"),
            }
            fallback_reason = output.get("fallback_reason")
            if fallback_reason:
                diag["fallback_reason"] = fallback_reason
                diag["retryable"] = output.get("retryable", False)
                diag["error_stage"] = output.get("error_stage", "unknown")
            agent_diagnostics[str(agent_name)] = diag
    if agent_diagnostics:
        artifacts["agent_diagnostics"] = agent_diagnostics

    return deduped, step_index, len(evidence_pool)
