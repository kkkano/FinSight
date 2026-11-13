"""只读分页、完整原件绑定及最终提交合同；不作为真实模型质量评分。"""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("paged_eval", Path(__file__).with_name("paged_judge.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def payload(value):
    return {"case": {"id": "fixture"}, "answers": [], "recordings": [{"tool": "fixture", "arguments": {}, "result": value}]}


def test_unicode_pages_reconstruct_all_original_content_and_byte_ranges(tmp_path):
    original = "中文财务证据￥🙂" * 5000
    reader = module.ReadOnlyEvidence(payload(original), tmp_path / "original.json")
    cursor, fragments, byte_ranges = 0, [], []
    while True:
        page = reader.read(path=["recordings", 0, "result"], cursor=cursor, max_chars=15000)
        fragments.append(page["value"])
        byte_ranges.append(page["utf8_byte_range"])
        assert len(page["value"].encode()) <= 8192
        assert page["node_sha256"] == module.digest(original)
        assert page["range"]["start"] == cursor
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert "".join(fragments) == original
    assert byte_ranges[0]["start"] == 0 and byte_ranges[-1]["end"] == len(original.encode())
    assert all(a["end"] == b["start"] for a, b in zip(byte_ranges, byte_ranges[1:]))


def test_large_children_are_references_not_silently_truncated_values(tmp_path):
    data = {"large": "大" * 50000, "small": 42}
    reader = module.ReadOnlyEvidence(payload(data), tmp_path / "original.json")
    page = reader.read(path=["recordings", 0, "result"])
    large = next(item for item in page["items"] if item["key"] == "large")
    assert large["value_materialized"] is False and "value" not in large
    child = reader.read(**large["read_child_arguments"])
    assert child["value"] == data["large"][:child["next_cursor"]]
    assert child["has_more"] is True
    assert next(item for item in page["items"] if item["key"] == "small")["value"] == 42


def test_json_string_view_keeps_original_binding_and_correct_child_arguments(tmp_path):
    original = json.dumps({"rows": [{"revenue": 42}] * 5000})
    reader = module.ReadOnlyEvidence(payload(original), tmp_path / "original.json")
    page = reader.read(path=["recordings", 0, "result"], view="json")
    item = page["items"][0]
    assert item["read_child_arguments"] == {"path": ["recordings", 0, "result"], "view": "json", "decoded_path": ["rows"]}
    data = reader.read(**item["read_child_arguments"], limit=2)
    assert data["items"][0]["value"] == {"revenue": 42}
    assert data["original_node_sha256"] == module.digest(original)


def test_payload_mutation_and_nonstructural_paths_are_rejected(tmp_path):
    reader = module.ReadOnlyEvidence(payload({"price": 42}), tmp_path / "original.json")
    with pytest.raises((ValueError, KeyError)):
        reader.read(path=["__class__", "__globals__", "environ"])
    reader.path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen_judge_payload_changed"):
        reader.read(path=[])


def test_compaction_preserves_unseen_pages_and_recent_pairing():
    messages = [{"role": "system", "content": "固定原量表"}]
    for index in range(8):
        messages.extend([{"role": "assistant", "content": "已核验事实", "tool_calls": [{"id": f"c{index}"}]},
                         {"role": "tool", "tool_call_id": f"c{index}", "content": module.encode({
                             "receipt_id": f"read-{index}", "returned_page_sha256": "hash", "value": "原始页"})}])
    compacted = module.compact(messages, {"read-0", "read-1"})
    tools = [json.loads(item["content"]) for item in compacted if item["role"] == "tool"]
    assert "value" not in tools[0] and "value" not in tools[1]
    assert all(item["value"] == "原始页" for item in tools[2:])
    assert len(compacted) == len(messages)


class FixtureTransport:
    config = SimpleNamespace(model="independent-model", context_window=131072, max_output=256)

    def __init__(self):
        self.calls = []

    async def stream(self, messages, tools, **kwargs):
        self.calls.append((messages, tools, kwargs))
        if len(self.calls) == 1:
            name, args = "read_evidence", {"path": ["recordings", 0, "result"]}
        elif len(self.calls) == 2:
            name, args = "finish_reading", {"facts_notes": "原始price为42，已核对。"}
        else:
            name, args = "submit_score", {"answered": 2, "numbers": 2, "limitations": 1,
                "presentation": 1, "no_internal_identifiers": 1, "reasons": ["fixture协议验证。"]}
        yield {"model": self.config.model, "choices": [{"delta": {"tool_calls": [{"index": 0,
            "id": f"call-{len(self.calls)}", "function": {"name": name, "arguments": json.dumps(args)}}]}, "finish_reason": None}]}
        yield {"model": self.config.model, "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


def test_final_step_only_exposes_submit_score_and_original_reads_are_audited(tmp_path):
    transport = FixtureTransport()
    case = {"id": "fixture", "must": ["准确42"], "must_not": []}
    row = {"model": "tested-model", "turns": [{"query": "报价", "terminal": {"response": "42"}}]}
    result = asyncio.run(module.judge_with_pages(transport, case, row,
        [{"tool": "quote", "arguments": {}, "result": {"price": 42}}], tmp_path))
    assert result["total"] == 7 and result["model"] == "independent-model"
    assert result["read_receipts"][0]["delivered_to_model"] is True
    assert [tool["function"]["name"] for tool in transport.calls[-1][1]] == ["submit_score"]
    assert transport.calls[-1][2]["tool_choice"]["function"]["name"] == "submit_score"
    assert json.loads((tmp_path / "original_payload.json").read_text(encoding="utf-8"))["recordings"][0]["result"]["price"] == 42


def test_same_model_cannot_score_its_own_answer(tmp_path):
    transport = FixtureTransport()
    row = {"model": transport.config.model, "turns": []}
    with pytest.raises(ValueError, match="judge_must_differ_from_subject"):
        asyncio.run(module.judge_with_pages(transport, {"id": "fixture"}, row, [], tmp_path))
