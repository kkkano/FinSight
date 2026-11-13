"""h12真实双producer输出：索引和正文的返回顺序不应改变最终证据。"""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

import pytest

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.nodes.analyze import analyze
from backend.graph.nodes.render_node import render_node
from backend.research.filing_evidence import disclosure_sections, filing_identity, merge_filing_evidence


def _fixture():
    return json.loads(Path(__file__).with_name("fixtures").joinpath("h12_crm_filing_producers.json").read_text(encoding="utf-8"))


def _state(order):
    fixture = _fixture()
    requirements = [{"requirement_id": f"filing:{dimension}", "kind": "explanation", "dimension": dimension,
                     "description": description, "evidence_kinds": ["filing_context"], "requires_analysis": True}
                    for dimension, description in (("business_model", "说明披露中的业务模式"), ("competition", "说明披露中的竞争因素"))]
    task = {"id": "task_1", "title": "CRM公告正文", "request_text": "说明CRM的业务模式与竞争因素，引用实际披露正文。", "subject_label": "CRM", "subject_type": "company", "tickers": ["CRM"], "operation": {"name": "qa"}, "order_index": 0, "priority": 0,
            "request_frame_id": "frame", "render_group_id": "frame", "render_kind": "single", "required_evidence": ["filing_context"], "answer_requirements": requirements}
    state = {"query": task["request_text"], "subject": {"subject_type": "company", "tickers": ["CRM"]}, "output_mode": "chat", "understanding": {"route": "research"}, "operation": task["operation"], "tasks": [task], "trace": {},
             "plan_ir": {"tasks": [task], "steps": fixture["plan_steps"]}, "artifacts": {"step_results": {step_id: {"output": fixture["step_outputs"][step_id]} for step_id in order}}}
    normalize_execution_evidence(state=state, plan_ir=state["plan_ir"], artifacts=state["artifacts"])
    return state


@pytest.fixture(autouse=True)
def _no_external_calls(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")


@pytest.mark.asyncio
async def test_real_index_and_body_outputs_reach_analysis_and_render_identically_in_both_orders(monkeypatch):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    prompts, final_indexes, rendered_texts = [], [], []

    async def select(**kwargs):
        payload = json.loads(kwargs["prompt"].split("\n", 1)[1])
        prompts.append(payload)
        by_section = {section: next(row["id"] for row in payload["evidence"] if row["data"].get("content_sections", {}).get(section)) for section in ("business", "competition")}
        return kwargs["schema"].model_validate({"claim_ids": [], "direction_supporting_claim_ids": [], "explanations": [
            {"text": "公司以企业客户订阅及支持服务为业务基础。", "evidence_ids": [by_section["business"]], "dimension": "business_model", "requirement_ids": ["filing:business_model"]},
            {"text": "竞争格局要求结合产品能力与客户需求判断。", "evidence_ids": [by_section["competition"]], "dimension": "competition", "requirement_ids": ["filing:competition"]},
        ]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    for order in (("s15", "s7"), ("s7", "s15")):
        state = _state(order)
        pool = state["artifacts"]["evidence_pool"]
        assert len(pool) == 6
        body_rows = [row for row in pool if disclosure_sections(row["structured_data"])]
        assert len(body_rows) == 2
        assert all(row["step_id"] == "s7" and row["subject"] == "CRM" for row in body_rows)
        assert all(row["step_ids"] == ["s15", "s7"] and len(row["source_ids"]) == 2 for row in body_rows)
        analyzed = await analyze(state)
        rendered = render_node({**state, **analyzed})
        research = rendered["artifacts"]["research_result"]
        rows = {row["structured_data"]["accession_number"]: row for row in research["evidence_index"].values()}
        annual = rows["0001108524-26-000060"]
        quarterly = rows["0001108524-26-000190"]
        assert annual["structured_data"]["content_read"] is True
        original = {row["accession_number"]: row for row in json.loads(_fixture()["step_outputs"]["s7"])["filings"]}
        assert annual["structured_data"]["content_sections"]["business"] == original["0001108524-26-000060"]["content_sections"]["business"]
        assert quarterly["structured_data"]["content_sections"]["management_discussion"] == original["0001108524-26-000190"]["content_sections"]["management_discussion"]
        assert quarterly["metadata"]["step_ids"] == ["s15", "s7"]
        assert len(quarterly["metadata"]["source_ids"]) == 2
        assert all(check["status"] == "answered" for check in research["task_results"][0]["requirement_results"])
        markdown = rendered["artifacts"]["draft_markdown"]
        assert "已读取业务、竞争、管理层讨论正文" in markdown
        assert "公司以企业客户订阅及支持服务为业务基础" in markdown
        assert "竞争格局尚无可展示" not in markdown
        assert "该来源为公告索引" not in markdown
        final_indexes.append(rows)
        rendered_texts.append(markdown)
    assert final_indexes[0] == final_indexes[1]
    assert rendered_texts[0] == rendered_texts[1]
    assert prompts[0] == prompts[1]


@pytest.mark.parametrize("changed", [{"subject": "MSFT"}, {"report_date": "2026-04-30"}, {"accession_number": "0001108524-26-000127"}])
def test_same_url_with_different_subject_or_filing_identity_is_not_merged(changed):
    state = _state(("s15", "s7"))
    original = next(row for row in state["artifacts"]["evidence_pool"] if row.get("content_read"))
    other = copy.deepcopy(original)
    if "subject" in changed:
        other["subject"] = changed["subject"]
    else:
        other["structured_data"].update(changed)
    assert filing_identity(original) != filing_identity(other)
    fresh = {"artifacts": {"evidence_pool": [original, other]}, "plan_ir": {"steps": []}}
    normalize_execution_evidence(state=fresh, plan_ir=fresh["plan_ir"], artifacts=fresh["artifacts"])
    assert len(fresh["artifacts"]["evidence_pool"]) == 2
    with pytest.raises(ValueError, match="filing_evidence_identity_mismatch"):
        merge_filing_evidence(original, other)


def test_same_filing_preserves_complementary_body_sections_without_mutating_producers():
    state = _state(("s15", "s7"))
    original = next(row for row in state["artifacts"]["evidence_pool"] if "business" in row.get("content_sections", {}))
    left, right = copy.deepcopy(original), copy.deepcopy(original)
    left["content_sections"] = {"business": original["content_sections"]["business"]}
    left["structured_data"]["content_sections"] = dict(left["content_sections"])
    right["content_sections"] = {"competition": original["content_sections"]["competition"]}
    right["structured_data"]["content_sections"] = dict(right["content_sections"])
    forward = merge_filing_evidence(left, right)
    backward = merge_filing_evidence(right, left)
    assert forward == backward
    assert set(forward["content_sections"]) == {"business", "competition"}
    assert set(left["content_sections"]) == {"business"} and set(right["content_sections"]) == {"competition"}
