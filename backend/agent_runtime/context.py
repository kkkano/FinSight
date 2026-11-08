"""有界模型上下文；完整工具结果保留在运行资料中。"""
from __future__ import annotations

import copy
import json
from typing import Any


def dumps(value: Any) -> str:
    from backend.graph.json_utils import json_dumps_safe
    return json_dumps_safe(value, ensure_ascii=False)


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
    # 不在请求路径下载tokenizer资产。UTF-8字节数是保守的token上界，实际usage另行结算。
    return max(1, len(text.encode("utf-8")) + image_budget)


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
    from .diagnostics import safe_preview
    original = value.get("result", value) if isinstance(value, dict) else value
    references = {key: value[key] for key in ("data_refs", "source_refs") if isinstance(value, dict) and key in value}
    preview = safe_preview(original, max_chars=min(limit, 4500))
    if (isinstance(original, dict) and isinstance(preview, dict) and "comparison_stats" in preview
            and isinstance(original.get("comparison_stats"), dict)):
        # 比较统计已是有界摘要；从自身起算层级，避免4个交叉日期被缩成“条目数4”。
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
    for i, message in enumerate(result):
        if message.get("role") not in {"user", "assistant"} or message.get("tool_calls") or i in protected_users:
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
        message["content"] = dumps({"context_pruned": True, "data_refs": [x for x in refs if x],
                                   "summary": content[:500],
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
        for start, end in groups[:-1]:
            entry = {"tools": [call.get("function", {}).get("name") for call in result[start]["tool_calls"]],
                     "data_refs": [], "results": []}
            for message in result[start + 1:end]:
                try:
                    data = json.loads(message.get("content") or "{}")
                except ValueError:
                    data = {}
                if isinstance(data, dict):
                    refs = data.get("data_refs") or ([data["data_ref"]] if data.get("data_ref") else [])
                    entry["data_refs"].extend(refs)
                    nested = data.get("result") if isinstance(data.get("result"), dict) else data
                    entry["results"].append({key: nested[key] for key in
                        ("status", "error", "currency", "unit", "period", "as_of") if key in nested})
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
        raise ValueError("context_window_exhausted")
    return result

