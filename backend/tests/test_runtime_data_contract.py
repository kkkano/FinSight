"""唯一运行时的整数引用、来源继承与历史结构迁移合同。"""
import json
import time

from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import Source, ToolResult


def ledger(tmp_path, run="run"):
    data = RunData("owner", "session", run, "原始问题")
    data.storage_dir = tmp_path
    return data


def record(data, ticker="AAPL", url="https://example.test/filing"):
    raw = {"rows": [{"period": "2026Q3", "revenue": 12.34, "missing": None}]}
    envelope = ToolResult(status="ok", kind="table", data=raw, sources=[Source(title="原始申报", url=url)])
    return data.record("get_financial_statements", {"ticker": ticker}, raw, envelope=envelope)


def test_default_records_use_integer_sources_and_stable_handles(tmp_path):
    data = ledger(tmp_path)
    ref = record(data)
    assert ref.startswith("h_")
    assert data.source_refs(ref) == ["1"]
    snapshot = data.snapshot()
    assert snapshot["reference_style"] == "integer"
    assert snapshot["next_source_number"] == 2
    assert snapshot["source_links"] == {ref: ["1"]}


def test_integer_sources_follow_first_appearance_and_deduplicate(tmp_path):
    data = ledger(tmp_path)
    first = record(data)
    second = record(data, ticker="MSFT")
    third = record(data, ticker="NVDA", url="https://example.test/other")
    assert first.startswith("h_") and second != first
    assert record(data) == first
    assert data.source_refs(first) == data.source_refs(second) == ["1"]
    assert data.source_refs(third) == ["2"]
    assert list(data.sources) == ["1", "2"]


def test_new_ledger_does_not_extract_prose_urls_or_fabricate_sources(tmp_path):
    data = ledger(tmp_path)
    text = "错误：这里只是在引用报道措辞 https://example.test/not-declared"
    ref = data.record("fetch_url_content", {}, text)
    quote = data.record("get_stock_price", {}, {"price": 22, "as_of": "2026-11-12"})
    assert data.records[ref]["output"] == text
    assert data.source_refs(ref) == data.source_refs(quote) == []


def test_derived_data_inherits_existing_sources_and_original_values(tmp_path):
    data = ledger(tmp_path)
    parent = record(data)
    output = {"rows": [{"value": -0.005, "missing": None}], "source": "不得新增来源"}
    derived = data.record("run_analysis_code", {"dataset_refs": [parent]}, output)
    explicit = data.record("computed", {"source_refs": ["1"]}, {"value": 1})
    assert data.source_refs(derived) == data.source_refs(explicit) == ["1"]
    assert list(data.sources) == ["1"]
    assert data.rows(derived) == output["rows"]
    assert data.records[derived]["output"] == output


def test_save_restore_keeps_ids_handles_and_allocation_gaps(tmp_path):
    data = ledger(tmp_path)
    first = record(data)
    expired = record(data, "MSFT", "https://example.test/expired")
    data.record_expires_at[expired] = time.time() - 1
    data.save()
    restored = ledger(tmp_path, "followup")
    assert restored.restore("run")
    assert list(restored.records) == [first]
    assert restored.source_refs(first) == ["1"]
    new = record(restored, "NVDA", "https://example.test/new")
    assert restored.source_refs(new) == ["3"]
    assert not ledger(tmp_path, "wrong").restore("unknown")


def test_legacy_restore_maps_structural_refs_without_rewriting_history(tmp_path):
    old = ledger(tmp_path)
    parent, child, source = "dataset_abc123", "dataset_def456", "Sabc123"
    body = f"已披露收入 [{source}]；句柄 {parent}"
    expiry = time.time() + 3600
    # 已持久化的旧结构是测试输入；生产账本不再提供旧格式生成模式。
    payload = {
        "format": "finsight-run-data.v1", "owner": "owner", "session_id": "session", "run_id": "run", "expires_at": expiry,
        "records": {
            parent: {"tool": "get_financial_statements", "inputs": {"ticker": "AAPL"}, "status": "success",
                     "output": {"rows": [{"revenue": 12.34, "missing": None}]}},
            child: {"tool": "run_analysis_code", "inputs": {"dataset_refs": [parent]}, "status": "success",
                    "output": {"rows": [{"value": 2}], "content": body}}},
        "sources": {source: {"source_id": source, "data_ref": parent, "title": "历史申报", "url": "https://example.test/filing"}},
        "source_links": {parent: [source], child: [source]}, "record_expires_at": {parent: expiry, child: expiry},
        "artifacts": [{"artifact_id": "chart_history", "kind": "chart", "title": "历史图表", "dataset_refs": [child], "source_refs": [source]}],
    }
    path = old._path("run")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    restored = ledger(tmp_path, "new")
    assert restored.restore("run")
    new_parent, new_child = restored.handle_aliases[parent], restored.handle_aliases[child]
    assert new_parent == parent.replace("dataset_", "h_", 1)
    assert restored.records[new_child]["inputs"]["dataset_refs"] == [new_parent]
    assert restored.records[new_child]["output"]["content"] == body
    assert restored.source_aliases[source] == "1"
    assert "1" in restored.source_refs(new_child)
    assert restored.source_refs(child) == ["1"]
    assert restored.prior_artifacts[0]["dataset_refs"] == [new_child]
    assert restored.prior_artifacts[0]["source_refs"] == ["1"]
    restored.save()
    again = ledger(tmp_path, "again")
    assert again.restore("new")
    assert again.source_aliases == restored.source_aliases
    assert again.handle_aliases == restored.handle_aliases


def test_restore_new_chain_reads_structured_status_only(tmp_path):
    data = ledger(tmp_path)
    ref = data.record("fetch_url_content", {}, "error: 是新闻引用，不是工具失败")
    unavailable = data.record("get_stock_price", {}, {"status": "unavailable", "price": None})
    data.save()
    restored = ledger(tmp_path, "new")
    assert restored.restore("run")
    assert ref in restored.records and unavailable not in restored.records
    assert json.loads(data._path("run").read_text(encoding="utf-8"))["reference_style"] == "integer"


def test_computation_combines_input_and_explicit_sources_without_adding_output_sources(tmp_path):
    data = ledger(tmp_path)
    first = record(data)
    second = record(data, ticker="MSFT", url="https://example.test/second")
    third = record(data, ticker="NVDA", url="https://example.test/third")
    raw = {"rows": [{"value": -0.000125, "missing": None}], "source_refs": data.source_refs(third),
           "source": "计算自己写的来源", "url": "https://example.test/not-a-financial-source"}
    ref = data.record("run_analysis_code", {"dataset_refs": [first], "handles": [second]}, raw)
    assert data.source_refs(ref) == ["1", "2", "3"]
    assert data.records[ref]["output"] == raw and len(data.sources) == 3


def test_assumption_only_computation_has_no_financial_sources(tmp_path):
    data = ledger(tmp_path)
    raw = {"rows": [{"assumed_eps": 3, "multiple": 20, "value": 60}], "source": "假设来源"}
    ref = data.record("run_analysis_code", {"dataset_refs": []}, raw,
        envelope=ToolResult(status="ok", kind="computation", data=raw,
                            sources=[Source(title="计算输出的名称", url="https://example.test/assumption")]))
    assert data.source_refs(ref) == [] and data.sources == {}
    assert data.rows(ref) == raw["rows"]
