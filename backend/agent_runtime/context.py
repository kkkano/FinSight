"""通用 JSON 序列化与本地模型令牌估算。"""
from __future__ import annotations

import base64
import math
from functools import lru_cache
from pathlib import Path
from typing import Any


def dumps(value: Any) -> str:
    from backend.common.json_utils import json_dumps_safe
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
