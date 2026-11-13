"""历史录制导入的协议测试；样本仅在临时目录中合成。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from .tapes import ToolTape, _hash


@pytest.fixture(autouse=True)
def isolated_archive_workspace(tmp_path, monkeypatch):
    from . import import_archive
    monkeypatch.setattr(import_archive, "REPO", tmp_path)


def write_source(path: Path, payload, *, ticker="AAPL", tool="get_stock_price", **metadata):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"synthetic": True, "owner": "private-owner", "session_id": "private-session",
            "query": "private-user-query", "records": {
                "dataset_test": {"tool": tool, "inputs": {"ticker": ticker},
                                 "output": payload, "status": "success"}}, **metadata}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def forbidden(_arguments):
    raise AssertionError("导入和回放不能调用供应商")


def import_fixture(source, output, **kwargs):
    from .import_archive import import_sources
    return import_sources([source], output, **kwargs)


@pytest.mark.parametrize("payload", [
    {"price": 42.5, "currency": "USD", "notes": ["中文说明", None]},
    [{"title": "合成新闻", "url": "https://example.invalid/news"}],
    "Price: $42.5; Currency: USD; unknown metadata",
])
def test_import_preserves_the_original_json_payload(payload, tmp_path):
    source = write_source(tmp_path / "source.json", payload)
    output = tmp_path / "archive"
    import_fixture(source, output)
    assert ToolTape(output / "tapes", "replay").invoke("get_stock_price", {"ticker": "AAPL"}, forbidden) == payload


def test_import_preserves_the_source_file_bytes(tmp_path):
    source = write_source(tmp_path / "source.json", {"price": 42})
    original = source.read_bytes()
    import_fixture(source, tmp_path / "archive")
    assert source.read_bytes() == original


def test_import_rejects_paths_outside_the_selected_workspace(tmp_path):
    from .import_archive import import_sources
    source = write_source(tmp_path / "source.json", {"price": 42})
    with pytest.raises(ValueError, match="archive_path_outside_workspace"):
        import_sources([source], tmp_path.parent / "outside-archive")


def test_provenance_hashes_the_source_file_and_original_payload(tmp_path):
    payload = {"price": 42.5, "currency": "USD"}
    source = write_source(tmp_path / "source.json", payload)
    output = tmp_path / "archive"
    import_fixture(source, output)
    record = ToolTape(output / "tapes", "replay").records()[0]
    origin = record["provenance"]["sources"][0]
    assert origin["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert origin["payload_sha256"] == _hash(payload)
    assert origin["json_pointer"] == "/records/dataset_test/output"


def test_import_omits_non_tool_private_context(tmp_path):
    source = write_source(tmp_path / "source.json", {"price": 42})
    output = tmp_path / "archive"
    import_fixture(source, output)
    all_files = list(output.rglob("*.json"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in all_files)
    assert all(value not in text for value in ("private-owner", "private-session", "private-user-query"))


def test_import_preserves_query_when_it_is_an_explicit_tool_parameter(tmp_path):
    source = write_source(tmp_path / "source.json", "opaque archived source text", tool="search")
    data = json.loads(source.read_text(encoding="utf-8"))
    data["records"]["dataset_test"]["inputs"] = {"query": "TEST_A filing"}
    source.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "archive"
    import_fixture(source, output)
    assert ToolTape(output / "tapes", "replay").invoke("search", {"query": "TEST_A filing"}, forbidden) == "opaque archived source text"


def test_legacy_record_declares_unavailable_producer_capture(tmp_path):
    source = write_source(tmp_path / "source.json", "opaque archived source text")
    output = tmp_path / "archive"
    import_fixture(source, output)
    record = ToolTape(output / "tapes", "replay").records()[0]
    assert record["producer_outputs"] == []
    assert record["producer_capture"] == {"status": "unavailable", "reason": "archived_unstructured_origin"}


def test_synthetic_test_sources_remain_labelled_synthetic(tmp_path):
    source = write_source(tmp_path / "source.json", {"price": 42})
    output = tmp_path / "archive"
    import_fixture(source, output)
    record = ToolTape(output / "tapes", "replay").records()[0]
    assert record["provenance"]["sources"][0]["synthetic"] is True


def test_conflicting_payloads_keep_variants_and_explicit_first_source_freeze(tmp_path):
    from .import_archive import import_sources
    first = write_source(tmp_path / "first.json", {"price": 42})
    second = write_source(tmp_path / "second.json", {"price": 99})
    output = tmp_path / "archive"
    manifest = import_sources([first, second], output)
    key = _hash({"tool": "get_stock_price", "arguments": {"ticker": "AAPL"}})
    entry = manifest["keys"][key]
    assert entry["conflict"] is True
    assert len(entry["variants"]) == 2
    assert ToolTape(output / "tapes", "replay").invoke("get_stock_price", {"ticker": "AAPL"}, forbidden) == {"price": 42}
    for variant in entry["variants"]:
        path = output / variant["path"]
        record = ToolTape(path.parent, "replay").records()[0]
        assert record["raw_output"] in ({"price": 42}, {"price": 99})


def test_schema_defaults_only_normalize_protocol_arguments(tmp_path):
    from .import_archive import normalize_arguments
    args = {"ticker": "aapl", "query": "Do not interpret this text"}
    schema = {"type": "object", "properties": {"ticker": {"type": "string"},
              "query": {"type": "string"}, "limit": {"type": "integer", "default": 5}}}
    before = deepcopy(args)
    assert normalize_arguments(args, schema) == {**args, "limit": 5}
    assert args == before


def test_import_uses_schema_defaults_and_preserves_original_inputs(tmp_path):
    source = write_source(tmp_path / "source.json", [{"title": "synthetic"}], tool="get_company_news")
    schema = {"get_company_news": {"properties": {"ticker": {"type": "string"},
              "limit": {"type": "integer", "default": 5}}}}
    output = tmp_path / "archive"
    import_fixture(source, output, schemas=schema)
    record = ToolTape(output / "tapes", "replay").records()[0]
    assert record["arguments"] == {"ticker": "AAPL", "limit": 5}
    assert record["provenance"]["sources"][0]["original_inputs"] == {"ticker": "AAPL"}


def test_import_never_installs_or_calls_producer_hooks(tmp_path, monkeypatch):
    import socket
    from . import capture
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: forbidden({}))
    monkeypatch.setattr(capture, "capture_producers", lambda *_args, **_kwargs: forbidden({}))
    source = write_source(tmp_path / "source.json", {"price": 42})
    output = tmp_path / "archive"
    import_fixture(source, output)
    assert ToolTape(output / "tapes", "replay").invoke("get_stock_price", {"ticker": "AAPL"}, forbidden) == {"price": 42}


def test_market_api_import_preserves_the_raw_data_at_its_original_pointer(tmp_path):
    payload = {"ticker": "SOXX", "kline_data": [{"time": "2026-11-06", "close": 100.5}],
               "source": "synthetic-unit-test", "price_basis": "unknown"}
    source = tmp_path / "market-data.json"
    source.write_text(json.dumps([{"synthetic": True, "ticker": "SOXX", "period": "max", "interval": "1wk",
                     "retrieved_at": "2026-11-07T00:00:00Z", "response": {"success": True, "data": payload}}]), encoding="utf-8")
    output = tmp_path / "archive"
    import_fixture(source, output)
    record = ToolTape(output / "tapes", "replay").records()[0]
    assert record["raw_output"] == payload
    assert record["tool"] == "get_stock_historical_data"
    assert record["provenance"]["sources"][0]["json_pointer"] == "/0/response/data"


def test_an_existing_freeze_cannot_be_silently_replaced(tmp_path):
    from .import_archive import import_sources
    first = write_source(tmp_path / "first.json", {"price": 42})
    second = write_source(tmp_path / "second.json", {"price": 99})
    output = tmp_path / "archive"
    import_sources([first, second], output)
    original = next((output / "tapes").glob("*.json")).read_bytes()
    with pytest.raises(ValueError, match="archive_freeze_conflict"):
        import_sources([second, first], output)
    assert next((output / "tapes").glob("*.json")).read_bytes() == original


def test_reimporting_the_same_sources_preserves_all_archive_bytes(tmp_path):
    source = write_source(tmp_path / "source.json", {"price": 42})
    output = tmp_path / "archive"
    import_fixture(source, output)
    before = {path.relative_to(output): path.read_bytes() for path in output.rglob("*.json")}
    import_fixture(source, output)
    after = {path.relative_to(output): path.read_bytes() for path in output.rglob("*.json")}
    assert after == before


def test_source_reader_rejects_paths_outside_the_declared_workspace(tmp_path):
    from .import_archive import read_source
    outside = tmp_path.parent / "outside-source.json"
    with pytest.raises(ValueError, match="archive_path_outside_workspace"):
        read_source(outside)
