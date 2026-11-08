"""研究文字的数值/日期闭卷约束；共享于旧合成与自主运行时。"""
from __future__ import annotations
import re


def validate_grounded_quantities(text: str, grounding: str) -> None:
    numeric_pattern = re.compile(r"(?<![A-Za-z0-9])([-+]?\d[\d,]*(?:\.\d+)?)(?:[ \t]*(亿|万|[KMBT]|%))?(?![A-Za-z0-9])")
    scales = {"亿": 100_000_000, "万": 10_000, "K": 1000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000, "%": 0.01}
    available = [float(match.group(1).replace(",", "")) * scales.get(match.group(2), 1) for match in numeric_pattern.finditer(grounding)]
    enumeration_spans = [match.span(1) for match in re.finditer(r"(?m)^\s*(?:[-*]\s*)?(\d+)[.)、](?:\s|[^\d])", text)]
    for match in numeric_pattern.finditer(text):
        if any(start <= match.start(1) < end for start, end in enumeration_spans):
            continue
        token = match.group(1).replace(",", "")
        scale = scales.get(match.group(2), 1)
        requested = float(token) * scale
        places = len(token.split(".", 1)[1]) if "." in token else 0
        tolerance = max(1e-9, 0.5 * 10 ** (-places) * scale)
        if not any(abs(requested - value) <= tolerance for value in available):
            raise ValueError("explanation_contains_unbound_number")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if any(date not in grounding for date in dates):
        raise ValueError("explanation_contains_unbound_date")

