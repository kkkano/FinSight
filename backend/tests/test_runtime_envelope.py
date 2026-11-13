"""信封的结果协议和预算合同；合成值只用于单元测试，不是市场录制。"""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from backend.agent_runtime.adapters import adapt_result
from backend.agent_runtime.context import tokens
from backend.agent_runtime.envelope import Source, ToolError, ToolResult, to_model, to_ui


@pytest.mark.parametrize("kind", ["quote", "series", "table", "news", "document", "computation", "chart", "control"])
def test_every_registered_kind_roundtrips_without_changing_payload(kind):
    data = {"protocol_sample": True, "rows": [{"value": None}, {"value": -12.125}]}
    result = ToolResult(status="ok", kind=kind, data=data, sources=[Source(title="协议样本来源")])
    restored = ToolResult.model_validate_json(result.model_dump_json())
    assert restored.data == data and restored.sources[0].title == "协议样本来源"
    assert restored.kind == kind


def test_error_requires_structured_error_and_ok_cannot_carry_one():
    with pytest.raises(ValidationError):
        ToolResult(status="error", kind="quote")
    with pytest.raises(ValidationError):
        ToolResult(status="ok", kind="quote", error=ToolError(code="fixture_error", user_message="协议样本", retryable=False))


def test_result_collections_are_not_shared_between_instances():
    first = ToolResult(status="ok", kind="control")
    second = ToolResult(status="ok", kind="control")
    first.notes.append("协议样本")
    first.sources.append(Source(title="协议来源"))
    assert second.notes == second.sources == []


@pytest.mark.parametrize("budget", [1, 10, 64, 300, 1000])
@pytest.mark.parametrize("kind", ["quote", "series", "table", "news", "document", "computation", "chart", "control"])
def test_model_projection_never_exceeds_the_token_budget(kind, budget):
    data = {"rows": [{"value": index, "description": "协议预算样本" * 30} for index in range(40)],
            "content": "协议正文。\n" * 400, "currency": "fixture-unit"}
    result = ToolResult(status="ok", kind=kind, data=data, notes=["协议备注"])
    before = deepcopy(result.model_dump())
    text = to_model(result, budget, handle="arbitrary_data_ref", source_ids=[1])
    assert tokens(text) <= budget
    assert result.model_dump() == before


def test_long_table_has_real_counts_and_recoverable_handle():
    result = ToolResult(status="ok", kind="series", data={"rows": [{"time": str(i), "close": i + 0.125} for i in range(100)]})
    text = to_model(result, 300, handle="dataset_original")
    assert "共 100 行" in text and "已显示" in text
    assert "dataset_original" in text and "read_data" in text
    assert len(result.data["rows"]) == 100


def test_table_headers_keep_declared_units_and_original_signed_values():
    result = ToolResult(status="ok", kind="table", data={"rows": [{"eps": -1.25, "revenue": 12.125}],
                         "column_units": {"eps": "USD/shares", "revenue": "USD"}})
    text = to_model(result, 300)
    assert "eps (USD/shares)" in text and "revenue (USD)" in text
    assert "-1.25" in text and "12.125" in text
    assert result.data["rows"] == [{"eps": -1.25, "revenue": 12.125}]


def test_integer_and_legacy_source_numbers_are_preserved():
    result = ToolResult(status="ok", kind="document", data="协议正文", sources=[Source(title="来源一"), Source(title="来源二")])
    text = to_model(result, 300, source_ids=[1, "Slegacy"])
    assert "[1]" in text and "[Slegacy]" in text


@pytest.mark.parametrize("budget", [64, 300, 1000])
def test_document_read_cursor_advances_only_by_delivered_chinese_characters(budget):
    content = '中文原文包含"引号"与换行。\n' * 400
    raw = {"content": content, "offset": 137, "total_chars": len(content) + 1000,
           "next_offset": 137 + len(content), "has_more": True, "data_ref": "original_document"}
    result = ToolResult(status="ok", kind="document", data=deepcopy(raw))
    text = to_model(result, budget, handle="original_document")
    payload = json.loads(text.split("\n\n")[-1])
    assert payload["content"] == content[:len(payload["content"])]
    assert payload["next_offset"] == 137 + len(payload["content"])
    assert payload["has_more"] == (payload["next_offset"] < raw["total_chars"])
    assert payload["next_offset"] < raw["next_offset"]
    assert tokens(text) <= budget and result.data == raw


def test_complete_document_page_preserves_cursor_without_extra_truncation():
    raw = {"content": "最后一页。", "offset": 12, "total_chars": 17, "next_offset": 17, "has_more": False}
    result = ToolResult(status="ok", kind="document", data=deepcopy(raw))
    payload = json.loads(to_model(result, 300).split("\n\n")[-1])
    assert payload == raw and result.data == raw


def test_error_projection_does_not_display_untrusted_exception_payload():
    result = adapt_result("get_stock_price", {"status": "error", "error_code": "tool_provider_error", "message": "provider-secret-detail"})
    assert "provider-secret-detail" not in to_model(result, 300)
    assert "provider-secret-detail" not in str(to_ui(result, name="get_stock_price"))


def test_ui_projection_exposes_kind_true_counts_and_bounded_rows():
    result = ToolResult(status="ok", kind="table", data={"rows": [{"value": i} for i in range(12)]})
    display = to_ui(result, name="render_table", arguments={"ticker": "FIXTURE"})
    assert display["kind"] == "table" and display["target"] == "FIXTURE"
    assert display["row_count"] == 12 and display["returned_rows"] == 6 and display["has_more"] is True
    assert len(result.data["rows"]) == 12


def test_control_labels_and_quote_fields_are_public_chinese_labels():
    control = to_ui(ToolResult(status="ok", kind="control", data={}), name="update_plan")
    assert control["title"] == "更新研究计划"
    quote = to_ui(ToolResult(status="ok", kind="quote", data={"data": {"price": 12.5, "currency": "fixture-unit"}}), name="get_quote")
    assert quote["title"] == "获取行情"
    assert {item["label"] for item in quote["key_facts"]} == {"价格", "货币"}
