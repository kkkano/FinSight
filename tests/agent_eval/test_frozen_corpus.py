"""冻结语料与生产者合同；synthetic fixtures不作为真实金融数据证据。"""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("frozen_test", Path(__file__).with_name("frozen_corpus_provider.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def source(root, name, arguments, raw, producers):
    tape = module.ToolTape(root, "record")
    tape.invoke(name, arguments, lambda _args: raw)
    path = next(root.glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["producer_outputs"] = producers
    data.pop("checksum")
    data["checksum"] = module.checksum(data)
    path.write_text(module.canonical_json(data), encoding="utf-8")


def producer(name, method, arguments, data):
    return {"producer": name, "method": method, "arguments": arguments, "data": data,
            "status": "captured", "data_format": "json"}


def test_different_actual_queries_search_same_complete_corpus_without_keyword_intent_rules(tmp_path):
    articles = [{"title": "Alpha revenue cash flow", "url": "https://example.invalid/alpha", "text": "ALPHA revenue is 42. Cash flow is 17."},
                {"title": "Beta market risks", "url": "https://example.invalid/beta", "text": "BETA market risk and debt exposure."}]
    source(tmp_path / "source" / "a", "search", {"query": "original query"}, "captured",
           [producer("requests.Response", "json", {"url": "https://api.tavily.com/search", "status_code": 200}, {"results": articles})])
    module.build_corpus(tmp_path / "source", tmp_path / "corpus")
    corpus = module.FrozenCorpus(tmp_path / "corpus")
    assert corpus.search("ALPHA cash flow", 1)[0]["url"].endswith("alpha")
    assert corpus.search("BETA debt exposure", 1)[0]["url"].endswith("beta")
    result, proof = corpus.retrieve("search", {"query": "new ALPHA revenue query"}, lambda _args: pytest.fail("network callback"))
    assert result["source"] == "frozen_corpus" and result["query"] == "new ALPHA revenue query"
    assert proof["network_access"] is False
    assert corpus.by_url("https://example.invalid/alpha")[0]["content"] == articles[0]["text"]


def test_content_sha_dedup_retains_both_actual_urls_and_original_capture_origins(tmp_path):
    articles = [{"title": "one", "url": "https://example.invalid/one", "text": "same complete captured text"},
                {"title": "two", "url": "https://example.invalid/two", "text": "same complete captured text"}]
    source(tmp_path / "source" / "a", "search", {"query": "original"}, "captured",
           [producer("requests.Response", "json", {"url": "https://api.exa.ai/search", "status_code": 200}, {"results": articles})])
    manifest = module.build_corpus(tmp_path / "source", tmp_path / "corpus")
    assert len(manifest["documents"]) == 1
    corpus = module.FrozenCorpus(tmp_path / "corpus")
    assert corpus.by_url(articles[0]["url"])[0]["id"] == corpus.by_url(articles[1]["url"])[0]["id"]
    assert len(manifest["documents"][0]["origins"]) == 2


def test_actual_production_callback_uses_exact_captured_gateway_parameters(tmp_path):
    data = {"data": [{"close": 42}], "as_of": "2026-11-13T00:00:00Z"}
    source(tmp_path / "source" / "a", "get_stock_historical_data", {"ticker": "ALPHA", "period": "1y", "interval": "1d"}, data,
        [producer("market_data_gateway", "get_kline", {"symbol": "ALPHA", "period": "1y", "interval": "1d"}, data)])
    module.build_corpus(tmp_path / "source", tmp_path / "corpus")
    corpus = module.FrozenCorpus(tmp_path / "corpus")
    from backend.services.market_data_gateway import MarketDataGateway
    gateway = object.__new__(MarketDataGateway)
    def production_callback(arguments):
        return gateway.get_kline(arguments["ticker"], period=arguments["period"], interval=arguments["interval"])
    value, proof = corpus.reexecute("fixture_production", {"ticker": "ALPHA", "period": "1y", "interval": "1d"}, production_callback)
    assert value == data and proof["kind"] == "actual_production_function_offline_reexecution"
    assert proof["producer_inputs"][0]["arguments"] == {"symbol": "ALPHA", "period": "1y", "interval": "1d"}


def test_missing_producer_is_gap_never_filled_from_nearby_fields(tmp_path):
    source(tmp_path / "source" / "a", "get_stock_price", {"ticker": "ALPHA"}, {"price": 42}, [])
    module.build_corpus(tmp_path / "source", tmp_path / "corpus")
    corpus = module.FrozenCorpus(tmp_path / "corpus")
    from backend.services.market_data_gateway import MarketDataGateway
    gateway = object.__new__(MarketDataGateway)
    value, proof = corpus.reexecute("missing", {"ticker": "BETA"}, lambda arguments: gateway.get_quote(arguments["ticker"]))
    assert value["error_code"] == "frozen_corpus_gap" and "price" not in value
    assert proof["kind"] == "structured_data_gap"


def test_no_network_fallback_and_fixed_database_identity_are_enforced(tmp_path):
    source(tmp_path / "source" / "a", "get_stock_price", {"ticker": "ALPHA"}, {"price": 42}, [])
    module.build_corpus(tmp_path / "source", tmp_path / "corpus")
    corpus = module.FrozenCorpus(tmp_path / "corpus")
    import socket
    value, _ = corpus.reexecute("network", {}, lambda _args: socket.create_connection(("example.invalid", 80)))
    assert value["error_code"] == "frozen_corpus_gap"
    with (tmp_path / "corpus/corpus.sqlite").open("ab") as file:
        file.write(b"tampered")
    with pytest.raises(ValueError, match="frozen_corpus_database_changed"):
        module.FrozenCorpus(tmp_path / "corpus")


def test_explicit_mount_mapping_retains_database_manifest_original_bytes_and_rejects_escape(tmp_path, monkeypatch):
    source(tmp_path / "source" / "a", "get_stock_price", {"ticker": "ALPHA"}, {"price": 42}, [])
    manifest = module.build_corpus(tmp_path / "source", tmp_path / "corpus")
    shutil.copytree(tmp_path / "source", tmp_path / "mounted")
    original_manifest = (tmp_path / "corpus/manifest.json").read_bytes()
    original_database = (tmp_path / "corpus/corpus.sqlite").read_bytes()
    mapping = {"recorded_source_root": manifest["source_root"], "mounted_source_root": str(tmp_path / "mounted"),
               "corpus_manifest_sha256": module.file_sha(tmp_path / "corpus/manifest.json"),
               "database_sha256": manifest["database_sha256"]}
    path = tmp_path / "mount.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.setenv("FINSIGHT_EVAL_CORPUS_MOUNT_MANIFEST", str(path))
    corpus = module.FrozenCorpus(tmp_path / "corpus")
    record = corpus.exact("get_stock_price", {"ticker": "ALPHA"})
    assert record["raw_output"] == {"price": 42}
    assert corpus.original_record(0)["checksum"] == record["checksum"]
    with pytest.raises(ValueError, match="outside_mount"):
        corpus.source_path(str(tmp_path / "source/../../escape.json"))
    assert (tmp_path / "corpus/manifest.json").read_bytes() == original_manifest
    assert (tmp_path / "corpus/corpus.sqlite").read_bytes() == original_database
