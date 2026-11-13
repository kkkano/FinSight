"""离线导入明确指定的历史工具录制，保留原载荷、冲突版本及来源摘要。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
if not __package__:
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "tests"))
    from agent_eval.tapes import ToolTape, _hash, canonical_json
else:
    from .tapes import ToolTape, _hash, canonical_json


_PRIVATE_CONTEXT = {
    "owner", "session_id", "user_id", "query", "messages", "prompt", "reasoning", "thinking",
    "credentials", "authorization", "headers", "api_key", "environment", "secrets",
}
_SOURCE_FIELDS = {
    "source_id", "title", "url", "source", "publisher", "as_of", "published_at", "confidence",
    "kind", "type", "reliability", "currency", "unit", "period", "price_basis",
    "dividends_included", "limitations",
}


def normalize_arguments(arguments: dict, schema: dict | None = None) -> dict:
    """仅补协议声明的默认值；不解释文本、不改主体、不扩充参数别名。"""
    if type(arguments) is not dict:
        raise ValueError("archive_arguments_not_object")
    result = deepcopy(arguments)
    for name, specification in (schema or {}).get("properties", {}).items():
        if name not in result and "default" in specification:
            result[name] = deepcopy(specification["default"])
    canonical_json(result)
    return result


def _workspace_path(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(REPO):
        raise ValueError("archive_path_outside_workspace")
    return resolved


def _pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _record_containers(node, pointer=""):
    if isinstance(node, dict):
        if isinstance(node.get("records"), dict):
            yield pointer, node
            return
        for key, value in node.items():
            if key.lower() not in _PRIVATE_CONTEXT:
                yield from _record_containers(value, pointer + "/" + _pointer_part(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _record_containers(value, pointer + "/" + str(index))


@dataclass
class ArchivedCall:
    tool: str
    inputs: dict
    output: object
    status: str
    origin: dict
    recorded_at: str | None = None
    sources: list = field(default_factory=list)
    producer_outputs: list = field(default_factory=list)
    producer_capture: dict = field(default_factory=lambda: {
        "status": "unavailable", "reason": "archived_unstructured_origin"})


def _origin(path: Path, source_hash: str, pointer: str, payload, inputs: dict, *, synthetic=False) -> dict:
    return {"source_path": path.relative_to(REPO).as_posix(), "source_sha256": source_hash,
            "json_pointer": pointer, "payload_sha256": _hash(payload),
            "original_inputs": deepcopy(inputs), "synthetic": bool(synthetic)}


def read_source(path: str | Path) -> tuple[dict, list[ArchivedCall]]:
    source = _workspace_path(path)
    raw_bytes = source.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    data = json.loads(raw_bytes.decode("utf-8"))
    calls = []
    for pointer, snapshot in _record_containers(data):
        for ref, record in snapshot["records"].items():
            if not isinstance(record, dict) or not isinstance(record.get("tool"), str) or "output" not in record:
                raise ValueError("archive_invalid_tool_record")
            inputs = record.get("inputs")
            if type(inputs) is not dict or not isinstance(record.get("status"), str):
                raise ValueError("archive_invalid_tool_record")
            output = deepcopy(record["output"])
            canonical_json(output)
            original_sources = snapshot.get("sources", {})
            linked = [
                {name: deepcopy(value) for name, value in item.items() if name in _SOURCE_FIELDS}
                for item in original_sources.values()
                if isinstance(item, dict) and item.get("data_ref") == ref
            ] if isinstance(original_sources, dict) else []
            calls.append(ArchivedCall(record["tool"], deepcopy(inputs), output, record["status"],
                _origin(source, source_hash, pointer + "/records/" + _pointer_part(ref) + "/output",
                        output, inputs, synthetic=snapshot.get("synthetic", data.get("synthetic", False) if isinstance(data, dict) else False)),
                recorded_at=record.get("recorded_at") or snapshot.get("recorded_at"), sources=linked,
                producer_outputs=deepcopy(record.get("producer_outputs", [])),
                producer_capture=deepcopy(record.get("producer_capture") or {
                    "status": "unavailable", "reason": "archived_unstructured_origin"})))
    # 该有限格式为已确认的生产行情 API 归档，不从市场正文或文件名推断意图。
    if not calls and isinstance(data, list):
        for index, item in enumerate(data):
            if (not isinstance(item, dict) or not all(key in item for key in ("ticker", "period", "interval", "response"))
                    or not isinstance(item["response"], dict) or not isinstance(item["response"].get("data"), dict)):
                raise ValueError("archive_unknown_source_format")
            inputs = {name: item[name] for name in ("ticker", "period", "interval")}
            output = deepcopy(item["response"]["data"])
            if not isinstance(output.get("kline_data"), list):
                raise ValueError("archive_unknown_source_format")
            calls.append(ArchivedCall("get_stock_historical_data", inputs, output,
                str(output.get("status") or "success"),
                _origin(source, source_hash, "/" + str(index) + "/response/data", output, inputs,
                        synthetic=item.get("synthetic", False)), recorded_at=item.get("retrieved_at"),
                producer_outputs=[{"producer": "archived_production_api", "method": "kline_response",
                    "arguments": deepcopy(inputs), "status": "captured", "data_format": "json", "data": deepcopy(output)}],
                producer_capture={"status": "captured", "captured_count": 1, "reason": "archived_production_api_response"}))
    if not calls:
        raise ValueError("archive_no_tool_records")
    return {"path": source.relative_to(REPO).as_posix(), "sha256": source_hash, "records": len(calls)}, calls


def _write_new(path: Path, value) -> None:
    encoded = canonical_json(value) + "\n"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError("archive_existing_record_conflict")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def import_sources(sources: list[str | Path], output: str | Path, *, schemas: dict | None = None) -> dict:
    target = _workspace_path(output)
    schemas = schemas or {}
    tape = ToolTape(target / "tapes", "replay")
    manifest = {"schema_version": 1, "freeze_policy": "first_source_in_explicit_order_then_record_order",
                "source_order": [], "keys": {}}
    variants = {}
    for source in sources:
        source_meta, calls = read_source(source)
        manifest["source_order"].append(source_meta)
        for call in calls:
            arguments = normalize_arguments(call.inputs, schemas.get(call.tool))
            key = _hash({"tool": call.tool, "arguments": arguments})
            variant_id = _hash({"tool": call.tool, "arguments": arguments, "raw_output": call.output,
                               "original_status": call.status, "producer_outputs": call.producer_outputs,
                               "producer_capture": call.producer_capture})
            if (key, variant_id) not in variants:
                record = tape._record(key, call.tool, arguments, call.output,
                    producer_outputs=call.producer_outputs, producer_capture=call.producer_capture)
                record.pop("checksum")
                record["recorded_at"] = call.recorded_at
                record["provenance"] = {"variant_id": variant_id, "original_status": call.status, "sources": []}
                if call.sources:
                    record["result"]["sources"] = deepcopy(call.sources)
                variants[key, variant_id] = record
                entry = manifest["keys"].setdefault(key, {"tool": call.tool, "arguments": arguments,
                    "selected_variant": variant_id, "conflict": False, "variants": []})
                entry["variants"].append({"id": variant_id,
                    "path": f"variants/{variant_id[:12]}/{key}.json", "payload_sha256": _hash(call.output)})
                entry["conflict"] = len(entry["variants"]) > 1
            variants[key, variant_id]["provenance"]["sources"].append(call.origin)
    for record in variants.values():
        record["checksum"] = _hash(record)
    # 写入前先检查所有冻结键，拒绝用不同来源顺序暗中替换已有版本。
    for key, entry in manifest["keys"].items():
        selected_path = target / "tapes" / (key + ".json")
        if selected_path.exists():
            existing = tape._read(selected_path)
            if existing.get("provenance", {}).get("variant_id") != entry["selected_variant"]:
                raise ValueError("archive_freeze_conflict")
    for key, entry in manifest["keys"].items():
        for variant in entry["variants"]:
            _write_new(target / variant["path"], variants[key, variant["id"]])
        _write_new(target / "tapes" / (key + ".json"), variants[key, entry["selected_variant"]])
    _write_new(target / "provenance.json", manifest)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, help="明确选择的有限历史录制文件；顺序决定冻结版本。")
    parser.add_argument("--output", default=str(REPO / "tests/agent_eval/fixtures/archive-v1"))
    parser.add_argument("--schemas", help="可选的工具参数 JSON schema 表；只用于补默认值。")
    args = parser.parse_args(argv)
    schemas = json.loads(_workspace_path(args.schemas).read_text(encoding="utf-8")) if args.schemas else None
    manifest = import_sources(args.source, args.output, schemas=schemas)
    print(json.dumps({"sources": len(manifest["source_order"]), "keys": len(manifest["keys"]),
        "variants": sum(len(item["variants"]) for item in manifest["keys"].values()),
        "conflicts": sum(item["conflict"] for item in manifest["keys"].values())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
