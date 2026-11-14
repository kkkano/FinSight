"""新同语料decision层测量入口；原run.py/backend不变，金融来源全部来自冻结provider。"""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from agent_eval import run as runner
from agent_eval.tapes import ToolTape, _hash, canonical_json
from agent_eval.frozen_offline_worker import OfflineWorker

spec = importlib.util.spec_from_file_location("frozen_provider", Path(__file__).with_name("frozen_corpus_provider.py"))
provider_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider_module)

WORK = ContextVar("frozen_case_work", default=None)
ORIGINAL_RUN_CASE = runner.run_case
_CORPUS = None
_OFFLINE_WORKER = None


def corpus():
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = provider_module.FrozenCorpus(os.environ["FINSIGHT_EVAL_FROZEN_CORPUS_DIR"])
    return _CORPUS


def offline_worker():
    global _OFFLINE_WORKER
    if _OFFLINE_WORKER is None:
        _OFFLINE_WORKER = OfflineWorker(Path(os.environ["FINSIGHT_EVAL_FROZEN_CORPUS_DIR"]))
    return _OFFLINE_WORKER


def tagged(raw, provenance):
    if isinstance(raw, dict):
        result = deepcopy(raw)
        result["original_source_provider"] = result.get("source")
        result["source"] = "frozen_corpus"
        result["frozen_provenance"] = provenance
        return result
    return {"status": "ok" if raw else "empty", "source": "frozen_corpus", "content": deepcopy(raw),
            "frozen_provenance": provenance}


class FrozenTape(ToolTape):
    def __init__(self, path, mode, faults=None, **kwargs):
        super().__init__(path, "replay", faults, **kwargs)
        self.derived = {}
        self.provider = corpus()

    def invoke(self, name, arguments, callback, *, project=None):
        key = _hash({"tool": name, "arguments": arguments})
        with self._guard:
            cached = deepcopy(self.derived.get(key))
        if cached is not None:
            with self._guard:
                self._counts["hits"] += 1
            return cached["result"]
        if name in {"search_memory", "search_knowledge", "read_document", "get_watchlist"}:
            raw = callback(deepcopy(arguments))
            provenance = self.provider.marker({"kind": "evaluation_isolated_control_store"})
        elif name in self.faults:
            raw = deepcopy(self.faults[name])
            provenance = self.provider.marker({"kind": "same_explicit_case_fault"})
        else:
            raw, provenance = offline_worker().retrieve(name, deepcopy(arguments))
        envelope = None
        exact = self.provider.exact(name, arguments) if provenance["kind"] == "exact_original_snapshot" else None
        if project:
            if exact is not None:
                envelope = self.project_envelope(name, arguments, exact)
            else:
                from backend.agent_runtime.adapters import adapt_result
                envelope = adapt_result(name, raw, arguments).model_dump(mode="json")
            envelope["notes"] = list(envelope.get("notes", [])) + ["本条来自frozen_corpus冻结原件/离线生产函数，不是新的网络查询。"]
            if isinstance(envelope.get("data"), dict):
                envelope["data"] = tagged(envelope["data"], provenance)
        result = envelope if envelope is not None else tagged(raw, provenance)
        with self._guard:
            self.derived[key] = {"tool": name, "arguments": deepcopy(arguments), "result": deepcopy(result),
                                 "injected": name in self.faults, "frozen_provenance": provenance}
            self._counts["hits"] += 1
            if isinstance(raw, dict) and raw.get("status") in {"error", "unavailable"}:
                self._counts["errors"] += 1
            work = WORK.get()
            if work:
                path = Path(work) / "frozen_provider_calls.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(list(self.derived.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return deepcopy(result)

    def wrap_specs(self, specs, *, record_specs=None):
        originals = runner.financial_tool_specs("baseline")
        output = {}
        for name, value in specs.items():
            callback = originals[name].invoke if name in originals else value.invoke
            projection = self.project_envelope if getattr(value, "enveloped", False) else None
            output[name] = replace(value, invoke=lambda arguments, name=name, callback=callback, projection=projection:
                self.invoke(name, arguments, callback, project=projection))
        return output

    def records(self):
        with self._guard:
            return deepcopy(list(self.derived.values()))


async def frozen_run_case(case, subject, judge, args, eval_dir, pacer=None):
    location = ROOT / "tmp/agent-eval" / args.run_id / case["id"]
    token = WORK.set(location)
    try:
        with patch.object(runner, "ToolTape", FrozenTape):
            result = await ORIGINAL_RUN_CASE(case, subject, judge, args, eval_dir, pacer)
        result["frozen_provider"] = {"provider": "frozen_corpus", "manifest_sha256": corpus().identity,
            "provider_source_sha256": hashlib.sha256(Path(provider_module.__file__).read_bytes()).hexdigest(),
            "driver_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "actual_calls_path": (location / "frozen_provider_calls.json").relative_to(ROOT).as_posix(),
            "network_access": False, "measurement_scope": "decision_quality_on_same_frozen_data"}
        calls_path = location / "frozen_provider_calls.json"
        result["frozen_provider"]["actual_calls_sha256"] = hashlib.sha256(calls_path.read_bytes()).hexdigest() if calls_path.exists() else None
        return result
    finally:
        WORK.reset(token)


def frozen_worker(case, subject, judge, args, eval_dir, shared_pacing=None):
    # 原runner的ProcessPool initializer已完成唯一运行时选择，不能再次激活基线。
    pacer = runner.RequestPacer(args.request_interval, shared_pacing)
    return asyncio.run(frozen_run_case(case, subject, judge, args, eval_dir, pacer))


async def main(args):
    os.environ["FINSIGHT_EVAL_FROZEN_CORPUS_DIR"] = str(ROOT / "tests/agent_eval" / args.fixtures_root)
    runner.run_case = frozen_run_case
    runner.run_case_in_process = frozen_worker
    result = await runner.main(args)
    if args.list:
        return result
    output = Path(args.output)
    report = json.loads(output.read_text(encoding="utf-8"))
    report["harness_config"]["frozen_provider"] = {"provider": "frozen_corpus", "manifest_sha256": corpus().identity,
        "provider_source_sha256": hashlib.sha256(Path(provider_module.__file__).read_bytes()).hexdigest(),
        "driver_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "measurement_scope": "same_frozen_document_and_producer_corpus; decision_layer_only; live_network_validated_separately"}
    environment_path = os.getenv("FINSIGHT_EVAL_ENVIRONMENT_MANIFEST")
    if environment_path:
        preflight = json.loads(Path(environment_path).read_text(encoding="utf-8"))
        if preflight.get("passed") is not True or preflight["parent"]["python_executable"] != sys.executable:
            raise ValueError("measurement_environment_preflight_changed")
        report["harness_config"]["environment_manifest_sha256"] = hashlib.sha256(Path(environment_path).read_bytes()).hexdigest()
    if corpus().mount_manifest:
        report["harness_config"]["corpus_mount_manifest_sha256"] = corpus().mount_manifest["mapping_manifest_sha256"]
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(runner.build_parser().parse_args())))
