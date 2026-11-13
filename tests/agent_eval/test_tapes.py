"""录制回放的协议测试，不约束任何自然语言问法。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
import time

import pytest

from .tapes import ToolTape, _hash


def forbidden(_args):
    raise AssertionError("回放不能访问真实工具")


def test_record_seed_preserves_bytes_and_replays_without_the_archive(tmp_path):
    seed = tmp_path / "archive"
    target = tmp_path / "case"
    payload = {"status": "ok", "price": 42.5, "currency": "USD"}
    ToolTape(seed, "record").invoke("get_stock_price", {"ticker": "AAPL"}, lambda _: payload)
    original = next(seed.glob("*.json")).read_bytes()
    tape = ToolTape(target, "record", seed_path=seed)
    assert tape.invoke("get_stock_price", {"ticker": "AAPL"}, forbidden) == payload
    assert next(target.glob("*.json")).read_bytes() == original
    assert next(seed.glob("*.json")).read_bytes() == original
    assert ToolTape(target, "replay").invoke("get_stock_price", {"ticker": "AAPL"}, forbidden) == payload


def test_seed_does_not_match_a_different_ticker_or_parameter(tmp_path):
    seed = tmp_path / "archive"
    ToolTape(seed, "record").invoke("quote", {"ticker": "AAPL", "delay": 1}, lambda _: {"price": 42})
    tape = ToolTape(tmp_path / "case", "record", seed_path=seed)
    calls = []
    def live(args):
        calls.append(args)
        return {"price": 99}
    assert tape.invoke("quote", {"ticker": "NVDA", "delay": 1}, live) == {"price": 99}
    assert tape.invoke("quote", {"ticker": "AAPL", "delay": 2}, live) == {"price": 99}
    assert len(calls) == 2


def test_replay_cannot_fill_a_missing_case_from_seed(tmp_path):
    seed = tmp_path / "archive"
    ToolTape(seed, "record").invoke("quote", {"ticker": "AAPL"}, lambda _: {"price": 42})
    target = tmp_path / "case"
    result = ToolTape(target, "replay", seed_path=seed).invoke("quote", {"ticker": "AAPL"}, forbidden)
    assert result["error_code"] == "tape_miss"
    assert not target.exists()


def test_seed_checksum_is_validated_before_it_is_copied(tmp_path):
    seed = tmp_path / "archive"
    ToolTape(seed, "record").invoke("quote", {}, lambda _: {"price": 42})
    path = next(seed.glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["raw_output"] = {"price": 99}
    path.write_text(json.dumps(record), encoding="utf-8")
    target = tmp_path / "case"
    with pytest.raises(ValueError, match="tape_corrupt"):
        ToolTape(target, "record", seed_path=seed).invoke("quote", {}, forbidden)
    assert not target.exists()


def test_canonical_arguments_ignore_dict_key_order(tmp_path):
    tape = ToolTape(tmp_path, "record")
    first = {"ticker": "0700.HK", "options": {"end": 2, "start": 1}}
    other = {"options": {"start": 1, "end": 2}, "ticker": "0700.HK"}
    assert tape.invoke("quote", first, lambda args: {"price": 42}) == {"price": 42}
    assert tape.invoke("quote", other, forbidden) == {"price": 42}
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert tape.stats() == {"recorded": 1, "hits": 1, "misses": 0, "errors": 0}


def test_new_replay_instance_never_calls_original_tool(tmp_path):
    original = {"status": "ok", "rows": [{"价格": 12.5}], "source": "fixture"}
    ToolTape(tmp_path, "record").invoke("get_stock_price", {"ticker": "AAPL"}, lambda _: original)
    tape = ToolTape(tmp_path, "replay")
    assert tape.invoke("get_stock_price", {"ticker": "AAPL"}, forbidden) == original
    record = tape.records()[0]
    assert record["result"]["status"] == "ok"
    assert record["result"]["kind"] == "quote"
    assert record["raw_output"] == original


def test_replay_miss_is_error_without_creating_fixture(tmp_path):
    tape = ToolTape(tmp_path / "absent", "replay")
    result = tape.invoke("quote", {"ticker": "AAPL"}, forbidden)
    assert result["status"] == "error" and result["error_code"] == "tape_miss"
    assert tape.stats() == {"recorded": 0, "hits": 0, "misses": 1, "errors": 1}
    assert not tape.path.exists()


@pytest.mark.parametrize("exception,code", [(TimeoutError, "provider_timeout"), (RuntimeError, "tool_exception")])
def test_exception_records_only_type_and_safe_code(tmp_path, exception, code):
    def failing(_):
        raise exception("secret-provider-response-that-must-not-be-written")
    tape = ToolTape(tmp_path, "record")
    result = tape.invoke("quote", {}, failing)
    assert result["error_code"] == code
    record = tape.records()[0]
    assert record["exception_type"] == exception.__name__
    assert "secret-provider-response" not in json.dumps(record)
    assert ToolTape(tmp_path, "replay").invoke("quote", {}, forbidden) == result


@pytest.mark.parametrize("status", ["error", "empty"])
def test_faults_overlay_without_overwriting_live_recording(tmp_path, status):
    original = {"price": 42}
    ToolTape(tmp_path, "record").invoke("quote", {}, lambda _: original)
    before = next(tmp_path.glob("*.json")).read_bytes()
    tape = ToolTape(tmp_path, "replay", {"quote": {"status": status, "code": "provider_timeout"}})
    assert tape.invoke("quote", {}, forbidden)["status"] == status
    assert tape.records()[0]["injected"] is True
    assert next(tmp_path.glob("*.json")).read_bytes() == before
    assert ToolTape(tmp_path, "replay").invoke("quote", {}, forbidden) == original


def test_replay_outputs_and_judge_records_are_independent_copies(tmp_path):
    tape = ToolTape(tmp_path, "record")
    tape.invoke("quote", {}, lambda _: {"rows": [{"price": 42}]})
    first = tape.invoke("quote", {}, forbidden)
    first["rows"][0]["price"] = 99
    records = tape.records()
    records[0]["raw_output"]["rows"].clear()
    assert tape.invoke("quote", {}, forbidden) == {"rows": [{"price": 42}]}
    assert tape.records()[0]["raw_output"] == {"rows": [{"price": 42}]}


def test_concurrent_same_key_invokes_once(tmp_path):
    tape = ToolTape(tmp_path, "record")
    count, lock = [], Lock()
    def original(args):
        with lock:
            count.append(args)
        time.sleep(.02)
        return {"price": 42}
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: tape.invoke("quote", {"ticker": "AAPL"}, original), range(8)))
    assert results == [{"price": 42}] * 8
    assert len(count) == 1
    assert tape.stats()["recorded"] == 1 and tape.stats()["hits"] == 7


@pytest.mark.parametrize("arguments", [{"x": float("nan")}, {"x": float("inf")}, {"x": {1, 2}}, {"x": (1, 2)}, {1: "value"}])
def test_non_json_arguments_are_rejected_before_call(tmp_path, arguments):
    with pytest.raises(ValueError, match="tape_non_json_value"):
        ToolTape(tmp_path, "record").invoke("quote", arguments, forbidden)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("field,value", [("key", "wrong"), ("raw_output", {"price": 99}), ("checksum", "wrong")])
def test_tampered_record_is_rejected(tmp_path, field, value):
    tape = ToolTape(tmp_path, "record")
    tape.invoke("quote", {}, lambda _: {"price": 42})
    path = next(tmp_path.glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record[field] = value
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="tape_corrupt"):
        ToolTape(tmp_path, "replay").invoke("quote", {}, forbidden)


def test_structured_status_controls_failure_not_text(tmp_path):
    tape = ToolTape(tmp_path, "record")
    tape.invoke("text", {}, lambda _: "error: this is quoted source text")
    tape.invoke("structured", {}, lambda _: {"status": "error", "error_code": "provider_timeout"})
    tape.invoke("code", {}, lambda _: {"error_code": "not_found"})
    records = {row["tool"]: row for row in tape.records()}
    assert records["text"]["result"]["status"] == "ok"
    assert records["structured"]["result"]["status"] == "error"
    assert records["code"]["result"]["status"] == "error"


def test_exact_environment_secrets_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_API_KEY", "exact-fixture-secret")
    monkeypatch.setenv("FINSIGHT_AGENT_MAX_OUTPUT_TOKENS", "16384")
    monkeypatch.setenv("FINSIGHT_AGENT_TOKEN_BUDGET", "160000")
    tape = ToolTape(tmp_path, "record")
    original_args = {"api_key": "exact-fixture-secret", "ticker": "AAPL"}
    def original(args):
        assert args == original_args
        return {"note": "received exact-fixture-secret", "other": "sk-ordinary-source-text", "budget": "16384 / 160000"}
    result = tape.invoke("quote", original_args, original)
    assert result["note"] == "received [REDACTED]"
    assert result["other"] == "sk-ordinary-source-text"
    assert result["budget"] == "16384 / 160000"
    assert "exact-fixture-secret" not in next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert tape.invoke("quote", original_args, forbidden) == result


def test_wrap_specs_preserves_schema_and_invokes_correct_callback(tmp_path):
    @dataclass
    class Spec:
        name: str
        invoke: object
        parameters: dict
        financial: bool = True
    specs = {name: Spec(name, lambda _, result=value: result, {"type": "object"})
             for name, value in (("first", 1), ("second", 2))}
    wrapped = ToolTape(tmp_path, "record").wrap_specs(specs)
    assert wrapped["first"].invoke({}) == 1
    assert wrapped["second"].invoke({}) == 2
    assert wrapped["first"].parameters == specs["first"].parameters
    assert wrapped["first"].financial is True
    assert wrapped["first"] is not specs["first"]


def test_candidate_record_preserves_raw_and_captured_response_for_both_replays(tmp_path, monkeypatch):
    from backend.agent_runtime.registry import ToolSpec
    from backend.services.market_data_gateway import MarketDataGateway
    from .baseline_runtime.tools import ToolSpec as BaselineSpec
    from .capture import install_capture_hooks

    args = {"ticker": "SYNTH"}
    quote = {"status": "ok", "data": {"price": 42.25, "currency": "USD"}, "provider": "fixture"}
    raw = "合成报价原文：42.25 USD"
    calls = []
    def get_quote(_gateway, symbol):
        calls.append(symbol)
        return quote
    monkeypatch.setattr(MarketDataGateway, "get_quote", get_quote)
    gateway = object.__new__(MarketDataGateway)
    def legacy(arguments):
        assert arguments == args
        assert gateway.get_quote(arguments["ticker"]) is quote
        return raw
    specs = {name: ToolSpec(name, "合成工具", {"type": "object"}, forbidden, True, True)
             for name in ("get_stock_price", "get_company_info")}
    record_specs = {name: BaselineSpec(name, spec.description, spec.parameters,
                                     legacy if name == "get_stock_price" else forbidden, True)
                    for name, spec in specs.items()}
    tape = ToolTape(tmp_path, "record")
    with install_capture_hooks():
        wrapped = tape.wrap_specs(specs, record_specs=record_specs)
        assert calls == []
        result = wrapped["get_stock_price"].invoke(args)
        assert result["status"] == "ok" and result["kind"] == "quote" and result["data"] == quote
        assert wrapped["get_stock_price"].invoke(args) == result
    assert calls == [args["ticker"]]
    assert wrapped["get_stock_price"].openai() == specs["get_stock_price"].openai()
    record, = tape.records()
    assert record["raw_output"] == raw
    assert record["producer_capture"]["status"] == "captured"
    captured, = record["producer_outputs"]
    assert captured["data"] == quote and captured["arguments"] == {"symbol": args["ticker"]}
    path, = tmp_path.glob("*.json")
    before = path.read_bytes()
    baseline = BaselineSpec("get_stock_price", "合成工具", {"type": "object"}, forbidden, True)
    assert ToolTape(tmp_path, "replay").wrap_specs({baseline.name: baseline})[baseline.name].invoke(args) == raw
    assert ToolTape(tmp_path, "replay").wrap_specs(specs)[baseline.name].invoke(args) == result
    assert path.read_bytes() == before and calls == [args["ticker"]]


@pytest.mark.parametrize("record_specs", [None, {}])
def test_candidate_record_requires_matching_raw_entry(tmp_path, record_specs):
    from backend.agent_runtime.registry import ToolSpec

    spec = ToolSpec("get_stock_price", "合成工具", {"type": "object"}, forbidden, True, True)
    with pytest.raises(ValueError, match="^tape_record_spec_missing:get_stock_price$"):
        ToolTape(tmp_path, "record").wrap_specs({spec.name: spec}, record_specs=record_specs)
    assert not list(tmp_path.iterdir())


def test_candidate_replay_uses_captured_structured_quote_without_refetch(tmp_path):
    from backend.agent_runtime.registry import ToolSpec
    args = {"ticker": "AAPL"}
    seed = ToolTape(tmp_path, "record")
    key = _hash({"tool": "get_stock_price", "arguments": args})
    quote = {"status": "ok", "data": {"price": 42.25, "currency": "USD"}, "provider": "fixture"}
    record = seed._record(key, "get_stock_price", args, "legacy formatted quote",
        producer_outputs=[{"producer": "market_data_gateway", "method": "get_quote", "status": "captured", "data": quote}])
    path = tmp_path / (key + ".json")
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    spec = ToolSpec("get_stock_price", "行情", {"type": "object"}, forbidden, True, True)
    tape = ToolTape(tmp_path, "replay")
    result = tape.wrap_specs({spec.name: spec})[spec.name].invoke(args)
    assert result["status"] == "ok" and result["data"] == quote
    assert path.read_bytes() == before


def test_candidate_replay_reports_legacy_capture_gap_without_parsing_text(tmp_path):
    from backend.agent_runtime.registry import ToolSpec
    args = {"ticker": "AAPL"}
    ToolTape(tmp_path, "record").invoke("get_stock_price", args, lambda _: "legacy price 42.25")
    spec = ToolSpec("get_stock_price", "行情", {"type": "object"}, forbidden, True, True)
    result = ToolTape(tmp_path, "replay").wrap_specs({spec.name: spec})[spec.name].invoke(args)
    assert result["status"] == "error" and result["error"]["code"] == "unsupported_payload"


def test_record_without_capture_hooks_exposes_capability_gap(tmp_path):
    tape = ToolTape(tmp_path, "record")
    tape.invoke("quote", {}, lambda _: "legacy text")
    record = tape.records()[0]
    assert record["producer_outputs"] == []
    assert record["producer_capture"]["status"] == "unavailable"
    assert record["producer_capture"]["reason"] == "capture_hooks_not_installed"


def test_legacy_record_is_not_overwritten_or_refetched_for_capture(tmp_path):
    tape = ToolTape(tmp_path, "record")
    tape.invoke("quote", {}, lambda _: "original legacy text")
    path = next(tmp_path.glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("producer_outputs")
    record.pop("producer_capture")
    record.pop("checksum")
    record["checksum"] = _hash(record)
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    assert tape.invoke("quote", {}, forbidden) == "original legacy text"
    view = tape.records()[0]
    assert view["producer_capture"]["reason"] == "legacy_record_without_producer_outputs"
    assert view["recorded_checksum"] == record["checksum"]
    assert path.read_bytes() == before


def synthetic_http_capture(url, data, status=200, **overrides):
    return {"producer": "requests.Response", "method": "json", "status": "captured",
            "arguments": {"url": url, "status_code": status}, "data": data, **overrides}


def synthetic_record(tmp_path, name, args, captures):
    """最低同结构合成样本，不代表真实公司或真实市场数据。"""
    tape = ToolTape(tmp_path, "record")
    key = _hash({"tool": name, "arguments": args})
    record = tape._record(key, name, args, "合成格式化正文：不能从此推断市场数值。", producer_outputs=captures)
    record["synthetic"] = True
    record.pop("checksum")
    record["checksum"] = _hash(record)
    path = tmp_path / (key + ".json")
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return tape, record, path


@pytest.mark.parametrize("url,provider", [("https://api.exa.ai/search", "exa"),
                                          ("https://API.EXA.AI//search/?fixture=1#part", "exa"),
                                          ("https://api.tavily.com/search", "tavily")])
def test_search_projection_reads_structured_http_results_and_preserves_raw_baseline(tmp_path, url, provider):
    from backend.agent_runtime.registry import ToolSpec

    args = {"query": "synthetic-query"}
    data = {"results": [{"title": "Synthetic article", "url": "https://news.example.invalid/item",
                          "text": "Synthetic content", "publishedDate": "2000-01-01T12:00:00Z"}]}
    _tape, record, path = synthetic_record(tmp_path, "search", args, [synthetic_http_capture(url, data)])
    before = path.read_bytes()
    candidate = ToolSpec("search", "synthetic", {"type": "object"}, forbidden, True, True)
    legacy = ToolSpec("search", "synthetic", {"type": "object"}, forbidden, True, False)
    result = ToolTape(tmp_path, "replay").wrap_specs({"search": candidate})["search"].invoke(args)
    assert result["status"] == "ok" and result["data"]["source"] == provider
    assert result["data"]["results"] == data["results"]
    assert any(source["url"] == data["results"][0]["url"] for source in result["sources"])
    assert ToolTape(tmp_path, "replay").wrap_specs({"search": legacy})["search"].invoke(args) == record["raw_output"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("url,profile,provider", [
    ("https://api.finnhub.io/api/v1//stock/profile2", {"name": "Synthetic Company", "ticker": "SYNTH", "currency": "USD", "marketCapitalization": 12.5}, "finnhub"),
    ("https://www.alphavantage.co/query", {"Symbol": "SYNTH", "Currency": "USD", "MarketCapitalization": "12500000"}, "alpha_vantage"),
])
def test_company_projection_maps_known_profile_protocol_and_units(tmp_path, url, profile, provider):
    args = {"ticker": "SYNTH"}
    _tape, record, path = synthetic_record(tmp_path, "get_company_info", args, [synthetic_http_capture(url, profile)])
    before = path.read_bytes()
    result = ToolTape.project_envelope("get_company_info", args, record)
    assert result["status"] == "ok" and result["data"]["source"] == provider
    assert result["data"]["ticker"] == args["ticker"]
    assert all(result["data"][key] == value for key, value in profile.items())
    if provider == "finnhub":
        assert result["data"]["column_units"] == {"marketCapitalization": "million USD"}
    assert path.read_bytes() == before


@pytest.mark.parametrize("name,url,data,status,expected", [
    ("search", "https://api.exa.ai/search", {"results": []}, 200, "empty"),
    ("search", "https://api.tavily.com/search", {"error": "synthetic-denial"}, 403, "error"),
    ("get_company_info", "https://api.finnhub.io/api/v1/stock/profile2", {}, 200, "empty"),
    ("get_company_info", "https://api.finnhub.io/api/v1/stock/profile2", {"error": "synthetic-denial"}, 403, "error"),
    ("get_company_info", "https://www.alphavantage.co/query", {"Information": "synthetic-protocol-message"}, 200, "error"),
])
def test_projection_keeps_real_protocol_empty_and_errors(tmp_path, name, url, data, status, expected):
    args = {"query": "synthetic-query"} if name == "search" else {"ticker": "SYNTH"}
    _tape, record, _path = synthetic_record(tmp_path, name, args, [synthetic_http_capture(url, data, status)])
    result = ToolTape.project_envelope(name, args, record)
    assert result["status"] == expected
    if status == 403:
        assert result["error"]["code"] == "provider_http_403"
        assert result["data"]["http_status"] == 403


@pytest.mark.parametrize("override", [{"producer": "unknown.Response"}, {"method": "text"},
                                    {"arguments": {"url": "https://api.exa.ai.evil.invalid/search", "status_code": 200}},
                                    {"arguments": {"url": "https://api.exa.ai/other", "status_code": 200}}])
def test_projection_does_not_guess_provider_from_payload_fields_or_body(tmp_path, override):
    args = {"query": "synthetic-query"}
    capture = synthetic_http_capture("https://api.exa.ai/search", {"source": "exa", "results": []}, **override)
    _tape, record, _path = synthetic_record(tmp_path, "search", args, [capture])
    result = ToolTape.project_envelope("search", args, record)
    assert result["status"] == "error" and result["error"]["code"] == "unsupported_payload"


def test_company_fallback_uses_success_and_does_not_mask_error_with_empty(tmp_path):
    args = {"ticker": "SYNTH"}
    denied = synthetic_http_capture("https://api.finnhub.io/api/v1/stock/profile2", {"error": "synthetic-denial"}, 403)
    _tape, record, _path = synthetic_record(tmp_path, "get_company_info", args, [denied,
        synthetic_http_capture("https://www.alphavantage.co/query", {})])
    assert ToolTape.project_envelope("get_company_info", args, record)["error"]["code"] == "provider_http_403"
    record["producer_outputs"][1]["data"] = {"Symbol": "SYNTH", "Currency": "USD"}
    result = ToolTape.project_envelope("get_company_info", args, record)
    assert result["status"] == "ok" and result["data"]["source"] == "alpha_vantage"


def test_empty_yahoo_capture_does_not_hide_structured_finnhub_profile(tmp_path):
    args = {"ticker": "SYNTH"}
    _tape, record, _path = synthetic_record(tmp_path, "get_company_info", args, [
        {"producer": "yfinance.TickerBase", "method": "get_info", "status": "captured", "data": {}},
        synthetic_http_capture("https://api.finnhub.io/api/v1/stock/profile2", {"name": "Synthetic Company", "currency": "USD"})])
    result = ToolTape.project_envelope("get_company_info", args, record)
    assert result["status"] == "ok" and result["data"]["source"] == "finnhub"


@pytest.mark.parametrize("folder,key", [
    ("attribution-01", "942e32abfb4753b2e419b20a621f11b449be73be4f2c42134df6f9c9097f9917"),
    ("facts-02", "3ea68a3bbf1531ed759d34b5f71825c8f855ad92ce15ac308822a252983b9ad3"),
    ("attribution-01", "e592cd1e6086720805bf0fc5f90ec6e203a9869433c27d88b8c76a20405c1669"),
])
def test_real_recorded_provider_projection_preserves_original_file_bytes(folder, key):
    path = Path(__file__).parent / "fixtures" / "qwen-canonical-v1" / folder / (key + ".json")
    if not path.is_file():
        pytest.skip("真实录制不在当前测试环境；合成协议矩阵仍必跑")
    before = path.read_bytes()
    record = json.loads(before.decode("utf-8"))
    result = ToolTape.project_envelope(record["tool"], record["arguments"], record)
    assert result["status"] == "ok"
    assert path.read_bytes() == before
