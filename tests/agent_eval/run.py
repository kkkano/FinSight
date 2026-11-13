"""运行完整研究入口；录制与回放工具边界，输出分项成绩及基线差值。"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "tests"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from agent_eval.scoring import ContentScore, EXTERNAL_JUDGE, JUDGE_SYSTEM, SCORE_FIELDS, compare, judge_answer, judge_metadata, judge_prompt, structural_score, summarize
from agent_eval.capture import install_capture_hooks
from agent_eval.tapes import ToolTape
from agent_eval.eval_transport import EvaluationLimiter, json_completions, observe_chunks, validate_temperature
from agent_eval.eval_costs import STEP5_MODEL, STEPFUN_BASE, STEP5_PRICING, estimate_step5_cost, sum_cost_estimates


def activate_runtime(name: str) -> Path:
    """在导入前选择冻结基线或当前实现，冻结文件必须逐项校验。"""
    current = REPO / "backend" / "agent_runtime"
    if name == "current":
        return current
    if name != "baseline":
        raise ValueError("unknown_evaluation_runtime")
    snapshot = Path(__file__).resolve().parent / "baseline_runtime"
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    for relative, checksum in manifest["files"].items():
        path = (snapshot / relative).resolve()
        if not path.is_relative_to(snapshot.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError("frozen_baseline_changed")
    if any(key.startswith("backend.agent_runtime.") for key in sys.modules):
        raise ValueError("baseline_runtime_must_be_selected_before_import")
    from agent_eval.reference.loader import activate
    activate()
    import backend.agent_runtime as package
    package.__path__ = [str(snapshot)]
    return snapshot


def financial_tool_specs(runtime_name: str = "current"):
    """当前工具来自唯一注册表；历史基线直接读取冻结快照。"""
    if runtime_name == "current":
        from backend.agent_runtime.registry import financial_tools
    elif runtime_name == "baseline":
        from agent_eval.baseline_runtime.tools import financial_tools
    else:
        raise ValueError("unknown_evaluation_runtime")
    return financial_tools()


def runtime_digest(directory: Path) -> str:
    """冻结基线保持原摘要；当前实现递归绑定代码与提示词。"""
    digest = hashlib.sha256()
    baseline = directory.name == "baseline_runtime"
    paths = directory.glob("*.py") if baseline else (
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix in {".py", ".md"} and "__pycache__" not in path.parts
    )
    for path in sorted(paths):
        relative = path.name if baseline else path.relative_to(directory).as_posix()
        digest.update(("backend/agent_runtime/" + relative).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def evaluation_model(base, provider: str):
    """显式选择评测端点；不覆盖生产配置或在请求中途切换供应商。"""
    if provider == "configured":
        return base
    if provider == "stepfun":
        key = os.getenv("FINSIGHT_AGENT_STEPFUN_API_KEY", "").strip()
        if not key:
            raise ValueError("evaluation_stepfun_configuration_incomplete")
        from backend.agent_runtime.config import ModelConfig
        return ModelConfig(STEP5_MODEL, STEPFUN_BASE, key, endpoint_name="stepfun-official",
                           context_window=1000000, max_output=4096, effort="low")
    if provider in {"vectide", "apikl"}:
        prefix = "FINSIGHT_EVAL_" + provider.upper() + "_"
        fields = {name: os.getenv(prefix + name, "").strip()
                  for name in ("MODEL", "API_BASE", "API_KEY")}
        if not all(fields.values()):
            raise ValueError("evaluation_" + provider + "_configuration_incomplete")
        from backend.agent_runtime.config import ModelConfig
        return ModelConfig(fields["MODEL"], fields["API_BASE"].rstrip("/"), fields["API_KEY"],
                           endpoint_name="evaluation-" + provider,
                           context_window=int(os.getenv(prefix + "CONTEXT_WINDOW", "1048576" if provider == "vectide" else "131072")),
                           max_output=int(os.getenv(prefix + "MAX_OUTPUT", "16384")))
    if provider == "moxuna":
        fields = {name: os.getenv("FINSIGHT_EVAL_MOXUNA_" + name,
                                 "deepseek-v4.1-flash" if name == "MODEL" else "").strip()
                  for name in ("MODEL", "API_BASE", "API_KEY")}
        if not all(fields.values()):
            raise ValueError("evaluation_moxuna_configuration_incomplete")
        from backend.agent_runtime.config import ModelConfig
        return ModelConfig(fields["MODEL"], fields["API_BASE"].rstrip("/"), fields["API_KEY"],
                           endpoint_name="evaluation-moxuna", context_window=32768, max_output=4096)
    if provider != "fallback":
        raise ValueError("unknown_evaluation_provider")
    fields = {name: os.getenv("FINSIGHT_EVAL_FALLBACK_" + name, "").strip()
              for name in ("MODEL", "API_BASE", "API_KEY")}
    if not all(fields.values()):
        raise ValueError("evaluation_fallback_configuration_incomplete")
    return replace(base, model=fields["MODEL"], base_url=fields["API_BASE"].rstrip("/"),
                   api_key=fields["API_KEY"], endpoint_name="evaluation-fallback",
                   context_window=int(os.getenv("FINSIGHT_EVAL_FALLBACK_CONTEXT_WINDOW", "32768")),
                   max_output=int(os.getenv("FINSIGHT_EVAL_FALLBACK_MAX_OUTPUT", "8192")), effort=None)


def model_quota_configuration():
    return {"concurrency": max(1, int(os.getenv("FINSIGHT_AGENT_MODEL_CONCURRENCY", "2"))),
            "rpm": max(1, int(os.getenv("FINSIGHT_AGENT_RPM_LIMIT", "30"))),
            "tpm": max(1, int(os.getenv("FINSIGHT_AGENT_TPM_LIMIT", "250000"))),
            "minimum_request_interval_seconds": max(0.0, min(60.0, float(os.getenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")))),
            "run_token_budget": int(os.getenv("FINSIGHT_AGENT_TOKEN_BUDGET", "160000"))}


class RequestPacer:
    """只限制评测请求频率；不修改消息、模型参数或工具选择。"""
    def __init__(self, interval: float = 0, shared_state=None):
        if interval < 0:
            raise ValueError("evaluation_request_interval_negative")
        self.interval = interval
        self._next = 0.0
        self._lock = asyncio.Lock()
        self._shared_state = shared_state

    def _claim_shared_slot(self) -> float:
        with self._shared_state.lock:
            now = time.monotonic()
            delay = self._shared_state.next_allowed.value - now
            if delay <= 0:
                self._shared_state.next_allowed.value = now + self.interval
            return delay

    async def wait(self) -> None:
        if not self.interval:
            return
        async with self._lock:
            if self._shared_state is not None:
                while (delay := await asyncio.to_thread(self._claim_shared_slot)) > 0:
                    await asyncio.sleep(delay)
                return
            delay = self._next - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next = time.monotonic() + self.interval


class PacedTransport:
    def __init__(self, transport, pacer: RequestPacer):
        self.transport, self.pacer = transport, pacer
        self.config = transport.config
        self.errors = []

    async def stream(self, *args, **kwargs):
        async for chunk in evaluation_stream(self.transport.stream, self.pacer, self.errors, *args, **kwargs):
            yield chunk

    async def complete_json(self, messages, *, timeout: float = 90):
        """显式非流式 JSON 协议；请求与原生工具调用共用同一配额节奏。"""
        import httpx
        from backend.agent_runtime.model import ModelProtocolError

        deadline = time.monotonic() + timeout
        await self.pacer.wait()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelProtocolError("model_timeout")
        payload = {"model": self.config.model, "messages": messages, "stream": False,
                   "max_tokens": self.config.max_output, "response_format": {"type": "json_object"}}
        if self.config.effort:
            payload["reasoning_effort"] = self.config.effort
        supplied_client = self.transport.client
        client = supplied_client or httpx.AsyncClient(follow_redirects=False)
        try:
            async with asyncio.timeout(remaining):
                response = await client.post(self.config.base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + self.config.api_key}, json=payload,
                    timeout=httpx.Timeout(remaining, connect=min(15, remaining)))
                if response.status_code != 200:
                    raise ModelProtocolError("model_http_" + str(response.status_code), status=response.status_code)
                try:
                    result = response.json()
                except ValueError:
                    raise ModelProtocolError("model_invalid_response_json") from None
                if isinstance(result, dict) and result.get("error"):
                    raise ModelProtocolError("model_response_error")
                return result
        except (httpx.TimeoutException, TimeoutError):
            raise ModelProtocolError("model_timeout") from None
        except httpx.HTTPError:
            raise ModelProtocolError("model_connection_error") from None
        finally:
            if supplied_client is None:
                await client.aclose()


async def evaluation_stream(stream, pacer, errors, *args, **kwargs):
    """零片段连接失败最多重试一次；已收到的流绝不重放。"""
    from backend.agent_runtime.model import ModelProtocolError

    deadline = time.monotonic() + kwargs.get("timeout", 60)
    retry_record = None
    for attempt in range(2):
        await pacer.wait()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelProtocolError("model_timeout")
        received = False
        try:
            async for chunk in stream(*args, **{**kwargs, "timeout": remaining}):
                received = True
                yield chunk
            if retry_record is not None:
                retry_record["recovered"] = True
            return
        except ModelProtocolError as exc:
            if attempt or received or exc.code != "model_connection_error":
                raise
            retry_record = {"code": exc.code, "cause": type(exc.__context__).__name__
                            if exc.__context__ else None, "recovered": False}
            errors.append(retry_record)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def digest_files(paths: list[Path], base: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class IsolatedWatchlist:
    """写操作题只改变评测进程内数据；保留原运行时的授权行为。"""
    def __init__(self):
        self.items = {}

    def list_items(self, user_id):
        return list(self.items.get(user_id, {}).values())

    def add_item(self, ticker, user_id, **fields):
        self.items.setdefault(user_id, {})[ticker] = {"ticker": ticker, **fields}

    def remove_item(self, ticker, user_id):
        return self.items.setdefault(user_id, {}).pop(ticker, None) is not None


async def no_archive(_context):
    """用量由结果文件归档，不接入生产数据库。"""


def isolated_environment(work: Path) -> dict[str, str]:
    values = {
        "FINSIGHT_ARTIFACT_DIR": str(work / "artifacts"),
        "FINSIGHT_ACTION_STORE": str(work / "actions.sqlite"),
        "FINSIGHT_RUNTIME_QUOTA_DB": str(work / "quota.sqlite"),
        "LANGGRAPH_CHECKPOINTER_BACKEND": "memory",
        "MONITOR_REALTIME_ENABLED": "false", "ENABLE_LANGSMITH": "false",
    }
    worker = evaluation_analysis_worker()
    values.update(worker)
    return values


def evaluation_analysis_worker() -> dict[str, str]:
    url = os.getenv("FINSIGHT_EVAL_ANALYSIS_WORKER_URL", "").strip()
    token = os.getenv("FINSIGHT_EVAL_ANALYSIS_WORKER_TOKEN", "").strip()
    if not url or not token:
        return {}
    return {"FINSIGHT_ANALYSIS_WORKER_URL": url, "FINSIGHT_ANALYSIS_WORKER_TOKEN": token}


async def run_case(case, subject_config, judge_config, args, eval_dir, pacer=None):
    import httpx
    from backend.agent_runtime import service
    from backend.agent_runtime.limits import LeaseLimiter
    from backend.agent_runtime.model import ModelTransport
    from backend.services.run_context import RunContext

    started = time.monotonic()
    pacer = pacer or RequestPacer(getattr(args, "request_interval", 0))
    fixture_base = eval_dir / (getattr(args, "fixtures_root", None) or "fixtures")
    seed_path = getattr(args, "seed_tapes", None)
    tape = ToolTape(fixture_base / case["id"], args.mode, faults=case.get("tool_faults"),
                    seed_path=eval_dir / seed_path if seed_path else None)
    work = REPO / "tmp" / "agent-eval" / args.run_id / case["id"]
    work.mkdir(parents=True, exist_ok=True)
    original_runtime = service.AgentRuntime
    runs, events, turns, histories, checkpoints = [], [], [], [], []
    model_calls, transport_errors, model_call_outcomes = [], [], []
    model_protocol = getattr(args, "model_protocol", "sse")
    model_temperature = validate_temperature(getattr(args, "temperature", None), model_protocol)

    class ObservedTransport(ModelTransport):
        async def stream(self, messages, tools, **kwargs):
            entry = {"messages": deepcopy(messages), "tools": tools, "usage": {}, "cost_estimate": None}
            model_calls.append(entry)
            request = {"model": self.config.model,
                "messages": [{key: value for key, value in message.items() if key != "reasoning_content"}
                             for message in messages], "tools": tools,
                "reasoning_omitted": any("reasoning_content" in message for message in messages),
                "max_tokens": kwargs.get("max_tokens", self.config.max_output),
                "stream": model_protocol == "sse", "model_protocol": model_protocol, "tool_choice": kwargs.get("tool_choice")}
            if model_protocol == "sse":
                request["stream_options"] = {"include_usage": True}
            if model_temperature is not None:
                request["temperature"] = model_temperature
            write_json(work / "last_model_request.json", request)
            outcome = {"model": self.config.model, "protocol": model_protocol}
            model_call_outcomes.append(outcome)
            upstream = super().stream
            if model_protocol == "json-completions":
                async def upstream(*stream_args, **stream_kwargs):
                    async for chunk in json_completions(self, *stream_args, temperature=model_temperature, **stream_kwargs):
                        yield chunk
            try:
                iterator = evaluation_stream(upstream, pacer, transport_errors, messages, tools, **kwargs)
                async for chunk in observe_chunks(iterator, outcome):
                    if chunk.get("usage"):
                        entry["usage"] = chunk["usage"]
                    yield chunk
            except Exception as exc:
                transport_errors.append({"code": getattr(exc, "code", type(exc).__name__),
                                         "cause": type(exc.__context__).__name__ if exc.__context__ else None})
                raise
            finally:
                entry["cost_estimate"] = estimate_step5_cost(entry["usage"], self.config.model, self.config.base_url)
                outcome["cost_estimate"] = entry["cost_estimate"]
                write_json(work / "model_call_outcomes.json", model_call_outcomes)

    def factory(**kwargs):
        specs = financial_tool_specs(getattr(args, "runtime", "current"))
        record_specs = None
        if args.mode == "record" and any(getattr(spec, "enveloped", False) for spec in specs.values()):
            # 独立导入旧入口，不切换候选运行时包；回放无需加载旧工具。
            record_specs = financial_tool_specs("baseline")
        kwargs["tools"] = tape.wrap_specs(specs, record_specs=record_specs)
        kwargs["limiter"] = EvaluationLimiter(LeaseLimiter(work / "quota.sqlite"), LeaseLimiter(work.parent / "model_quota.sqlite"))
        runtime = original_runtime(**kwargs)
        # 评测账号的知识库从空状态开始；不连接生产知识库或其它用户资料。
        def empty_knowledge(name, arguments):
            return tape.invoke(name, arguments, lambda _: {"status": "empty", "items": [],
                "source": "evaluation_isolated_store", "summary": "评测隔离账户没有历史资料。"})
        runtime._knowledge = SimpleNamespace(**{
            name: (lambda _name=name, **arguments: empty_knowledge(_name, arguments))
            for name in ("search_knowledge", "search_memory", "read_document")})
        runs.append(runtime)
        return runtime

    watchlist = IsolatedWatchlist()
    async with httpx.AsyncClient(timeout=90, follow_redirects=False,
            headers={"User-Agent": "FinSight-agent-eval/1.0"}) as client:
        model = ObservedTransport(subject_config, client=client)
        with patch.dict(os.environ, isolated_environment(work)), install_capture_hooks() as capture_hooks, \
             patch.object(service, "AgentRuntime", factory), \
             patch.object(service, "ModelTransport", lambda _config: model), \
             patch.object(service, "resolve_model", lambda: subject_config), \
             patch.object(RunContext, "archive_usage", no_archive), \
             patch("backend.services.watchlist_store.get_watchlist_store", lambda: watchlist):
            for index, query in enumerate(case["turns"]):
                run_id = args.run_id + ":" + case["id"] + ":" + str(index)
                ctx = RunContext.create(owner="agent-eval", entry=case.get("mode", "chat"),
                                        run_id=run_id, budget_seconds=args.timeout)
                ctx.quota_checker = lambda _: None
                ui = {"session_history": list(histories)}
                if index:
                    ui["resume_from_run_id"] = turns[-1]["run_id"]
                deps = SimpleNamespace(persist_run_event=None, schedule_report_index=lambda **_: True,
                                       update_session_context=lambda **_: None)
                before_calls = len(model_calls)
                turn_events = []
                async for event in service.run_agent_pipeline(deps=deps, query=query,
                        thread_id=args.run_id + ":" + case["id"], run_id=run_id,
                        run_context=ctx, ui_context=ui, output_mode=case.get("mode"),
                        checkpoint=lambda state: checkpoints.append(state)):
                    turn_events.append(event)
                    events.append(event)
                terminals = [event for event in turn_events if event.get("type") in {"done", "error", "cancelled"}]
                terminal = dict(terminals[-1]) if terminals else {"type": "error", "code": "terminal_missing", "response": ""}
                terminal["blocks"] = [block for block in terminal.get("blocks", []) if block.get("kind") != "reasoning"]
                turns.append({"run_id": run_id, "query": query, "terminal": terminal,
                              "model_calls": len(model_calls) - before_calls, "terminal_count": len(terminals)})
                histories.extend([{"role": "user", "content": query},
                                  {"role": "assistant", "content": terminal.get("response", "")}])
        result = {"id": case["id"], "group": case["group"], "model": subject_config.model,
                  "turns": turns, "tape": tape.stats(), "score": None,
                  "elapsed_seconds": round(time.monotonic() - started, 3),
                  "structure": structural_score(case, turns, events),
                  "checkpoints": len(checkpoints), "watchlist": watchlist.list_items("agent-eval"),
                  "transport_errors": transport_errors, "model_call_outcomes": model_call_outcomes,
                  "model_cost_estimates": [entry["cost_estimate"] for entry in model_calls],
                  "cost_estimate": sum_cost_estimates(entry["cost_estimate"] for entry in model_calls),
                  "capture_hooks": capture_hooks}
        if getattr(args, "judge_protocol", "tools") == "external":
            from agent_eval.external_judge import write_request
            result["external_judge_verified"] = False
            try:
                result["external_judge"] = write_request(case, result, tape.records(), eval_dir, args.run_id)
            except Exception as exc:
                result["judge_error"] = getattr(exc, "code", type(exc).__name__)
        elif not args.no_judge:
            try:
                judge = PacedTransport(ModelTransport(judge_config, client=client), pacer)
                result["score"] = await judge_answer(judge, case, result, tape.records(),
                                                     protocol=getattr(args, "judge_protocol", "tools"))
                result["judge_transport_errors"] = judge.errors
            except Exception as exc:
                result["judge_error"] = getattr(exc, "code", type(exc).__name__)
                result["judge_details"] = getattr(exc, "details", {})
        # 只存公开答案与结构事件；不把供应商的原始推理正文写入评测产物。
        public_events = [{**event, **({"blocks": [block for block in event["blocks"] if block.get("kind") != "reasoning"]}
                         if "blocks" in event else {})} for event in events
                         if not str(event.get("runtime_type", event.get("type", ""))).startswith("reasoning.")]
        write_json(work / "events.json", public_events)
        write_json(work / "model_usage.json", [entry["usage"] for entry in model_calls])
        result["events_path"] = (work / "events.json").relative_to(REPO).as_posix()
        result["tool_recordings"] = len(tape.records())
        return result


def run_case_in_process(case, subject_config, judge_config, args, eval_dir, shared_pacing=None):
    """每题在独立进程内运行，避免环境变量和服务 patch 在并发题间串扰。"""
    pacer = RequestPacer(getattr(args, "request_interval", 0), shared_pacing)
    return asyncio.run(run_case(case, subject_config, judge_config, args, eval_dir, pacer))


def print_table(groups):
    print("group | cases | judged | answered | numbers | limits | form | ids | total | complete | terminal | model_fail | seconds", flush=True)
    for group, row in groups.items():
        score = row["scores"]
        fields = [score[key] for key in ("answered", "numbers", "limitations", "presentation", "no_internal_identifiers", "total")]
        values = " | ".join("N/A" if value is None else f"{value:.2f}" for value in fields)
        terminal = "N/A" if row.get("single_terminal_rate") is None else f"{row['single_terminal_rate']:.0%}"
        failures = "N/A" if row.get("model_failure_rate") is None else f"{row['model_failure_rate']:.0%}"
        print(f"{group} | {row['cases']} | {row['judged']} | {values} | {row['completed_rate']:.0%} | {terminal} | {failures} | {row['median_seconds']:.2f}", flush=True)


def measured_row_ready(row, judge):
    """检验样本可测性；运行时预算失败和协议错误仍留在成绩中。"""
    if row.get("measurement_valid") is False or row.get("measurement_errors") or row.get("capture_complete") is False:
        return False
    turns = row.get("turns")
    if not isinstance(turns, list) or not turns:
        return False
    if any(not isinstance(turn.get("terminal"), dict) or turn["terminal"].get("type") not in {"done", "error", "cancelled"}
           or type(turn.get("terminal_count", 1)) is not int or turn.get("terminal_count", 1) < 1
           or turn.get("capture_complete") is False for turn in turns):
        return False
    score = row.get("score")
    if (not isinstance(row.get("model"), str) or not row["model"] or not isinstance(score, dict)
            or not judge.get("model") or score.get("model") != judge["model"] or score["model"] == row["model"]):
        return False
    try:
        checked = ContentScore.model_validate({key: score[key] for key in (*SCORE_FIELDS, "reasons")}).model_dump()
    except (KeyError, ValueError):
        return False
    if type(score.get("total")) is not int or score["total"] != sum(checked[key] for key in SCORE_FIELDS):
        return False
    if (row.get("tape") or {}).get("misses") != 0:
        return False
    for error in row.get("transport_errors", []):
        if error.get("code") == "model_timeout":
            continue
        if error.get("code") == "model_connection_error" and error.get("recovered") is True:
            continue
        return False
    outcomes = row.get("model_call_outcomes", [])
    if not isinstance(outcomes, list) or any(type(turn.get("model_calls", 0)) is not int for turn in turns):
        return False
    if any(outcome.get("status") not in {"completed", "cancelled", "failed"}
           or (outcome.get("status") == "failed" and outcome.get("error_code") != "model_timeout") for outcome in outcomes):
        return False
    if sum(turn.get("model_calls", 0) for turn in turns) > len(outcomes):
        return False
    if judge.get("protocol") == "external":
        reference = row.get("external_judge") or {}
        if (row.get("external_judge_verified") is not True or not reference.get("request_sha256")
                or score.get("request_sha256") != reference["request_sha256"]):
            return False
    return True


def report_ready(report):
    """第7.3节的完整基线测量，不能代替第12节产品验收。"""
    rows = report.get("results", [])
    expected = report.get("expected_cases")
    if (report.get("measurement_valid") is False or report.get("measurement_errors")
            or type(expected) is not int or expected < 1 or len(rows) != expected):
        return False
    ids = [row.get("id") for row in rows]
    if any(not isinstance(identity, str) or not identity for identity in ids) or len(set(ids)) != len(ids):
        return False
    if not all(measured_row_ready(row, report.get("judge") or {}) for row in rows):
        return False
    return any(outcome.get("model") == row.get("model") and outcome.get("status") == "completed"
               and type(outcome.get("received_chunks")) is int and outcome["received_chunks"] > 0
               for row in rows for outcome in row.get("model_call_outcomes", []))


async def grade_report(source, output, corpus, judge, eval_dir, pacer=None, judge_protocol="tools", external_judgments_dir=None):
    """判分失败可单独重跑；已有有效分数保留，不通过择优重试提高成绩。"""
    pacer = pacer or RequestPacer()
    report = json.loads(Path(source).read_text(encoding="utf-8"))
    cases_path = eval_dir / "cases.json"
    if report["cases_sha256"] != hashlib.sha256(cases_path.read_bytes()).hexdigest():
        raise ValueError("evaluation_cases_changed")
    prompt_hash = hashlib.sha256(judge_prompt(judge_protocol).encode()).hexdigest()
    judge_config = judge_metadata(judge, judge_protocol)
    if report.get("judge_prompt_sha256") != prompt_hash or report.get("judge") != judge_config:
        raise ValueError("judge_changed_requires_new_evaluation")
    fixture_base = eval_dir / report.get("fixtures_root", "fixtures")
    fixture_digest = digest_files(list(fixture_base.rglob("*.json")), fixture_base)
    if not report.get("fixtures_sha256") or report["fixtures_sha256"] != fixture_digest:
        raise ValueError("evaluation_fixtures_changed_requires_new_evaluation")
    by_id = {case["id"]: case for case in corpus["cases"]}
    report["graded_from"] = str(source)
    if judge_protocol == "external":
        if external_judgments_dir is None:
            raise ValueError("external_judgments_directory_required")
        from agent_eval.external_judge import import_judgment
        for row in report["results"]:
            row["external_judge_verified"] = False
            try:
                case = by_id[row["id"]]
                tape = ToolTape(fixture_base / case["id"], "replay", faults=case.get("tool_faults"))
                row["score"] = import_judgment(case, row, tape.records(), eval_dir, Path(external_judgments_dir))
                row["external_judge_verified"] = True
                row.pop("judge_error", None)
                row.pop("judge_details", None)
            except Exception as exc:
                row["judge_error"] = getattr(exc, "code", type(exc).__name__)
            report["groups"] = summarize(report["results"])
            report["ready"] = report_ready(report)
            write_json(output, report)
        print_table(report["groups"])
        print("RESULT " + str(output), flush=True)
        return 0 if report["ready"] else 2
    import httpx
    from backend.agent_runtime.model import ModelTransport
    async with httpx.AsyncClient(headers={"User-Agent": "FinSight-agent-eval/1.0"}) as client:
        for row in report["results"]:
            if row.get("score") is not None:
                continue
            case = by_id[row["id"]]
            tape = ToolTape(fixture_base / case["id"], "replay", faults=case.get("tool_faults"))
            try:
                transport = PacedTransport(ModelTransport(judge, client=client), pacer)
                row["score"] = await judge_answer(transport, case, row, tape.records(), protocol=judge_protocol)
                row["judge_transport_errors"] = transport.errors
                row.pop("judge_error", None)
                row.pop("judge_details", None)
            except Exception as exc:
                row["judge_error"] = getattr(exc, "code", type(exc).__name__)
                row["judge_details"] = getattr(exc, "details", {})
            report["groups"] = summarize(report["results"])
            report["ready"] = report_ready(report)
            write_json(output, report)
    report["groups"] = summarize(report["results"])
    report["ready"] = report_ready(report)
    write_json(output, report)
    print_table(report["groups"])
    print("RESULT " + str(output), flush=True)
    return 0 if report["ready"] else 2


async def main(args):
    temperature = validate_temperature(getattr(args, "temperature", None), args.model_protocol)
    runtime_dir = activate_runtime(args.runtime)
    from backend.agent_runtime.config import ModelConfig, load_local_config, resolve_model
    if args.runtime == "baseline":
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env.runtime.local", override=False)
    else:
        load_local_config()
    pacer = RequestPacer(args.request_interval)
    eval_dir = Path(__file__).resolve().parent
    cases_path = eval_dir / "cases.json"
    corpus = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = corpus["cases"]
    if args.case:
        requested = set(args.case)
        cases = [case for case in cases if case["id"] in requested]
        if len(cases) != len(requested):
            raise ValueError("unknown_case_id")
    if args.list:
        for case in cases:
            print(case["id"], case["group"])
        return 0
    if args.limit:
        cases = cases[:args.limit]
    base = evaluation_model(None if args.provider in {"stepfun", "moxuna", "vectide", "apikl"} else resolve_model(), args.provider)
    subject = ModelConfig(base.model, base.base_url, base.api_key, context_window=args.context_window or base.context_window,
                          max_output=args.max_output or base.max_output, effort=base.effort)
    if args.judge_protocol == "external":
        judge = SimpleNamespace(**EXTERNAL_JUDGE)
        if subject.model == judge.model:
            raise ValueError("judge_must_differ_from_subject")
    else:
        judge_model = os.getenv("FINSIGHT_EVAL_JUDGE_MODEL", "glm-5.3")
        # GLM-5.3 官方规格：1M 上下文、128K 最大输出；完整中转边界仍未实测。
        judge_window, judge_output = (1048576, 16384) if judge_model == "glm-5.3" else (131072, 8192)
        judge = ModelConfig(judge_model,
                            os.getenv("FINSIGHT_EVAL_JUDGE_API_BASE", base.base_url),
                            os.getenv("FINSIGHT_EVAL_JUDGE_API_KEY", base.api_key),
                            context_window=int(os.getenv("FINSIGHT_EVAL_JUDGE_CONTEXT_WINDOW", str(judge_window))),
                            max_output=int(os.getenv("FINSIGHT_EVAL_JUDGE_MAX_OUTPUT", str(judge_output))))
    head = subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=REPO, text=True).strip()
    args.run_id = time.strftime("%Y-%m-%d_%H%M%S") + "_" + head
    output = Path(args.output) if args.output else eval_dir / "results" / (args.run_id + ".json")
    if args.grade_report:
        return await grade_report(args.grade_report, output, corpus, judge, eval_dir, pacer, args.judge_protocol,
                                  args.external_judgments_dir)
    report = {"schema_version": 1, "runtime": args.runtime, "mode": args.mode, "head": head, "run_id": args.run_id,
              "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(), "results": [], "groups": {},
              "judge_prompt_sha256": hashlib.sha256(judge_prompt(args.judge_protocol).encode()).hexdigest(),
              "subject": {"model": subject.model, "context_window": subject.context_window, "max_output": subject.max_output,
                          "base_url": subject.base_url, "effort": subject.effort, "temperature": temperature},
              "judge": judge_metadata(judge, args.judge_protocol),
              "runtime_sha256": runtime_digest(runtime_dir),
              "fixtures_root": args.fixtures_root,
              "seed_tapes": args.seed_tapes,
              "harness_config": {"request_interval_seconds": args.request_interval, "jobs": args.jobs,
                                 "request_pacing_scope": "global" if args.request_interval else "unrestricted",
                                 "model_protocol": args.model_protocol, "upstream_stream": args.model_protocol == "sse",
                                 "model_configuration": {"model": subject.model, "base_url": subject.base_url,
                                                         "effort": subject.effort, "context_window": subject.context_window,
                                                         "max_output": subject.max_output, "temperature": temperature},
                                 "model_quotas": model_quota_configuration(),
                                 "step5_cost_pricing": STEP5_PRICING if subject.model == STEP5_MODEL and subject.base_url == STEPFUN_BASE else None,
                                 "model_quota_scope": "run_shared",
                                 "analysis_worker_enabled": bool(evaluation_analysis_worker()),
                                 "retry_unstarted_connections": 1},
              "ready": False, "expected_cases": len(corpus["cases"]), "cost_estimate": sum_cost_estimates([])}
    write_json(output, report)
    async def completed_cases():
        if args.jobs == 1:
            for case in cases:
                print("RUN " + case["id"], flush=True)
                yield await run_case(case, subject, judge, args, eval_dir, pacer)
            return
        from concurrent.futures import ProcessPoolExecutor
        from contextlib import ExitStack
        import multiprocessing
        loop = asyncio.get_running_loop()
        process_context = multiprocessing.get_context("spawn")
        with ExitStack() as resources:
            shared_pacing = None
            if args.request_interval:
                manager = resources.enter_context(process_context.Manager())
                shared_pacing = SimpleNamespace(next_allowed=manager.Value("d", 0.0), lock=manager.Lock())
            pool = resources.enter_context(ProcessPoolExecutor(max_workers=args.jobs, mp_context=process_context,
                                           initializer=activate_runtime, initargs=(args.runtime,)))
            pending = [loop.run_in_executor(pool, run_case_in_process, case, subject, judge, args, eval_dir, shared_pacing)
                       for case in cases]
            for future in asyncio.as_completed(pending):
                yield await future

    order = {case["id"]: index for index, case in enumerate(corpus["cases"])}
    async for result in completed_cases():
        report["results"].append(result)
        report["results"].sort(key=lambda row: order[row["id"]])
        report["groups"] = summarize(report["results"])
        report["cost_estimate"] = sum_cost_estimates(estimate for row in report["results"]
                                                    for estimate in row.get("model_cost_estimates", []))
        write_json(output, report)
        print("DONE " + result["id"] + " " + json.dumps({"completed": result["structure"]["completed"],
              "score": (result.get("score") or {}).get("total"), "tape": result["tape"],
              "judge_error": result.get("judge_error")}), flush=True)
    fixture_base = eval_dir / args.fixtures_root
    fixture_files = list(fixture_base.rglob("*.json"))
    report["fixtures_sha256"] = digest_files(fixture_files, fixture_base)
    report["ready"] = report_ready(report)
    if args.baseline:
        report["comparison"] = compare(json.loads(Path(args.baseline).read_text(encoding="utf-8")), report)
    write_json(output, report)
    print_table(report["groups"])
    print("RESULT " + str(output), flush=True)
    return 0 if report["ready"] and report.get("comparison", {}).get("passed", True) else 2


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("current", "baseline"), default="current",
                        help="current 使用当前唯一运行时；baseline 使用不可修改的M1原运行时快照")
    parser.add_argument("--provider", choices=("configured", "fallback", "stepfun", "moxuna", "vectide", "apikl"), default="configured",
                        help="显式选择默认配置或独立评测端点；APIKL/Vectide/Moxuna均使用各自环境变量")
    parser.add_argument("--mode", choices=("record", "replay"), default="replay")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3, 4), default=1, help="独立评测进程数；默认串行")
    parser.add_argument("--request-interval", type=float, default=0, help="所有评测进程共享的最小模型请求间隔（秒）；研究与判分共用")
    parser.add_argument("--case", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--context-window", type=int)
    parser.add_argument("--max-output", type=int)
    parser.add_argument("--temperature", type=float, help="可选采样温度0到2；仅json-completions评测支持，默认不指定")
    parser.add_argument("--model-protocol", choices=("sse", "json-completions"), default="sse",
                        help="研究模型传输协议；默认SSE，可显式按原样非流式响应投影协议片段")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--judge-protocol", choices=("tools", "json", "external"), default="tools",
                        help="独立判分提交协议；默认原生工具调用，可选严格JSON或原生角色离线判分")
    parser.add_argument("--external-judgments-dir", help="原生角色逐题评分JSON目录；仅external补判读取")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--baseline")
    parser.add_argument("--fixtures-root", default="fixtures", help="相对评测目录的录制根目录；不同录制版本不混用")
    parser.add_argument("--seed-tapes", help="录制时复用明确指定的历史归档；仅精确匹配工具及参数，回放不读取此目录")
    parser.add_argument("--grade-report", help="只补判已有结果中缺失的分数，不重新生成研究回答")
    return parser


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.ERROR)
    raise SystemExit(asyncio.run(main(build_parser().parse_args())))
