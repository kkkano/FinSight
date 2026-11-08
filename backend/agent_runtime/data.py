"""运行级不可变资料引用；证据归一化继续复用金融合同。"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
import re
from pathlib import Path
from copy import deepcopy
from functools import wraps
from threading import RLock
from typing import Any

from .context import dumps


class DatasetRowsError(ValueError):
    def __init__(self, code: str, summary: str, **details):
        super().__init__(code)
        self.summary, self.details = summary, details


_ROW_KEYS = ("rows", "bars", "data", "kline_data", "prices", "historical", "quarterly", "results", "output")
_EARNINGS_TABLES = ("earnings_estimate", "eps_trend", "eps_revisions")
_SEC_METRICS = ("revenue", "gross_profit", "operating_income", "net_income", "eps", "total_assets",
                "total_liabilities", "cash_and_equivalents", "long_term_debt", "operating_cash_flow", "capital_expenditures", "free_cash_flow",
                "productive_asset_purchases", "free_cash_flow_after_productive_asset_purchases")
_ROW_CONTEXT = ("ticker", "market", "source", "source_url", "as_of", "source_latest_filed",
                "currency", "unit", "units", "frequency")
_SOURCE_FIELDS = {"id", "source_id", "data_ref", "title", "url", "snippet", "summary", "source", "source_name", "published_date", "as_of",
                  "confidence", "type", "kind", "reliability", "quality", "currency", "unit", "period", "price_basis", "dividends_included", "metadata", "meta", "limitations"}


def fact_metadata_preview(metadata: dict) -> dict:
    """保留财务口径及差分输入，不重复嵌套的申报全文。"""
    fields = {"unit", "concept", "period_start", "period_end", "reporting_basis", "derivation", "derived_from", "capital_expenditures_concept"}
    result = {}
    for metric, fact in metadata.items():
        if not isinstance(fact, dict):
            continue
        item = {key: value for key, value in fact.items() if key in fields and value is not None}
        if fact.get("derivation_inputs"):
            item["derivation_inputs"] = [{key: source[key] for key in ("metric", "value", "unit", "period_start", "period_end") if key in source}
                for source in fact["derivation_inputs"] if isinstance(source, dict)]
        result[metric] = item
    return result


def _rows_with_context(rows: list[dict], payload: dict, table: str | None = None) -> list[dict]:
    context = {key: payload[key] for key in _ROW_CONTEXT if key in payload}
    if table:
        context["source_table"] = table
    return deepcopy([{**context, **row} for row in rows])


def _companyfacts_rows(payload: dict) -> list[dict]:
    periods = payload.get("period_ends") or payload.get("periods") or []
    labels = payload.get("periods") or periods
    metrics = {key: payload[key] for key in _SEC_METRICS if key in payload}
    if not periods or not metrics:
        return []
    metadata = payload.get("fact_metadata") or {}
    # 平行数组只按原始下标对齐；缺值保留 None，不截短、不补零，也不混用各指标单位。
    if (len(labels) != len(periods)
            or any(not isinstance(values, list) or len(values) != len(periods) for values in metrics.values())
            or any(not isinstance(values, list) or len(values) != len(periods) for values in metadata.values())):
        raise DatasetRowsError("dataset_columns_misaligned", "财报指标与财期数量不一致，无法可靠对齐；请回读原始资料。")
    rows = [{"period": labels[index], "period_end": period,
             **{key: values[index] for key, values in metrics.items()},
             "fact_metadata": {key: values[index] for key, values in metadata.items()}}
            for index, period in enumerate(periods)]
    return _rows_with_context(rows, payload, "companyfacts")


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class RunData:
    def __init__(self, owner: str, session_id: str, run_id: str, query: str):
        self.owner, self.session_id, self.run_id, self.query = owner, session_id, run_id, query
        self._lock = RLock()
        self.records: dict[str, dict] = {}
        self.record_expires_at: dict[str, float] = {}
        self.sources: dict[str, dict] = {}
        self._source_links: dict[str, list[str]] = {}
        self.artifacts: list[dict] = []
        self.prior_artifacts: list[dict] = []
        self.steps: list[dict] = []
        self.results: dict[str, dict] = {}
        self.storage_dir = Path(os.getenv("FINSIGHT_ARTIFACT_DIR", str(Path(__file__).resolve().parents[2] / "data/agent_artifacts")))

    @_locked
    def record(self, tool: str, inputs: dict, output: Any, *, status: str = "success") -> str:
        # 财务空值和NumPy标量必须能进入标准JSON/JSONB；缺失不伪装成0。
        output = json.loads(dumps(output), parse_constant=lambda _value: None)
        encoded = dumps({"tool": tool, "inputs": inputs, "output": output, "status": status})
        ref = "dataset_" + hashlib.sha256(encoded.encode()).hexdigest()[:18]
        if ref in self.records:
            return ref
        if len(encoded.encode()) > 5_000_000:
            raise ValueError("tool_result_too_large")
        if sum(len(dumps(row)) for row in self.records.values()) + len(encoded) > 20_000_000:
            raise ValueError("run_data_budget_exhausted")
        self.records[ref] = {"tool": tool, "inputs": dict(inputs), "output": output, "status": status}
        self.record_expires_at[ref] = time.time() + 12 * 3600
        step = {"id": ref, "kind": "tool", "name": tool, "inputs": inputs, "task_ids": ["research"]}
        self.steps.append(step)
        self.results[ref] = {"output": output, "status": status}
        if status != "success" or output is None or output == "" or output == [] or output == {}:
            return ref
        try:
            from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
            state = {"query": self.query, "subject": {"subject_type": "company", "tickers": [inputs["ticker"]] if inputs.get("ticker") else []}}
            evidence, _, _ = normalize_execution_evidence(
                state=state, plan_ir={"steps": [step]}, artifacts={"step_results": {ref: self.results[ref]}},
                enrich_snippets=False)
        except (ValueError, TypeError, KeyError):
            evidence = []
        for item in evidence:
            self.add_source(item, ref)
        self._extract_sources(output, tool, ref)
        self._complete_source_metadata(ref)
        return ref

    def add_source(self, item: dict, ref: str) -> str:
        from .diagnostics import clean_text, safe_preview
        url = item.get("url") or item.get("link") or item.get("source_url")
        title = item.get("title") or item.get("source") or "工具证据"
        identity = str(url or item.get("source_id") or ref) + ref
        source_id = "S" + hashlib.sha256(identity.encode()).hexdigest()[:10]
        # 引用账本只保存来源投影；完整行情/财报仍由data_ref回读，不能在每个引用里复制整张表。
        citation = {key: item[key] for key in ("source", "source_name", "published_date", "as_of", "confidence", "type", "kind",
                    "reliability", "quality", "currency", "unit", "period", "price_basis", "dividends_included") if key in item}
        if item.get("limitations"):
            citation["limitations"] = safe_preview(item["limitations"], max_chars=1200)
        previous = {key: value for key, value in self.sources.get(source_id, {}).items() if key in _SOURCE_FIELDS}
        for key in ("metadata", "meta"):
            if isinstance(item.get(key), dict):
                previous_meta = previous.get(key) if isinstance(previous.get(key), dict) else {}
                citation[key] = {**previous_meta, **safe_preview(item[key], max_chars=3000)}
                if "subject_binding" in item[key]:
                    citation[key]["subject_binding"] = item[key]["subject_binding"]
                if previous_meta.get("subject_binding") == "unverified":
                    citation[key]["subject_binding"] = "unverified"
        snippet = item.get("snippet") or item.get("summary") or item.get("content")
        if isinstance(snippet, str):
            citation["snippet"] = clean_text(snippet, 1500)
        self.sources[source_id] = {**previous, **citation, "source_id": source_id, "title": clean_text(str(title), 300),
                                   "url": clean_text(url, 4096) if isinstance(url, str) and url.startswith(("http://", "https://")) else None,
                                   "data_ref": ref}
        links = self._source_links.setdefault(ref, [])
        if source_id not in links:
            links.append(source_id)
        return source_id

    def _extract_sources(self, value: Any, tool: str, ref: str, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(value, dict):
            if value.get("url") or value.get("source_url") or value.get("source") or value.get("as_of"):
                self.add_source(value, ref)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    self._extract_sources(child, tool, ref, depth + 1)
        elif isinstance(value, list):
            for item in value[:100]:
                self._extract_sources(item, tool, ref, depth + 1)
        elif isinstance(value, str) and depth == 0:
            # 搜索/公司资料的旧工具仍返回文本；真实链接也必须进入引用账本。
            for line in value.splitlines():
                for url in re.findall(r"https?://[^\s<>\"]+", line):
                    self.add_source({"title": tool, "url": url.rstrip(".,，。；;）)]}"), "snippet": line}, ref)
        if depth == 0 and not any(x.get("data_ref") == ref for x in self.sources.values()):
            self.add_source({"title": tool, "source": tool, "limitations": ["来源时点以原始工具结果为准"]}, ref)

    def _complete_source_metadata(self, ref: str) -> None:
        """同一次工具的无链接摘要继承其唯一真实出处，并保留输入参数供用户核对。"""
        record = self.records[ref]
        entries = [self.sources[sid] for sid in self._source_links.get(ref, [])]
        linked = [source for source in entries if source.get("url")]
        urls = {source["url"] for source in linked}
        output = record["output"]
        inputs = {key: value for key, value in record["inputs"].items()
                  if key in {"ticker", "period", "interval", "operation", "window", "frequency", "limit"}}
        metadata = {"tool": record["tool"], "parameters": inputs}
        if isinstance(output, dict):
            for key in ("as_of", "observed_at", "currency", "unit", "period", "price_basis", "dividends_included"):
                if key in output:
                    metadata[key] = output[key]
            if isinstance(output.get("method"), dict):
                from .diagnostics import safe_preview
                metadata["method"] = safe_preview({key: value for key, value in output["method"].items()
                    if key not in {"code", "code_hash", "input_hash"}}, max_chars=1600)
        for source in entries:
            source["metadata"] = {**metadata, **(source.get("metadata") or {})}
            if not source.get("url") and len(urls) == 1:
                origin = linked[0]
                source["url"] = origin["url"]
                for key in ("source", "source_name", "as_of", "published_date", "currency", "unit", "price_basis", "dividends_included"):
                    if origin.get(key) is not None and (not source.get(key) or source.get(key) == record["tool"]):
                        source[key] = origin[key]

    def read(self, data_ref: str, offset: int = 0, max_chars: int = 6000) -> dict:
        if data_ref not in self.records:
            raise ValueError("dataset_not_found_in_this_run")
        raw = dumps(self.records[data_ref])
        offset, max_chars = max(0, offset), max(100, min(max_chars, 8000))
        return {"data_ref": data_ref, "offset": offset, "total_chars": len(raw),
                "content": raw[offset:offset + max_chars], "next_offset": min(len(raw), offset + max_chars),
                "has_more": offset + max_chars < len(raw)}

    def rows(self, ref: str, table: str | None = None) -> list[dict]:
        if ref not in self.records:
            raise ValueError("dataset_not_found_in_this_run")
        if table is not None and not isinstance(table, str):
            raise DatasetRowsError("dataset_table_invalid", "数据表名称必须是字符串。")
        if self.records[ref]["tool"] == "run_analysis_code":
            # 用户代码允许命名结果表，但多张表不能靠字典顺序猜测或混合。
            tables = {}

            def collect(value, path="", depth=0):
                if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
                    tables[path or "rows"] = value
                elif isinstance(value, dict) and depth < 6:
                    for key, child in value.items():
                        if key not in {"method", "sources", "source_refs", "fact_metadata"}:
                            collect(child, f"{path}.{key}" if path else key, depth + 1)

            collect(self.records[ref]["output"])
            if table is not None:
                if table not in tables:
                    raise DatasetRowsError("dataset_table_unavailable", "找不到指定的数据表，请从 available_tables 选择。", available_tables=list(tables))
                return deepcopy(tables[table])
            if len(tables) > 1:
                raise DatasetRowsError("dataset_table_required", "计算结果有多张表，请用 table 指定要画图或分析的那一张。",
                                       available_tables=list(tables), required_parameters=["table"])
            return deepcopy(next(iter(tables.values()), []))

        def find(value, selected=table):
            if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
                if selected is not None:
                    raise DatasetRowsError("dataset_table_unavailable", "指定的数据表不存在，请回读资料中的表名。")
                return deepcopy(value)
            if isinstance(value, dict):
                if value.get("source") == "sec_companyfacts":
                    if selected not in (None, "companyfacts"):
                        raise DatasetRowsError("dataset_table_unavailable", "SEC 财报可选择 companyfacts 表。",
                                               available_tables=["companyfacts"])
                    return _companyfacts_rows(value)
                tables = [key for key in _EARNINGS_TABLES if isinstance(value.get(key), list)]
                if tables:
                    available = [key for key in tables if value[key]]
                    if selected is None and len(available) > 1:
                        raise DatasetRowsError("dataset_table_required", "盈利预期包含不同口径的数据表，请用 parameters.table 选择一张表。",
                                               available_tables=available, required_parameters=["table"])
                    chosen = selected or (available[0] if available else None)
                    if chosen is None:
                        return []
                    if chosen not in tables:
                        raise DatasetRowsError("dataset_table_unavailable", "指定的数据表不存在，请从 available_tables 选择。",
                                               available_tables=available)
                    return _rows_with_context(find(value[chosen], None), value, chosen)
                if selected in _ROW_KEYS and selected in value:
                    return _rows_with_context(find(value[selected], None), value, selected)
                for key in _ROW_KEYS:
                    if key in value:
                        rows = find(value[key], selected)
                        if rows:
                            return _rows_with_context(rows, value)
            return []
        return find(self.records[ref]["output"])

    def source_refs(self, data_ref: str, _seen: set[str] | None = None) -> list[str]:
        seen = set(_seen or ())
        if data_ref in seen:
            return []
        seen.add(data_ref)
        refs = list(self._source_links.get(data_ref, []))
        inputs = self.records.get(data_ref, {}).get("inputs", {})
        parents = inputs.get("dataset_refs") or ([inputs["dataset_ref"]] if inputs.get("dataset_ref") else [])
        for parent in parents:
            refs.extend(self.source_refs(parent, seen))
        return list(dict.fromkeys(refs))

    @_locked
    def snapshot(self) -> dict:
        return deepcopy({"records": self.records, "sources": self.sources, "artifacts": self.artifacts,
                         "prior_artifacts": self.prior_artifacts,
                         "source_links": self._source_links, "record_expires_at": self.record_expires_at})

    def _path(self, run_id: str) -> Path:
        scope = hashlib.sha256((self.owner + ":" + self.session_id).encode()).hexdigest()[:32]
        return self.storage_dir / scope / (hashlib.sha256(run_id.encode()).hexdigest()[:32] + ".json")

    def save(self) -> None:
        path = self._path(self.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": "finsight-run-data.v1", "owner": self.owner, "session_id": self.session_id, "run_id": self.run_id,
                   "expires_at": max(self.record_expires_at.values(), default=time.time() + 12 * 3600), **self.snapshot()}
        encoded = dumps(payload)
        self.cleanup_expired()
        current_size = path.stat().st_size if path.exists() else 0
        used = sum(candidate.stat().st_size for candidate in self.storage_dir.glob("*/*.json") if candidate.is_file())
        maximum = max(16, int(os.getenv("FINSIGHT_ARTIFACT_CACHE_MAX_MB", "512"))) * 1024 * 1024
        if used - current_size + len(encoded.encode("utf-8")) > maximum:
            raise OSError("artifact_cache_capacity_exceeded")
        temporary = path.with_suffix("." + uuid.uuid4().hex[:8] + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, path)

    def cleanup_expired(self) -> int:
        """只清理本运行时标记、已过期且位于缓存根内的文件，不接触历史/报告/数据库。"""
        root = self.storage_dir.resolve()
        count = 0
        for path in self.storage_dir.glob("*/*.json"):
            if (not re.fullmatch(r"[0-9a-f]{32}\.json", path.name) or path.is_symlink()
                    or not path.resolve().is_relative_to(root) or time.time() - path.stat().st_mtime < 12 * 3600):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value.get("format") == "finsight-run-data.v1" and value.get("expires_at", 0) < time.time():
                    path.unlink()
                    count += 1
            except (OSError, ValueError):
                continue
        return count

    def restore(self, parent_run_id: str) -> bool:
        path = self._path(parent_run_id)
        if not path.is_file() or path.stat().st_size > 30_000_000:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (payload.get("owner") != self.owner or payload.get("session_id") != self.session_id
                or payload.get("run_id") != parent_run_id or payload.get("expires_at", 0) < time.time()):
            return False
        expiries = payload.get("record_expires_at") or {}
        records = payload.get("records") or {}
        from .completeness import output_status
        records = {ref: record for ref, record in records.items()
                   if record.get("status") == "success" and output_status(record.get("output")) == "success"}
        now = time.time()
        self.record_expires_at = {ref: float(expiries.get(ref, payload["expires_at"])) for ref in records
                                  if float(expiries.get(ref, payload["expires_at"])) > now}
        self.records = {ref: record for ref, record in records.items() if ref in self.record_expires_at}
        self.sources = {sid: {key: value for key, value in source.items() if key in _SOURCE_FIELDS} for sid, source in (payload.get("sources") or {}).items()
                        if source.get("data_ref") in self.records}
        self._source_links = {ref: [sid for sid in links if sid in self.sources]
                              for ref, links in (payload.get("source_links") or {}).items() if ref in self.records}
        # 只保留历史图表的可核验投影，不把旧图当作新产物重复交付。
        prior = {}
        for artifact in [*(payload.get("prior_artifacts") or []), *(payload.get("artifacts") or [])]:
            refs = artifact.get("dataset_refs") or []
            if artifact.get("kind") == "chart" and refs and all(ref in self.records for ref in refs):
                prior[artifact["artifact_id"]] = {key: artifact[key] for key in
                    ("artifact_id", "kind", "title", "dataset_refs", "source_refs", "spec", "coverage", "method", "limitations") if key in artifact}
        self.prior_artifacts = list(prior.values())[-30:]
        return bool(self.records)

