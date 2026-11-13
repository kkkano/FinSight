"""离线 SEC 派生录制的来源、时点、精确参数和零网络合同。"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import socket

import pytest

from .materialize import SecSnapshots, blocked_network, file_sha, materialize, observed_calls
from .tapes import ToolTape, _hash, canonical_json


SOURCE = (Path(__file__).parent / "fixtures/vectide-matched-20261113/facts-02"
          / "379e7c4c72cfbb34210c6ca58145e5ac44c3972b3724f92c810eb895490325a3.json")
SNAPSHOT_DATE = date(2026, 11, 13)
TOOL = "get_sec_company_facts_quarterly"


@pytest.fixture
def source():
    before = file_sha(SOURCE)
    yield SOURCE
    assert file_sha(SOURCE) == before


def observed_report(tmp_path, calls):
    events = [{"type": "tool.started", "run_id": "run-facts-02", "event_id": f"event-{i}",
               "payload": {"name": name, "inputs": arguments}}
              for i, (name, arguments) in enumerate(calls)]
    event_path = tmp_path / "events.json"
    event_path.write_text(json.dumps(events), encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"results": [{"id": "facts-02", "events_path": "events.json",
                       "turns": [{"run_id": "run-facts-02"}]}]}), encoding="utf-8")
    return report


def prepare(tmp_path, source, calls):
    return materialize(report_path=observed_report(tmp_path, calls), case_id="facts-02",
        source_paths=[source], snapshot_date=SNAPSHOT_DATE, output_dir=tmp_path / "tapes",
        manifest_path=tmp_path / "manifest.json", repo=tmp_path)


def test_original_limit_four_is_exactly_reproduced_from_captured_http(source):
    original = json.loads(source.read_text(encoding="utf-8"))
    derived = SecSnapshots([source], SNAPSHOT_DATE).derive(original["arguments"])
    assert derived["status"] == "derived"
    assert derived["raw_output"] == original["raw_output"]
    assert derived["network_attempts"] == 0
    assert len(derived["http_snapshots"]) == 2


def test_new_limit_six_uses_full_snapshot_and_restores_cache_and_date(source, monkeypatch):
    from backend.tools import sec

    prior_cache, prior_date = {"PRIVATE_CACHE": {"cik": "fake"}}, sec.date
    monkeypatch.setattr(sec, "_ticker_cache", prior_cache)
    monkeypatch.setattr(sec, "_ticker_cache_expire_at", float("inf"))
    arguments = {"ticker": "MSFT", "limit": 6}
    untouched = deepcopy(arguments)
    derived = SecSnapshots([source], SNAPSHOT_DATE).derive(arguments)
    assert derived["status"] == "derived" and derived["network_attempts"] == 0
    assert len(derived["raw_output"]["periods"]) == 6
    assert len(derived["raw_output"]["revenue"]) == 6
    assert arguments == untouched
    assert derived["raw_output"]["request_time_scope"] == {}
    assert sec.date is prior_date and sec._ticker_cache is prior_cache
    assert sec._ticker_cache_expire_at == float("inf")


def test_explicit_historical_as_of_filters_by_disclosure_without_changing_arguments(source):
    scope = {"as_of": "2025-01-01"}
    args = {"ticker": "MSFT", "limit": 6, "time_scope": scope}
    derived = SecSnapshots([source], SNAPSHOT_DATE).derive(args)
    raw = derived["raw_output"]
    assert derived["network_attempts"] == 0
    assert raw["request_time_scope"] == scope
    assert raw["source_latest_filed"] <= scope["as_of"]
    assert max(raw["periods"]) <= scope["as_of"]
    assert all(fact["filed"] <= scope["as_of"] for facts in raw["fact_metadata"].values()
               for fact in facts if fact)


def test_as_of_after_snapshot_is_rejected_without_tape(tmp_path, source):
    with pytest.raises(ValueError, match="materialize_as_of_after_snapshot"):
        prepare(tmp_path, source, [(TOOL, {"ticker": "MSFT", "limit": 6,
                                          "time_scope": {"as_of": "2026-11-14"}})])
    assert not (tmp_path / "tapes").exists()


def test_snapshot_date_cannot_claim_information_after_capture(source):
    with pytest.raises(ValueError, match="materialize_snapshot_after_capture"):
        SecSnapshots([source], date(2026, 11, 14))


def test_unknown_companyfacts_url_records_gap_without_creating_tape(tmp_path, source):
    result = prepare(tmp_path, source, [(TOOL, {"ticker": "AAPL", "limit": 6})])
    assert result["network_attempts"] == 0
    assert result["rows"][0]["status"] == "gap"
    assert result["rows"][0]["gaps"] == [{
        "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        "reason": "http_snapshot_missing"}]
    assert not (tmp_path / "tapes").exists()


def test_source_checksum_is_verified_before_deriving(tmp_path, source):
    record = json.loads(source.read_text(encoding="utf-8"))
    record["raw_output"]["revenue"][0] += 1
    changed = tmp_path / source.name
    changed.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="tape_corrupt"):
        SecSnapshots([changed], SNAPSHOT_DATE)


def test_conflicting_responses_for_identical_url_are_rejected(tmp_path, source):
    record = json.loads(source.read_text(encoding="utf-8"))
    record["arguments"]["limit"] = 5
    record["key"] = _hash({"tool": TOOL, "arguments": record["arguments"]})
    record["producer_outputs"][1]["data"]["entityName"] = "CONFLICTING COMPANY"
    record.pop("checksum")
    record["checksum"] = _hash(record)
    other = tmp_path / (record["key"] + ".json")
    other.write_text(canonical_json(record), encoding="utf-8")
    with pytest.raises(ValueError, match="materialize_conflicting_http_snapshot"):
        SecSnapshots([source, other], SNAPSHOT_DATE)


def test_materialized_key_and_provenance_replay_exactly_while_search_stays_missing(tmp_path, source):
    arguments = {"ticker": "MSFT", "limit": 6}
    search = {"query": "unrecorded exact query"}
    result = prepare(tmp_path, source, [(TOOL, arguments), (TOOL, {"limit": 6, "ticker": "MSFT"}),
                                       ("search", search)])
    assert len(result["rows"]) == 1 and result["network_attempts"] == 0
    key = _hash({"tool": TOOL, "arguments": arguments})
    assert result["rows"][0]["key"] == key
    assert result["rows"][0]["status"] == "materialized"
    path = tmp_path / "tapes" / (key + ".json")
    tape = ToolTape(path.parent, "replay")
    record = tape._read(path)
    assert record["arguments"] == arguments and len(record["raw_output"]["periods"]) == 6
    assert record["result"]["data"] == record["raw_output"]
    assert len(record["producer_outputs"]) == 2
    assert record["derivation"]["sources"][0]["sha256"] == file_sha(source)
    assert record["derivation"]["snapshot_date"] == "2026-11-13"
    assert record["derivation"]["network_attempts"] == 0
    assert record["derivation"]["observation"]["unsupported_tools_not_materialized"] == ["search"]
    assert len(record["derivation"]["parser_files"]) == 3

    def forbidden(_args):
        raise AssertionError("回放不得运行物化器或联网")

    assert tape.invoke(TOOL, arguments, forbidden) == record["raw_output"]
    assert tape.invoke(TOOL, arguments, forbidden, project=tape.project_envelope)["status"] == "ok"
    assert tape.invoke("search", search, forbidden)["error_code"] == "tape_miss"
    assert tape.invoke(TOOL, {"ticker": "MSFT", "limit": 5}, forbidden)["error_code"] == "tape_miss"
    assert len(list(path.parent.glob("*.json"))) == 1


def test_existing_tape_and_manifest_are_never_overwritten(tmp_path, source):
    arguments = {"ticker": "MSFT", "limit": 6}
    prepare(tmp_path, source, [(TOOL, arguments)])
    path = next((tmp_path / "tapes").glob("*.json"))
    before = path.read_bytes()
    manifest = tmp_path / "manifest.json"
    manifest_before = manifest.read_bytes()
    kwargs = dict(report_path=tmp_path / "report.json", case_id="facts-02", source_paths=[source],
                  snapshot_date=SNAPSHOT_DATE, output_dir=path.parent, repo=tmp_path)
    with pytest.raises(FileExistsError):
        materialize(**kwargs, manifest_path=manifest)
    result = materialize(**kwargs, manifest_path=tmp_path / "second_manifest.json")
    assert result["rows"][0]["status"] == "existing_not_overwritten"
    assert path.read_bytes() == before and manifest.read_bytes() == manifest_before


def test_complete_observed_parameters_remain_in_key_without_injected_as_of(tmp_path, source):
    arguments = {"ticker": "MSFT", "limit": 4, "calculations": [
        {"metric": "revenue", "concept": "Revenues"},
        {"metric": "operating_cash_flow", "concept": "NetCashProvidedByUsedInOperatingActivities"}]}
    result = prepare(tmp_path, source, [(TOOL, arguments)])
    key = _hash({"tool": TOOL, "arguments": arguments})
    assert result["rows"][0]["key"] == key
    record = ToolTape(tmp_path / "tapes", "replay")._read(tmp_path / "tapes" / (key + ".json"))
    assert record["arguments"] == arguments
    assert "time_scope" not in record["arguments"]
    assert record["raw_output"]["request_time_scope"] == {}
    assert len(record["raw_output"]["periods"]) == 4


def test_only_selected_case_actual_event_payloads_supply_parameters(tmp_path):
    path = observed_report(tmp_path, [(TOOL, {"ticker": "MSFT", "limit": 6})])
    events = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    events.extend([{"type": "tool.started", "run_id": "other-case", "payload": {
        "name": TOOL, "inputs": {"ticker": "AAPL", "limit": 8}}},
        {"type": "tool.result", "run_id": "run-facts-02", "payload": {
        "name": TOOL, "inputs": {"ticker": "MSFT", "limit": 10}}}])
    (tmp_path / "events.json").write_text(json.dumps(events), encoding="utf-8")
    calls, observation = observed_calls(path, "facts-02", tmp_path)
    assert [call["arguments"] for call in calls] == [{"ticker": "MSFT", "limit": 6}]
    assert observation["events_sha256"] == file_sha(tmp_path / "events.json")


def test_socket_guard_counts_and_blocks_a_connection():
    with blocked_network() as network:
        with pytest.raises(RuntimeError, match="materialize_network_forbidden"):
            socket.create_connection(("example.invalid", 443))
    assert network["attempts"] == 1


def test_swallowed_network_attempt_still_rejects_materialization(tmp_path, source, monkeypatch):
    from backend.tools import sec

    def unsafe_parser(ticker, limit):
        try:
            socket.create_connection(("example.invalid", 443))
        except RuntimeError:
            pass
        return {"ticker": ticker, "periods": ["2026-09-30"], "error": None}

    monkeypatch.setattr(sec, "get_sec_company_facts_quarterly", unsafe_parser)
    with pytest.raises(ValueError, match="materialize_network_access_attempted"):
        prepare(tmp_path, source, [(TOOL, {"ticker": "MSFT", "limit": 6})])
    assert not (tmp_path / "tapes").exists()
