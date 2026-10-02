"""Shared extraction of JSON objects from model text."""

from __future__ import annotations

import json
import re
from typing import Any


def _extract_json(text: str) -> dict[str, Any] | None:
    """从 LLM 文本里抽取第一个 JSON 对象。

    容忍：```json 代码块包裹、推理模型的 <think>...</think> 思考前缀、前后多余文字。
    """
    if not text:
        return None
    cleaned = text.strip()
    # 剥离推理模型（mimo 等）的思考标签（可能未闭合——被 max_tokens 截断时只剩开头）
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    # 去掉 markdown 代码块围栏
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # 直接尝试整体解析
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    # 退而求其次：抓取首个 {...} 片段
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None
