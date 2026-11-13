"""信封来源账本、完整值与租户恢复协议；不解析用户原话或模型答案。"""
import builtins
from copy import deepcopy
import json

import pytest

from backend.agent_runtime.adapters import adapt_result
from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import Source, ToolError, ToolResult


def ledger(tmp_path, run_id="fixture-run", owner="fixture-owner"):
    value = RunData(owner, "fixture-session", run_id, "用户问题包含OTHER 9999，不参与工具来源绑定")
    value.storage_dir = tmp_path
    return value


def test_record_cannot_import_or_invoke_legacy_graph_normalizer(tmp_path, monkeypatch):
    original = builtins.__import__
    def no_graph(name, *args, **kwargs):
        if name == "backend.graph" or name.startswith("backend.graph."):
            raise AssertionError("原生账本不得加载旧图")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_graph)
    data = ledger(tmp_path)
    raw = {"price": 12.125, "currency": "HKD"}
    envelope = ToolResult(status="ok", kind="quote", data=raw,
                          sources=[Source(title="协议来源", url="https://example.invalid/quote")])
    ref = data.record("get_stock_price", {"ticker": "FIXTURE"}, raw, envelope=envelope)
    assert data.records[ref]["output"] == raw and data.source_refs(ref)
    assert data.records[ref]["status"] == "success" and data.records[ref]["envelope"]["status"] == "ok"


def test_explicit_sources_do_not_scan_raw_document_links_numbers_or_tickers(tmp_path):
    data = ledger(tmp_path)
    body = "OTHER股价9999美元。\nhttps://undeclared.invalid/document"
    envelope = ToolResult(status="ok", kind="document", data=body,
                          sources=[Source(title="已声明来源", url="https://declared.invalid/document")])
    ref = data.record("fetch_url_content", {"ticker": "FIXTURE"}, body, envelope=envelope)
    sources = [data.sources[sid] for sid in data.source_refs(ref)]
    assert {source["url"] for source in sources} == {"https://declared.invalid/document"}
    assert all(source["metadata"]["parameters"]["ticker"] == "FIXTURE" for source in sources)
    assert data.records[ref]["output"] == body


def test_date_only_publication_and_quote_units_keep_their_actual_precision(tmp_path):
    data = ledger(tmp_path)
    raw = {"data": {"price": 12.125, "currency": "HKD", "source_timestamp": "2026-01-02",
                     "source_time_precision": "date", "market_session": "regular_close"}}
    envelope = ToolResult(status="ok", kind="quote", data=raw,
                          sources=[Source(title="报价来源", url="https://example.invalid/quote")])
    ref = data.record("get_stock_price", {"ticker": "FIXTURE"}, raw, envelope=envelope)
    source = data.sources[data.source_refs(ref)[0]]
    assert source["currency"] == "HKD" and source["as_of"] == "2026-01-02"
    assert source["metadata"]["source_time_precision"] == "date"
    article = {"news": [{"title": "协议公告", "url": "https://example.invalid/news", "published_at": "2026-01-03"}]}
    ref = data.record("get_company_news", {"ticker": "FIXTURE"}, article,
                      envelope=ToolResult(status="ok", kind="news", data=article,
                                          sources=[Source(title="协议公告", url="https://example.invalid/news")]))
    source = next(data.sources[sid] for sid in data.source_refs(ref) if data.sources[sid]["url"] == "https://example.invalid/news")
    assert source["published_date"] == "2026-01-03" and "00:00" not in json.dumps(source)


def test_direct_json_source_aliases_preserve_date_only_and_publisher(tmp_path):
    data = ledger(tmp_path)
    ref = data.record("get_company_news", {"ticker": "FIXTURE"}, [{"title": "协议消息",
        "url": "https://example.invalid/direct", "publisher": "协议发布方", "published_at": "2026-01-04"}])
    source = data.sources[data.source_refs(ref)[0]]
    assert source["published_date"] == "2026-01-04" and source["source_name"] == "协议发布方"


