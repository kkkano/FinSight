"""工具白名单、参数验证、同轮取数合并和资料引用。"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .context import compact_result, dumps, evidence_preview
from .completeness import output_status
from .diagnostics import TOOL_TITLES, display_tool, error_info, exception_code, safe_code, safe_preview, tool_summary


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    invoke: Callable
    financial: bool = False

    def openai(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description[:1500],
                                                "parameters": self.parameters}}

    def validate(self, args: dict) -> dict:
        if not isinstance(args, dict):
            raise ValueError("tool_arguments_must_be_object")
        required = self.parameters.get("required", [])
        properties = self.parameters.get("properties", {})
        if any(key not in args for key in required) or any(key not in properties for key in args):
            raise ValueError("invalid_tool_arguments")
        if len(dumps(args)) > 24000:
            raise ValueError("tool_arguments_too_large")
        return args


def schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def history_with_returns(output):
    """给相邻真实收盘观测附明确百分比，避免把模型手算当作行情证据。"""
    if not isinstance(output, dict):
        return output
    result = dict(output)
    for key in ("data", "kline_data", "rows", "bars"):
        points = output.get(key)
        if not isinstance(points, list) or not all(isinstance(row, dict) for row in points):
            continue
        rows, previous = [], None
        for point in points:
            close = point.get("close")
            valid = type(close) in {int, float} and math.isfinite(close)
            change = (close / previous - 1) * 100 if valid and previous is not None and previous > 0 else None
            rows.append({**point, "period_return_pct": change})
            previous = close if valid else None
        result[key] = rows
    result["derived_fields"] = {"period_return_pct": {"formula": "(close/previous_returned_close-1)*100", "unit": "percent",
        "basis": "相邻返回观测；首行或前收盘缺失时为空，不跨缺失值补算。"}}
    return result


def financial_tools() -> dict[str, ToolSpec]:
    from backend.langchain_tools import FINANCIAL_TOOLS
    from langchain_core.utils.function_calling import convert_to_openai_tool
    tools = {}
    for tool in FINANCIAL_TOOLS:
        # 只读能力显式分类；原固定计算由运行时数据接口调用，不把外部资源路径传入。
        if not tool.name.startswith(("get_", "search", "fetch_", "analyze_", "score_")):
            continue
        entry = convert_to_openai_tool(tool)["function"]
        def invoke(args, _tool=tool):
            result = _tool.invoke(args)
            if isinstance(result, str) and result.lstrip().startswith(("{", "[")):
                try:
                    return json.loads(result)
                except ValueError:
                    pass
            return result
        tools[tool.name] = ToolSpec(tool.name, entry.get("description", tool.name),
                                    entry.get("parameters", schema({}, [])), invoke, financial=True)
    def historical(args):
        from backend.tools.price import get_stock_historical_data
        period, interval = args.get("period", "1y"), args.get("interval", "1d")
        if period not in {"1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max"} or interval not in {"1d", "1wk", "1mo"}:
            raise ValueError("unsupported_history_window")
        if period == "ytd" and interval != "1d":
            raise ValueError("ytd_requires_daily_baseline")
        output = get_stock_historical_data(args["ticker"], period="1y" if period == "ytd" else period, interval=interval)
        from backend.services.market_history_view import clip_history_period
        output = clip_history_period(output, "1y" if period == "ytd" else period)
        if period == "ytd" and isinstance(output, dict) and not output.get("error_code"):
            from datetime import datetime
            from zoneinfo import ZoneInfo
            start = str(datetime.now(ZoneInfo("America/New_York")).year) + "-01-01"
            points = output.get("kline_data") or output.get("data") or []
            date_key = lambda row: str(row.get("time") or row.get("date") or "")[:10]
            prior = [row for row in points if date_key(row) < start]
            current = [row for row in points if date_key(row) >= start]
            selected = prior[-1:] + current
            if not current or not prior:
                return {"status": "unavailable", "error": "ytd_baseline_unavailable", "summary": "缺少年初前最后一个交易日收盘价，无法准确计算年初至今涨跌幅。"}
            output = {**output, "period": "ytd", "data": selected, "kline_data": selected,
                      "baseline_date": date_key(prior[-1]), "baseline_method": "previous_year_last_available_close"}
        return history_with_returns(output)
    tools["get_stock_historical_data"] = ToolSpec("get_stock_historical_data", "读取统一行情网关的真实历史OHLC，支持max历史和日/周/月周期；原始来源/时间/缺失必须保留。",
        schema({"ticker": {"type": "string"}, "period": {"type": "string", "enum": ["1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max"]},
                "interval": {"type": "string", "enum": ["1d", "1wk", "1mo"]}}, ["ticker"]), historical, financial=True)
    from backend.tools.extended_market import get_us_extended_hours, get_finra_otc_activity
    tools["get_us_extended_hours"] = ToolSpec("get_us_extended_hours",
        "读取美股04:00–20:00纽约时间盘前/常规/盘后OHLCV，非24小时；延迟未知，不保证实时，volume不是资金净流入。rows可直接render_chart。",
        schema({"ticker": {"type": "string"}, "period": {"type": "string", "enum": ["1d", "5d", "1mo"]},
                "interval": {"type": "string", "enum": ["1m", "5m", "15m", "30m"]},
                "session": {"type": "string", "enum": ["all", "pre_market", "regular", "after_hours"]}}, ["ticker"]),
        lambda args: get_us_extended_hours(**args), financial=True)
    tools["get_finra_otc_activity"] = ToolSpec("get_finra_otc_activity",
        "读取FINRA公布的美股ATS/非ATS场外周成交股数与笔数，官方延迟2或4周；并非暗盘即时报价或资金净流入。rows的ats_share_volume/non_ats_share_volume可直接画周柱状图。",
        schema({"ticker": {"type": "string"}, "weeks": {"type": "integer", "minimum": 1, "maximum": 26}}, ["ticker"]),
        lambda args: get_finra_otc_activity(**args), financial=True)
    from .tool_display import DISPLAYS
    missing = set(tools) - DISPLAYS.keys()
    if missing:
        raise ValueError("tool_display_not_registered:" + ",".join(sorted(missing)))
    return tools


class ToolExecutor:
    def __init__(self, runtime):
        self.runtime = runtime
        self._inflight: dict[str, asyncio.Task] = {}
        self._cache: dict[str, Any] = {}
        self._started: set[str] = set()
        self.failures: list[str] = []
        self.unresolved_failures: dict[str, str] = {}
        self.attempts: list[dict] = []

    async def _financial(self, spec: ToolSpec, arguments: dict):
        key = hashlib.sha256(dumps([spec.name, arguments]).encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        async def fetch():
            async with self.runtime.limiter.slot("financial", self.runtime.context.owner, 8,
                                                  timeout=self.runtime.context.timeout(15)):
                if self.runtime._closed:
                    raise asyncio.CancelledError()
                self.runtime.context.guard()
                self._started.add(key)
                result = await asyncio.to_thread(spec.invoke, arguments)
                self.runtime.context.guard()
                if self.runtime._closed:
                    raise asyncio.CancelledError()
            if output_status(result) == "success":
                self._cache[key] = result
            return result
        task = asyncio.create_task(fetch())
        self._inflight[key] = task
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self.runtime.context.timeout(30))
        finally:
            if task.done():
                self._inflight.pop(key, None)
            else:
                task.add_done_callback(lambda _: self._inflight.pop(key, None))

    async def execute(self, name: str, arguments: dict, call_id: str, agent_id: str, available: dict[str, ToolSpec]) -> dict:
        self.runtime.context.guard()
        if name not in available:
            self.failures.append(name)
            info = error_info("tool_not_allowed")
            await self.runtime.emit("tool.failed", {"tool_call_id": call_id, "name": name,
                "title": TOOL_TITLES.get(name, "研究工具"), "inputs": safe_preview(arguments), **info,
                "summary": info["reason"], "duration_ms": 0}, agent_id=agent_id)
            return {"status": "error", "error": "tool_not_allowed", "summary": info["reason"]}
        spec = available[name]
        started = time.monotonic()
        title = TOOL_TITLES.get(name, "研究工具")
        if name == "get_stock_historical_data":
            title = {"1d": "获取日线", "1wk": "获取周线", "1mo": "获取月线"}.get(arguments.get("interval", "1d"), "获取历史行情") if isinstance(arguments, dict) else title
        display_args = dict(arguments) if isinstance(arguments, dict) else {}
        data_ref = display_args.get("dataset_ref") or display_args.get("data_ref")
        if isinstance(data_ref, str) and data_ref in self.runtime.data.records:
            display_args["_dataset_inputs"] = self.runtime.data.records[data_ref].get("inputs", {})
        failure_key = hashlib.sha256(dumps([name, arguments]).encode()).hexdigest()
        attempt = {"name": name, "inputs": arguments, "status": "unavailable"}
        if spec.financial:
            self.attempts.append(attempt)
        await self.runtime.emit("tool.started", {"tool_call_id": call_id, "name": name, "title": title,
                                "display": display_tool(name, display_args),
                                "inputs": safe_preview(arguments), "summary": "正在" + title}, agent_id=agent_id)
        try:
            args = spec.validate(arguments)
            if name == "fetch_url_content" and self.runtime.ui_context.get("strict_selection"):
                from urllib.parse import urldefrag
                context = self.runtime.ui_context
                items = context.get("selections") or ([context["selection"]] if context.get("selection") else [])
                allowed_urls = {urldefrag(str(item.get("url") or ""))[0].rstrip("/") for item in items if isinstance(item, dict)}
                if urldefrag(str(args.get("url") or ""))[0].rstrip("/") not in allowed_urls:
                    raise ValueError("selection_scope_violation")
            if spec.financial:
                output = await self._financial(spec, args)
            else:
                output = spec.invoke(args)
                if inspect.isawaitable(output):
                    output = await output
            self.runtime.context.guard()
            result_status = output_status(output) if spec.financial else "success"
            from backend.graph.request_task_contract import output_is_error_like
            failure = result_status != "success" or output_is_error_like(output)
            if isinstance(output, str) and re.match(r"^(?:" + re.escape(name) + r"\s+(?:failed|unavailable|error)|error\s*:|错误[:：]|失败[:：])", output.strip(), re.IGNORECASE):
                output = {"status": "error", "error": "tool_provider_error", "summary": "供应商未返回可用数据。"}
                failure = True
            if isinstance(output, dict) and output.get("status") in {"error", "unavailable"}:
                failure = True
            if result_status == "empty":
                output = {"status": "empty", "error": "tool_empty_result", "summary": "本次来源未返回匹配资料，需换来源补查；这不代表相关资料不存在。",
                          "result": output}
            if failure:
                self.failures.append(name)
                self.unresolved_failures[failure_key] = name
                if isinstance(output, dict) and output.get("error") in {"analysis_capacity_insufficient", "analysis_worker_unconfigured"}:
                    self.runtime.unavailable_tools.add(name)
            else:
                self.unresolved_failures.pop(failure_key, None)
                ticker = args.get("ticker")
                if spec.financial and isinstance(ticker, str) and re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9.^=-]{0,19}", ticker):
                    ticker = ticker.upper()
                    if ticker not in self.runtime.observed_tickers:
                        self.runtime.observed_tickers.append(ticker)
            evidence_tool = spec.financial or name in {"search_knowledge", "read_document", "search_memory", "read_selection"}
            if evidence_tool:
                refs = [self.runtime.data.record(name, args, output, status="unavailable" if failure else "success")]
                attempt.update(status="unavailable" if failure else "success", data_ref=refs[0])
            else:
                refs = [r for r in ((output.get("data_refs") or []) if isinstance(output, dict) else [])
                        if r in self.runtime.data.records]
                if name == "read_evidence" and isinstance(output, dict) and output.get("data_ref") in self.runtime.data.records:
                    refs = [output["data_ref"]]
                if not refs and (failure or name in {"await_agent_results", "discover_tools", "delegate_research", "send_agent_message", "get_watchlist", "discover_skills", "use_skill"}):
                    refs = [self.runtime.data.record(name, args, output, status="control")]
            # 调度/确认/发现工具的回执不是金融来源，不能进入证据账本充数。
            result = {"status": "unavailable" if failure else "ok", "data_refs": refs,
                      "source_refs": list(dict.fromkeys(s for ref in refs for s in self.runtime.data.source_refs(ref))),
                      "result": output}
            if isinstance(output, dict) and output.get("status") == "confirmation_required":
                result["status"] = "confirmation_required"
            if refs:
                try:
                    await asyncio.to_thread(self.runtime.data.save)
                except OSError:
                    result["limitations"] = ["本轮数据尚未保存为可续研资料，当前结果仍可使用。"]
            info = error_info((output.get("error_code") or output.get("error") or "tool_provider_error")
                              if isinstance(output, dict) else "tool_provider_error",
                              output=output if isinstance(output, dict) else None) if failure else {}
            summary = tool_summary(output)
            if failure:
                summary = info["reason"] if not isinstance(output, dict) or not output.get("summary") else summary
                info["reason"] = summary
            source_refs = result["source_refs"]
            display_output = output
            if name == "render_chart" and isinstance(output, dict):
                display_output = {**output, "_artifact": next((item for item in self.runtime.data.artifacts if item["artifact_id"] == output.get("artifact_id")), {})}
            display = display_tool(name, display_args, display_output)
            if failure:
                display["result"] = info["reason"]
            sources = [safe_preview({"source_id": sid, **{key: self.runtime.data.sources[sid].get(key)
                for key in ("title", "url", "source", "as_of")}}) for sid in source_refs[:8] if sid in self.runtime.data.sources]
            preview_output = output.get("result") if name == "run_analysis_code" and not failure and isinstance(output, dict) and "result" in output else output
            if name == "read_evidence" and not failure and isinstance(output, dict):
                record = self.runtime.data.records.get(args.get("data_ref"), {})
                preview_output = {key: output[key] for key in ("offset", "total_chars", "next_offset", "has_more") if key in output}
                # 交给模型的原始片段保持不变；界面只投影同一资料的有界摘要，避免序列化包裹挤占阅读区。
                preview_output["preview"] = evidence_preview(record.get("output"), limit=3200)
            await self.runtime.emit("tool.failed" if failure else "tool.result", {
                "tool_call_id": call_id, "name": name, "title": title, "status": result["status"], "data_refs": refs,
                "inputs": safe_preview(args), "output_preview": safe_preview(preview_output), "source_refs": source_refs,
                "evidence_refs": source_refs, "sources": sources, "summary": summary, "display": display, **info,
                "duration_ms": int((time.monotonic() - started) * 1000)}, agent_id=agent_id)
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failures.append(name)
            self.unresolved_failures[failure_key] = name
            # 只传类型/经过约束的代码，不透传工具/供应商异常中的密钥。
            code = "tool_timeout" if isinstance(exc, TimeoutError) else safe_code(str(exc)) if isinstance(exc, ValueError) else exception_code(exc)
            info = error_info(code)
            from .data import DatasetRowsError
            details = {}
            if isinstance(exc, DatasetRowsError):
                info["reason"] = exc.summary
                details = safe_preview(exc.details)
            await self.runtime.emit("tool.failed", {"tool_call_id": call_id, "name": name, "title": title,
                                    "inputs": safe_preview(arguments), **info, **details, "summary": info["reason"],
                                    "display": {"target": display_tool(name, display_args)["target"], "result": info["reason"]},
                                    "duration_ms": int((time.monotonic() - started) * 1000)}, agent_id=agent_id)
            return {"status": "error", "error": code, "summary": info["reason"], "recovery_action": info["recovery_action"], **details}

    async def close(self):
        # 同步HTTP不可强制中断；不接收晚到结果，但其槽位保持到真实调用结束。
        waiting = []
        for key, task in list(self._inflight.items()):
            if key not in self._started:
                task.cancel()
                waiting.append(task)
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        if waiting:
            await asyncio.gather(*waiting, return_exceptions=True)

