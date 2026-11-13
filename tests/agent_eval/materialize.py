"""显式离线扩展已观察的 SEC 参数；不参与回放，也不补造缺失的 HTTP 数据。"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "tests"))
    from agent_eval.tapes import ToolTape, _hash, canonical_json
else:
    from .tapes import ToolTape, _hash, canonical_json

TOOL = "get_sec_company_facts_quarterly"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SnapshotGap(RuntimeError):
    pass


@contextmanager
def blocked_network():
    """连 DNS 和已有 socket 的发送也拒绝；计数会暴露被解析器吞掉的异常。"""
    state = {"attempts": 0}

    def deny(*_args, **_kwargs):
        state["attempts"] += 1
        raise RuntimeError("materialize_network_forbidden")

    with ExitStack() as stack:
        for name in ("create_connection", "getaddrinfo"):
            stack.enter_context(patch.object(socket, name, deny))
        for name in ("connect", "connect_ex", "send", "sendall", "sendto"):
            stack.enter_context(patch.object(socket.socket, name, deny))
        yield state


def _sec_json_url(url: str) -> bool:
    if url == "https://www.sec.gov/files/company_tickers.json":
        return True
    parsed = urlsplit(url)
    prefix, suffix = "/api/xbrl/companyfacts/CIK", ".json"
    cik = parsed.path.removeprefix(prefix).removesuffix(suffix)
    return (parsed.scheme == "https" and parsed.netloc == "data.sec.gov"
            and not parsed.query and not parsed.fragment and parsed.path == prefix + cik + suffix
            and len(cik) == 10 and cik.isascii() and cik.isdigit())


class SecSnapshots:
    def __init__(self, paths: list[Path], snapshot_date: date):
        self.snapshot_date = snapshot_date
        self.sources, self.responses = [], {}
        for path in paths:
            path = Path(path).resolve()
            before = file_sha(path)
            record = ToolTape(path.parent, "replay")._read(path)
            if file_sha(path) != before:
                raise ValueError("materialize_source_changed")
            if record["tool"] != TOOL or record.get("injected"):
                raise ValueError("materialize_invalid_source_tool")
            captured_date = datetime.fromisoformat(record["recorded_at"]).date()
            if snapshot_date > captured_date:
                raise ValueError("materialize_snapshot_after_capture")
            source = {"path": str(path), "sha256": before, "checksum": record["checksum"],
                      "recorded_at": record["recorded_at"], "key": record["key"]}
            self.sources.append(source)
            for index, item in enumerate(record.get("producer_outputs", [])):
                if (item.get("producer") != "requests.Response" or item.get("method") != "json"
                        or item.get("status") != "captured" or item.get("data_format") != "json"):
                    continue
                metadata = item.get("arguments") or {}
                url, status = metadata.get("url"), metadata.get("status_code")
                if not isinstance(url, str) or not _sec_json_url(url) or type(status) is not int:
                    continue
                identity = _hash({"status_code": status, "data": item.get("data")})
                if url in self.responses and self.responses[url]["sha256"] != identity:
                    raise ValueError("materialize_conflicting_http_snapshot:" + url)
                response = self.responses.setdefault(url, {"sha256": identity, "item": deepcopy(item), "origins": []})
                response["origins"].append({"source_sha256": before, "source_path": str(path),
                                            "producer_index": index, "producer_sha256": _hash(item)})
        if not self.sources:
            raise ValueError("materialize_source_required")

    def verify_unchanged(self):
        if any(file_sha(Path(source["path"])) != source["sha256"] for source in self.sources):
            raise ValueError("materialize_source_changed")

    def derive(self, arguments: dict) -> dict:
        from backend.tools import sec

        canonical_json(arguments)
        inspect.signature(sec.get_sec_company_facts_quarterly).bind(**arguments)
        scope = arguments.get("time_scope") or {}
        if not isinstance(scope, dict):
            raise ValueError("materialize_invalid_time_scope")
        as_of = sec.fact_date(scope.get("as_of"))
        if scope.get("as_of") is not None and as_of is None:
            raise ValueError("materialize_invalid_as_of")
        if as_of is not None and as_of > self.snapshot_date.isoformat():
            raise ValueError("materialize_as_of_after_snapshot")
        used, gaps = [], []
        snapshots = self

        class FrozenDate(date):
            @classmethod
            def today(cls):
                return cls.fromisoformat(snapshots.snapshot_date.isoformat())

        class Response:
            def __init__(self, url, response):
                self.url, self.response = url, response
                self.status_code = response["item"]["arguments"]["status_code"]

            def json(self):
                used.append(self.url)
                return deepcopy(self.response["item"]["data"])

        def get(url, **kwargs):
            if url not in self.responses or kwargs.get("params") not in (None, {}):
                gaps.append({"url": url, "reason": "http_snapshot_missing"})
                raise SnapshotGap("materialize_http_snapshot_missing")
            return Response(url, self.responses[url])

        with blocked_network() as network, patch.object(sec, "_http_get", get), \
                patch.object(sec, "_ticker_cache", {}), patch.object(sec, "_ticker_cache_expire_at", 0.0), \
                patch.object(sec, "date", FrozenDate), \
                patch.dict(os.environ, {"SEC_USER_AGENT": "FinSight offline-eval@example.invalid"}):
            raw = sec.get_sec_company_facts_quarterly(**deepcopy(arguments))
        self.verify_unchanged()
        if network["attempts"]:
            raise ValueError("materialize_network_access_attempted")
        if gaps:
            return {"status": "gap", "gaps": gaps, "network_attempts": 0}
        if not isinstance(raw, dict) or raw.get("error"):
            return {"status": "gap", "gaps": [{"reason": "parser_result_unavailable", "error": raw.get("error")
                    if isinstance(raw, dict) else "invalid_result"}], "network_attempts": 0}
        used = list(dict.fromkeys(used))
        return {"status": "derived", "raw_output": raw, "network_attempts": 0,
                "producer_outputs": [deepcopy(self.responses[url]["item"]) for url in used],
                "http_snapshots": [{"url": url, "sha256": self.responses[url]["sha256"],
                                    "origins": self.responses[url]["origins"]} for url in used]}


def observed_calls(report_path: Path, case_id: str, repo: Path = REPO) -> tuple[list[dict], dict]:
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cases = [case for case in report["results"] if case["id"] == case_id]
    if len(cases) != 1:
        raise ValueError("materialize_case_not_unique")
    case = cases[0]
    events_path = Path(case["events_path"])
    if not events_path.is_absolute():
        events_path = repo / events_path
    events_path = events_path.resolve()
    events = json.loads(events_path.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise ValueError("materialize_invalid_events")
    run_ids = {turn["run_id"] for turn in case["turns"]}
    calls, seen, unsupported = [], set(), set()
    for event in events:
        if event.get("type") != "tool.started" or event.get("run_id") not in run_ids:
            continue
        payload = event.get("payload") or {}
        if payload.get("name") != TOOL:
            if isinstance(payload.get("name"), str):
                unsupported.add(payload["name"])
            continue
        arguments = payload.get("inputs")
        if type(arguments) is not dict:
            raise ValueError("materialize_invalid_observed_arguments")
        key = _hash({"tool": TOOL, "arguments": arguments})
        if key not in seen:
            calls.append({"tool": TOOL, "arguments": deepcopy(arguments), "key": key,
                          "event_id": event.get("event_id"), "event_sha256": _hash(event)})
            seen.add(key)
    return calls, {"report_path": str(report_path), "report_sha256": file_sha(report_path),
                   "events_path": str(events_path), "events_sha256": file_sha(events_path),
                   "case_id": case_id, "unsupported_tools_not_materialized": sorted(unsupported)}


def _exclusive_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(value) + "\n")


def materialize(*, report_path: Path, case_id: str, source_paths: list[Path], snapshot_date: date,
                output_dir: Path, manifest_path: Path, repo: Path = REPO) -> dict:
    """只有调用此准备命令才生成文件；精确回放缺失仍由 ToolTape 自己报告。"""
    manifest_path, output_dir = Path(manifest_path).resolve(), Path(output_dir).resolve()
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    if manifest_path.parent == output_dir:
        raise ValueError("materialize_manifest_must_be_outside_tapes")
    calls, observation = observed_calls(report_path, case_id, repo)
    snapshots = SecSnapshots(source_paths, snapshot_date)
    parser_files = [REPO / "backend/tools" / name for name in
                    ("sec.py", "financial_facts.py", "financial_calculations.py")]
    provenance = {"kind": "offline_sec_http_materialization", "snapshot_date": snapshot_date.isoformat(),
                  "sources": snapshots.sources, "observation": observation,
                  "parser_files": [{"path": str(path), "sha256": file_sha(path)} for path in parser_files],
                  "materializer_sha256": file_sha(Path(__file__)),
                  "tape_format_sha256": file_sha(Path(__file__).with_name("tapes.py"))}
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "provenance": provenance, "network_attempts": 0, "rows": []}
    tape = ToolTape(output_dir, "record")
    for call in calls:
        target = output_dir / (call["key"] + ".json")
        row = {"key": call["key"], "tool": TOOL, "arguments": call["arguments"], "path": str(target)}
        if target.exists():
            existing = tape._read(target)
            row.update(status="existing_not_overwritten", sha256=file_sha(target), checksum=existing["checksum"])
        else:
            derived = snapshots.derive(call["arguments"])
            if derived["status"] == "gap":
                row.update(status="gap", gaps=derived["gaps"])
            else:
                record = tape._record(call["key"], TOOL, call["arguments"], derived["raw_output"],
                    producer_outputs=derived["producer_outputs"], producer_capture={"status": "captured",
                    "captured_count": len(derived["producer_outputs"]), "unavailable_count": 0,
                    "reason": "offline_materialized_from_verified_http_snapshots"})
                record.pop("checksum")
                record["derivation"] = {**provenance, "event_id": call["event_id"],
                    "event_sha256": call["event_sha256"], "http_snapshots": derived["http_snapshots"],
                    "materialized_at": record["recorded_at"], "network_attempts": 0}
                record["checksum"] = _hash(record)
                snapshots.verify_unchanged()
                _exclusive_json(target, record)
                row.update(status="materialized", sha256=file_sha(target), checksum=record["checksum"])
        manifest["rows"].append(row)
    snapshots.verify_unchanged()
    _exclusive_json(manifest_path, manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--source-record", type=Path, action="append", required=True)
    parser.add_argument("--snapshot-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = materialize(report_path=args.report, case_id=args.case, source_paths=args.source_record,
        snapshot_date=args.snapshot_date, output_dir=args.output_dir, manifest_path=args.manifest)
    print(json.dumps({"network_attempts": result["network_attempts"],
                      "rows": [{"key": row["key"], "status": row["status"]} for row in result["rows"]]}))