def test_unverified_source_binding_survives_declared_source_and_restore(tmp_path):
    data = ledger(tmp_path)
    raw = {"price": 12.125, "currency": "USD", "metadata": {"subject_binding": "unverified", "ticker": "OTHER"}}
    envelope = ToolResult(status="ok", kind="quote", data=raw,
                          sources=[Source(title="待核对来源", url="https://example.invalid/unverified")])
    ref = data.record("get_stock_price", {"ticker": "FIXTURE"}, raw, envelope=envelope)
    source_id = data.source_refs(ref)[0]
    assert data.sources[source_id]["metadata"]["subject_binding"] == "unverified"
    data.save()
    restored = ledger(tmp_path, run_id="child")
    assert restored.restore(data.run_id)
    assert restored.sources[source_id]["metadata"]["subject_binding"] == "unverified"
    assert restored.sources[source_id]["metadata"]["ticker"] == "OTHER"


def test_direct_record_and_enveloped_record_have_the_same_immutable_data_handle(tmp_path):
    data = ledger(tmp_path)
    raw = {"rows": [{"close": -12.125}], "source_url": "https://example.invalid/history", "currency": "USD"}
    before = deepcopy(raw)
    direct = data.record("get_stock_historical_data", {"ticker": "FIXTURE"}, raw)
    envelope = ToolResult(status="ok", kind="series", data=raw,
                          sources=[Source(title="额外交叉来源", url="https://example.invalid/secondary")])
    repeated = data.record("get_stock_historical_data", {"ticker": "FIXTURE"}, raw, envelope=envelope)
    assert direct == repeated and len(data.records) == len(data.steps) == 1
    assert data.records[direct]["output"] == before and raw == before
    assert "data" not in data.records[direct]["envelope"]
    assert {data.sources[sid]["url"] for sid in data.source_refs(direct)} == {
        "https://example.invalid/history", "https://example.invalid/secondary"}


def test_financial_metric_metadata_and_units_remain_in_full_data_and_rows(tmp_path):
    data = ledger(tmp_path)
    raw = {"source": "sec_companyfacts", "source_url": "https://example.invalid/filing", "currency": "USD", "frequency": "quarterly",
           "period_ends": ["2026-03-31"], "revenue": [12.125], "operating_cash_flow": [10], "capital_expenditures": [3],
           "fact_metadata": {"revenue": [{"unit": "USD", "period_start": "2026-01-01", "period_end": "2026-03-31",
                                          "derivation": "reported_quarter", "audit": "完整申报原文" * 100}]}}
    before = deepcopy(raw)
    ref = data.record("get_sec_company_facts_quarterly", {"ticker": "FIXTURE"}, raw,
                      envelope=ToolResult(status="ok", kind="table", data=raw,
                                          sources=[Source(title="申报来源", url=raw["source_url"])]))
    assert data.records[ref]["output"] == before
    assert data.rows(ref)[0]["fact_metadata"]["revenue"] == raw["fact_metadata"]["revenue"][0]
    assert data.rows(ref)[0]["revenue"] == 12.125
    data.save()
    restored = ledger(tmp_path, run_id="child")
    assert restored.restore(data.run_id) and restored.rows(ref) == data.rows(ref)
    assert restored.source_refs(ref) == data.source_refs(ref)
    assert not ledger(tmp_path, run_id="another", owner="another-owner").restore(data.run_id)


def test_error_empty_and_control_envelopes_do_not_gain_sources_or_restore(tmp_path):
    data = ledger(tmp_path)
    for result in [ToolResult(status="empty", kind="quote", data=[]),
                   ToolResult(status="error", kind="quote", data={"price": 12},
                              error=ToolError(code="fixture_error", user_message="协议错误", retryable=False)),
                   ToolResult(status="ok", kind="control", data={"status": "confirmation_required"})]:
        ref = data.record("fixture", {}, result.data, envelope=result)
        assert data.source_refs(ref) == []
    assert data.sources == {}
    data.save()
    assert not ledger(tmp_path, run_id="child").restore(data.run_id)


@pytest.mark.parametrize("value,expected", [(None, "empty"), ([], "empty"), ({}, "empty"),
    ({"status": "ok", "error": "资料中的字段"}, "ok"), ({"status": "empty"}, "empty"),
    ({"status": "error"}, "error"), ({"error_code": "tool_timeout"}, "error"),
    ("error: 这里是工具返回的普通正文", "ok"), ({"summary": "failed unavailable 错误"}, "ok")])
def test_failure_predicate_uses_protocol_status_instead_of_body_words(value, expected):
    result = adapt_result("fetch_url_content", value)
    assert result.status == expected and result.data == value
