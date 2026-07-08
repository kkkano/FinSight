# -*- coding: utf-8 -*-
"""
WP2-Task7: 证据黑板（ORC-05 / D5）。

星型黑板：executor 在 agent step 完成后写入单行摘要，后续 agent step
启动前把全部摘要（排除自己）注入其 inputs["__context_digest"]。
不做点对点消息（YAGNI）。
"""
from __future__ import annotations

from typing import Any

_DIGEST_MAX_CHARS = 300
_SUMMARY_SLICE = 180
_EVIDENCE_TITLES = 2


def digest_agent_output(agent_name: str, output: Any) -> str:
    """一条 ≤300 字符的单行摘要：'{agent}: {summary截断} | evidence: {前2条标题}'。

    output 非 dict 或无 summary → 返回 ''。
    """
    if not isinstance(output, dict):
        return ""
    summary = str(output.get("summary") or "").strip().replace("\n", " ")
    if not summary:
        return ""
    digest = f"{agent_name}: {summary[:_SUMMARY_SLICE]}"
    titles: list[str] = []
    evidence = output.get("evidence")
    if isinstance(evidence, list):
        for item in evidence[:_EVIDENCE_TITLES]:
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
                if title:
                    titles.append(title)
    if titles:
        digest = f"{digest} | evidence: {'; '.join(titles)}"
    return digest[:_DIGEST_MAX_CHARS]


def render_bus(bus: dict[str, str], *, exclude: str, limit_chars: int = 1200) -> str:
    """按写入顺序拼接（排除自己），超限从最旧开始丢弃。"""
    lines = [text for name, text in bus.items() if name != exclude and text]
    while lines and sum(len(line) + 1 for line in lines) > limit_chars:
        lines.pop(0)
    return "\n".join(lines)


__all__ = ["digest_agent_output", "render_bus"]
