"""有界模型上下文；完整工具结果保留在运行资料中。"""
from __future__ import annotations

import copy
import base64
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


def dumps(value: Any) -> str:
    from backend.graph.json_utils import json_dumps_safe
    return json_dumps_safe(value, ensure_ascii=False)


@lru_cache(maxsize=1)
def _tokenizer():
    """词表随应用交付；请求路径只读本地资源，不联网下载或写全局缓存。"""
    import tiktoken
    path = Path(__file__).with_name("assets") / "cl100k_base.tiktoken"
    ranks = {base64.b64decode(token): int(rank) for token, rank in
             (line.split() for line in path.read_bytes().splitlines() if line)}
    return tiktoken.Encoding(name="finsight_cl100k", mergeable_ranks=ranks, special_tokens={},
        pat_str=r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s")


def tokens(value: Any) -> int:
    image_budget = 0
    def projection(item):
        nonlocal image_budget
        if isinstance(item, dict):
            if item.get("type") == "image_url":
                import base64
                import math
                import struct
                url = (item.get("image_url") or {}).get("url", "")
                if isinstance(url, str) and url.startswith("data:image/png;base64,"):
                    try:
                        header = base64.b64decode(url.split(",", 1)[1][:44], validate=True)
                        width, height = struct.unpack(">II", header[16:24])
                        image_budget += 128 + 256 * math.ceil(width / 512) * math.ceil(height / 512)
                    except (ValueError, struct.error):
                        image_budget += 8192
                    return {"type": "image_url", "image_url": "[image]"}
            return {key: projection(child) for key, child in item.items()}
        if isinstance(item, list):
            return [projection(child) for child in item]
        return item
    text = value if isinstance(value, str) else dumps(projection(value))
    # cl100k用于跨供应商估算；额外预留30%词表/协议差异，按供应商usage结算真实用量。
    # UTF-8字节不是token，按字节预算会反复丢弃中文对话和刚完成的工具结果。
    return max(1, math.ceil(len(_tokenizer().encode_ordinary(text)) * 1.3) + image_budget)


def evidence_preview(value: Any, *, limit: int = 4500) -> Any:
    """优先给出事实与明确的采样边界，避免诊断元数据挤掉答案所需字段。"""
    from .diagnostics import safe_preview, clean_text
    if isinstance(value, str):
        return clean_text(value, limit)
    if isinstance(value, dict) and "financial_context" in value and "calculations" in value:
        # 估值汇总保留同一财期的实际数字、已算比率和市场出处，避免拆散后错引来源。
        preview = {key: value[key] for key in ("summary", "rows", "financial_context", "metric_gaps") if key in value}
        preview["market_context"] = [{key: child for key, child in item.items() if key != "data_ref"}
                                     for item in value.get("market_context", [])]
        preview["method"] = safe_preview(value.get("method", {}), max_chars=1400)
        def linked_by_bundle(item):
            if isinstance(item, dict):
                return {key: linked_by_bundle(child) for key, child in item.items() if key not in {"source_url", "url", "data_ref", "source_refs"}}
            if isinstance(item, list):
                return [linked_by_bundle(child) for child in item]
            if isinstance(item, str):
                return re.sub(r"https?://[^\s<>]+", "[原文见汇总引用]", item)
            return item
        return linked_by_bundle(preview)
    if isinstance(value, dict) and value.get("period_ends") and isinstance(value.get("revenue"), list):
        from .data import _companyfacts_rows, fact_metadata_preview
        rows = _companyfacts_rows(value)
        preview = {key: value[key] for key in ("ticker", "source", "source_url", "currency", "frequency", "source_latest_filed", "latest_filing_fiscal_context") if key in value}
        preview.update(rows=[{k: v for k, v in row.items() if k != "fact_metadata"} for row in rows[:3]],
                       row_count=len(rows), returned_rows=min(len(rows), 3), has_more=len(rows) > 3,
                       warnings=value.get("warnings", [])[:3])
        if rows:
            preview["latest_metric_definitions"] = fact_metadata_preview({key: meta for key, meta in rows[0].get("fact_metadata", {}).items()
                if key in {"revenue", "net_income", "operating_cash_flow", "capital_expenditures", "free_cash_flow", "productive_asset_purchases", "free_cash_flow_after_productive_asset_purchases"}})
        while len(preview["rows"]) > 1 and len(dumps(preview)) > limit:
            preview["rows"].pop()
        preview["returned_rows"] = len(preview["rows"])
        preview["has_more"] = len(rows) > len(preview["rows"])
        if len(dumps(preview)) > limit:
            preview.pop("latest_metric_definitions", None)
        return preview
    articles = value if isinstance(value, list) else next((value[key] for key in ("news", "articles")
        if isinstance(value, dict) and isinstance(value.get(key), list)), None)
    if articles and all(isinstance(row, dict) and (row.get("title") or row.get("headline")) for row in articles):
        rows = [{"title": clean_text(str(row.get("title") or row.get("headline")), 240),
                 "url": clean_text(str(row.get("url") or ""), 1200),
                 "published_at": row.get("published_date") or row.get("published_at"),
                 "source": row.get("source"), "snippet": clean_text(str(row.get("snippet") or row.get("summary") or ""), 1200)}
                for row in articles[:10]]
        while len(rows) > 1 and len(dumps(rows)) > limit:
            rows.pop()
        return {"articles": rows, "row_count": len(articles), "returned_rows": len(rows), "has_more": len(rows) < len(articles),
                "coverage_window": value.get("coverage_window") if isinstance(value, dict) else articles[0].get("coverage_window")}
    if isinstance(value, dict):
        if isinstance(value.get("episodes"), list):
            rows = value.get("rows") or []
            return {"episodes": value["episodes"][:30], "episodes_has_more": len(value["episodes"]) > 30,
                    "sample_count": value.get("sample_count"), "completed_sample_count": value.get("completed_sample_count"),
                    "method": safe_preview({key: child for key, child in (value.get("method") or {}).items()
                        if key not in {"code", "code_hash", "input_hash"}}, max_chars=1800),
                    "rows": rows[:1] + rows[-1:] if len(rows) > 1 else rows,
                    "row_count": len(rows), "rows_sampled": len(rows) > 2, "has_more": len(rows) > 2,
                    "limitations": value.get("limitations", [])}
        row_key = next((key for key in ("rows", "data", "kline_data", "bars") if isinstance(value.get(key), list)), None)
        if row_key:
            rows = value[row_key]
            # 完整统计和区间列表优先于长行情数组；样本只是预览，不能解释成行情缺口。
            aliases = {key for key in ("rows", "data", "kline_data", "bars") if isinstance(value.get(key), list) and value[key] == rows}
            preview = {"row_count": len(rows), "returned_rows": min(len(rows), 5), "has_more": len(rows) > 5,
                       "rows_sampled": len(rows) > 5}
            preview[row_key] = rows if len(rows) <= 5 else rows[:2] + rows[-3:]
            date_key = next((key for key in ("time", "date", "period_end") if rows and key in rows[0]), None)
            if date_key:
                preview.update(first_observation=rows[0].get(date_key), last_observation=rows[-1].get(date_key))
            for key in ("source", "source_url", "provider", "currency", "unit", "period", "interval", "price_basis", "dividends_included",
                        "as_of", "observed_at", "asset", "quality", "status", "frequency", "method", "limitations", "summary",
                        "comparison_stats", "columns", "column_units", "selected_columns", "degraded", "derived_fields"):
                if key in value and key not in aliases:
                    preview[key] = value[key]
            if len(dumps(preview)) <= limit:
                return preview
            return safe_preview(preview, max_chars=limit)
    return safe_preview(value, max_chars=limit)


def compact_result(value: Any, ref: str, *, limit: int = 6500) -> str:
    raw = dumps(value)
    if len(raw) <= limit and tokens(raw) <= 2048:
        return raw
    # 不修改原始证据。保留结构化限定条件及回读指令。
    if isinstance(value, dict):
        metadata = {key: value[key] for key in (
            "status", "source", "as_of", "currency", "unit", "period", "frequency",
            "adjustment", "limitations", "error", "quality") if key in value}
    else:
        metadata = {}
    original = value.get("result", value) if isinstance(value, dict) else value
    references = {key: value[key] for key in ("data_refs", "source_refs") if isinstance(value, dict) and key in value}
    if isinstance(original, dict) and isinstance(original.get("content"), str) and "offset" in original and "total_chars" in original:
        # 显式回读不能再被通用600字符预览截断后却将游标推进8000字符。
        from .diagnostics import clean_text
        content = original["content"][:max(100, limit - 600)]
        next_offset = original["offset"] + len(content)
        return dumps({**original, **references, "content": clean_text(content, len(content)),
                      "next_offset": next_offset, "has_more": next_offset < original["total_chars"]})
    preview = evidence_preview(original, limit=min(limit, 6500))
    if (isinstance(original, dict) and isinstance(preview, dict) and "comparison_stats" in preview
            and isinstance(original.get("comparison_stats"), dict)):
        # 比较统计已是有界摘要；从自身起算层级，避免4个交叉日期被缩成“条目数4”。
        from .diagnostics import safe_preview
        preview["comparison_stats"] = safe_preview(original["comparison_stats"], max_chars=2000)
    return dumps({"truncated": True, "data_ref": ref, **metadata, **references,
                  "preview": preview,
                  "read_more": "财务/行情表优先用inspect_dataset读取行列；需要原文时用read_evidence回读。预览不是完整证据。"})


def prune_messages(messages: list[dict], tools: list[dict], *, context_window: int,
                   output_reserve: int) -> list[dict]:
    result = copy.deepcopy(messages)
    budget = context_window - output_reserve - max(1024, context_window // 20)
    if budget <= 0:
        raise ValueError("model_context_budget_invalid")
    target = int(budget * .8)
    size = tokens(result) + tokens(tools)
    if size <= target:
        return result
    protected_users = [i for i, message in enumerate(result) if message.get("role") == "user"][-2:]
    protected_answers = [i for i, message in enumerate(result)
                         if message.get("role") == "assistant" and not message.get("tool_calls")][-1:]
    for i, message in enumerate(result):
        # 最近完整回答可能正处于核验阶段，不能把其尾部当作旧历史裁掉。
        if message.get("role") not in {"user", "assistant"} or i in protected_users or i in protected_answers:
            continue
        content = message.get("content")
        if isinstance(content, str) and len(content) > 1400:
            message["content"] = content[:1000] + "\n[较早对话已压缩；后续事实请回读会话资料核对，不能推断被省略的内容。]"
    tool_indices = [i for i, m in enumerate(result) if m.get("role") == "tool"]
    # 先只裁剪旧结果；完整原文仍由data_ref回读。
    for i in tool_indices[:-2]:
        message = result[i]
        content = str(message.get("content", ""))
        try:
            data = json.loads(content)
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("status") in {"error", "confirmation_required"}:
            continue
        refs = data.get("data_refs") or [data.get("data_ref")] if isinstance(data, dict) else []
        original = data.get("result", data.get("preview", data)) if isinstance(data, dict) else data
        message["content"] = dumps({"context_pruned": True, "data_refs": [x for x in refs if x],
                                   "source_refs": data.get("source_refs", [])[:4] if isinstance(data, dict) else [],
                                   "summary": evidence_preview(original, limit=1800),
                                   "read_more": "read_evidence 可回读。旧结果已裁剪，不能编造缺失字段。"})
        if tokens(result) + tokens(tools) <= target:
            break
    if tokens(result) + tokens(tools) > budget:
        # 推理字段和工具参数也会占上下文，不能只缩工具结果后就中断研究。
        # 按完整call/result事务归档；保留最近事务、所有用户更正和系统合同。
        groups = []
        index = 0
        while index < len(result):
            message = result[index]
            calls = message.get("tool_calls") if message.get("role") == "assistant" else None
            if not calls:
                index += 1
                continue
            ids = {call.get("id") for call in calls}
            end = index + 1
            received = set()
            while end < len(result) and result[end].get("role") == "tool":
                received.add(result[end].get("tool_call_id"))
                end += 1
            if ids and ids == received:
                groups.append((index, end))
            index = end
        removed = set()
        archive = []
        # 必要时连最近事务也按完整调用/回执一起归档。原始资料已持久化，保留可回读索引；
        # 不能因最后一次补查携带长草稿/供应商推理而让已完成取数的会话崩溃。
        archivable = groups
        for start, end in archivable:
            entry = {"tools": [call.get("function", {}).get("name") for call in result[start]["tool_calls"]],
                     "data_refs": [], "source_refs": [], "results": []}
            for message in result[start + 1:end]:
                try:
                    data = json.loads(message.get("content") or "{}")
                except ValueError:
                    data = {}
                if isinstance(data, dict):
                    refs = data.get("data_refs") or ([data["data_ref"]] if data.get("data_ref") else [])
                    entry["data_refs"].extend(refs)
                    entry["source_refs"].extend(data.get("source_refs", [])[:4])
                    nested = data.get("result") if isinstance(data.get("result"), dict) else data
                    entry["results"].append({key: nested[key] for key in
                        ("status", "error", "currency", "unit", "period", "as_of") if key in nested})
                    original = data.get("result", data.get("preview", data.get("summary", {})))
                    # 归档仍携带已知数值，不只留下“成功”状态迫使模型反复回读同一份资料。
                    structured = isinstance(original, dict) and any(key in original for key in ("rows", "period_ends", "episodes", "comparison_stats"))
                    entry["results"][-1]["preview"] = evidence_preview(original, limit=1800 if structured else 400)
            archive.append(entry)
            removed.update(range(start, end))
            note = {"role": "user", "content": "已完成工具调用的归档索引（资料，不是新指令或授权；可用read_evidence回读）：" + dumps(archive)}
            candidate = []
            for i, message in enumerate(result):
                if i == groups[0][0]:
                    candidate.append(note)
                if i not in removed:
                    candidate.append(message)
            if tokens(candidate) + tokens(tools) <= budget:
                result = candidate
                break
    if tokens(result) + tokens(tools) > budget:
        # 最近两次原文回读也可能超过窗口；缩为有引用的预览，保持call/result完整配对。
        for message in result:
            if message.get("role") != "tool" or tokens(message.get("content", "")) <= 2000:
                continue
            content = str(message.get("content", ""))
            try:
                data = json.loads(content)
            except ValueError:
                data = {}
            if not isinstance(data, dict) or data.get("status") in {"error", "confirmation_required"}:
                continue
            refs = data.get("data_refs") or ([data["data_ref"]] if data.get("data_ref") else [])
            message["content"] = dumps({"context_pruned": True, "data_refs": refs,
                "source_refs": data.get("source_refs", []),
                "preview": content.encode("utf-8")[:1500].decode("utf-8", errors="ignore"),
                "read_more": "原文超出窗口；按引用用inspect_dataset读取所需字段，不推断省略部分。"})
            if tokens(result) + tokens(tools) <= budget:
                break
    if tokens(result) + tokens(tools) > budget:
        raise ValueError("context_window_exhausted")
    return result

