"""工具类型注册、原始资料和源头转换合同；不调用模型或真实供应商。"""
from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agent_runtime.adapters import ADAPTERS, TOOL_KINDS, adapt_result, invoke_adapter
from backend.agent_runtime.context import tokens
from backend.agent_runtime.envelope import to_model, to_ui


def test_catalog_covers_all_current_financial_and_runtime_tools():
    from backend.agent_runtime.registry import financial_tools
    assert set(financial_tools()).issubset(ADAPTERS)
    assert set(ADAPTERS) == set(TOOL_KINDS)


def test_exa_publication_timestamp_survives_source_projection_without_changing_data():
    raw = {"results": [{"title": "测试公开资料", "url": "https://example.com/filing",
                        "publishedDate": "2026-11-10T15:30:00Z", "text": "合成协议样本"}]}
    before = deepcopy(raw)
    result = adapt_result("search", raw)
    assert result.data == raw == before
    assert result.sources[0].published_at.isoformat() == "2026-11-10T15:30:00+00:00"


def test_date_only_publication_is_retained_without_inventing_a_time():
    raw = {"results": [{"title": "测试公开资料", "url": "https://example.com/filing",
                        "publishedDate": "2026-11-10"}]}
    result = adapt_result("search", raw)
    assert result.data == raw
    assert result.sources[0].published_at is None


@pytest.mark.parametrize("status,expected", [("ok", "ok"), ("success", "ok"), ("empty", "empty"),
                                           ("error", "error"), ("unavailable", "error"), ("failed", "error")])
def test_failure_is_selected_by_structured_status(status, expected):
    raw = {"status": status, "summary": "error: 这里是源内容而不是错误判定规则", "value": 42}
    result = adapt_result("get_company_info", raw)
    assert result.status == expected and result.data == raw


@pytest.mark.parametrize("status", ["confirmation_required", "blocked", "waiting", "completed"])
def test_control_state_is_kept_in_payload_and_is_not_a_financial_source(status):
    raw = {"status": status, "source": "internal_control", "action_id": "fixture-action"}
    result = adapt_result("propose_action", raw)
    assert result.status == "ok" and result.data == raw and result.sources == []


def test_opaque_quote_is_explicitly_unsupported_and_never_parsed():
    text = "FIXTURE Current Price: $12.50 | Provider: unit_fixture"
    result = adapt_result("get_stock_price", text)
    assert result.status == "error" and result.error.code == "unsupported_payload"
    assert result.data == text


def test_json_machine_payload_is_decoded_without_body_matching():
    raw = {"status": "ok", "revenue": 42.125, "currency": "fixture-unit", "summary": "错误一词属于资料正文"}
    assert adapt_result("get_company_info", json.dumps(raw)).data == raw


def test_serialized_envelope_is_not_wrapped_a_second_time():
    result = adapt_result("get_company_news", {"status": "ok", "news": [], "source": "unit_fixture"})
    restored = adapt_result("get_company_news", result.model_dump(mode="json"))
    assert restored == result and restored.data == result.data


def test_quote_source_is_structured_gateway_and_fallback_is_not_called(monkeypatch):
    from backend.services import market_data_gateway
    raw = {"status": "ok", "source": "unit_fixture", "as_of": "2026-01-02", "data": {"price": 12.125, "currency": "fixture-unit"}}
    seen = []
    def get_quote(ticker):
        seen.append(ticker)
        return raw
    monkeypatch.setattr(market_data_gateway, "get_market_data_gateway", lambda: SimpleNamespace(get_quote=get_quote))
    def forbidden(_arguments):
        raise AssertionError("不得通过格式化报价入口")
    result = invoke_adapter("get_stock_price", {"ticker": "FIXTURE"}, forbidden)
    assert seen == ["FIXTURE"] and result.data == raw and result.status == "ok"
    assert result.as_of is None and to_ui(result)["as_of"] == "2026-01-02"


def test_timeout_is_structured_and_does_not_copy_exception_message():
    def timeout(_):
        raise TimeoutError("private-provider-detail")
    result = invoke_adapter("get_company_news", {}, timeout)
    assert result.error.code == "provider_timeout" and result.error.retryable is True
    assert "private-provider-detail" not in result.model_dump_json()


def test_company_profile_uses_structured_provider_without_formatting(monkeypatch):
    from backend.tools import financial
    raw = {"longName": "协议样本公司", "marketCap": 42.125, "currency": "fixture-unit"}
    monkeypatch.setattr(financial, "create_ticker", lambda _ticker: SimpleNamespace(info=raw))
    result = invoke_adapter("get_company_info", {"ticker": "FIXTURE"}, lambda _: pytest.fail("不调用格式化资料入口"))
    assert result.status == "ok" and result.data["marketCap"] == raw["marketCap"]
    assert result.data["longName"] == raw["longName"] and result.data["source"] == "yfinance"


def test_search_uses_structured_provider_and_retains_full_result(monkeypatch):
    provider = importlib.import_module("backend.tools.search")
    raw = {"results": [{"title": "协议资料", "url": "https://example.invalid/document", "content": "完整协议正文"}]}
    monkeypatch.setattr(provider, "EXA_API_KEY", "")
    monkeypatch.setattr(provider, "TAVILY_API_KEY", "fixture-key")
    monkeypatch.setattr(provider, "TAVILY_AVAILABLE", True)
    monkeypatch.setattr(provider, "TavilyClient", lambda **_: SimpleNamespace(search=lambda **_: raw))
    result = invoke_adapter("search", {"query": "协议查询"}, lambda _: pytest.fail("不调用格式化搜索入口"))
    assert result.status == "ok" and result.data["results"] == raw["results"]
    assert result.sources[-1].url == raw["results"][0]["url"]


def _recorded(tool):
    root = Path(__file__).resolve().parents[2] / "tests/agent_eval/fixtures/archive-v1/tapes"
    for path in sorted(root.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["tool"] == tool:
            return record
    raise AssertionError("缺少明确的真实录制")


@pytest.mark.parametrize("tool", ["get_stock_historical_data", "get_sec_company_facts_quarterly", "get_company_news"])
def test_archived_real_payload_is_retained_and_rendered_under_budget(tool):
    record = _recorded(tool)
    before = deepcopy(record["raw_output"])
    result = adapt_result(tool, record["raw_output"], record["arguments"])
    text = to_model(result, 2000, handle="h_recorded", source_ids=["1"])
    assert result.data == before and record["raw_output"] == before
    assert tokens(text) <= 2000 and result.kind == TOOL_KINDS[tool]
