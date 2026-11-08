"""研究文字的数值/日期闭卷约束；共享于旧合成与自主运行时。"""
from __future__ import annotations
import re


_SCALES = {"万亿": 1e12, "千亿": 1e11, "十亿": 1e9, "千万": 1e7, "百万": 1e6,
           "亿": 1e8, "万": 1e4, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12,
           "thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12, "%": .01}
_UNIT_PATTERN = r"万亿|千亿|十亿|千万|百万|亿|万|trillions?|billions?|millions?|thousands?|[KMBT]|%"
_NUMERIC_PATTERN = re.compile(r"(?<![A-Za-z0-9])([-+]?\d[\d,]*(?:\.\d+)?)(?:[ \t]*(" + _UNIT_PATTERN + r"))?(?![A-Za-z0-9])", re.I)


def _scale(unit: str | None) -> float:
    if not unit:
        return 1
    normalized = unit.upper() if len(unit) == 1 else unit.lower().rstrip("s")
    return _SCALES.get(normalized, 1)


def _table_amount_scales(text: str) -> list[tuple[int, int, float]]:
    """金额表头的单位仅授予金额列；日期、每股值、倍数、比例和数量列保留原单位。"""
    monetary = r"金额|营收|收入|利润|毛利|现金流|支出|资本开支|市值|资产|负债|债务|现金|amount|revenue|income|profit|cash|capex|assets?|liabilit|debt|market.cap|value"
    nonmonetary = r"EPS|每股|股价|价格|price|倍数|P/E|P/B|P/S|比率|率|percent|ratio|%|日期|财期|期间|季度|date|period|数量|股数|shares|count"
    scale_pattern = re.compile(r"(?<![A-Za-z])(?:" + _UNIT_PATTERN + r")(?![A-Za-z])", re.I)
    currency = re.compile(r"USD|HKD|CNY|EUR|GBP|美元|港元|人民币|欧元|英镑", re.I)
    ranges, columns = [], []
    recent = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped.startswith("|"):
            columns = []
            recent = (recent + [stripped])[-3:]
            offset += len(line)
            continue
        cells = line.rstrip("\r\n").split("|")
        if re.fullmatch(r"[|\s:\-]+", stripped):
            offset += len(line)
            continue
        if not columns:
            common = next((match[0] for previous in reversed(recent)
                           if re.search(r"单位|unit|in\s+(?:USD|millions?|billions?|trillions?)", previous, re.I)
                           and currency.search(previous) and (match := scale_pattern.search(previous))), None)
            columns = []
            for cell in cells:
                explicit = scale_pattern.search(cell)
                amount_column = bool(re.search(monetary, cell, re.I)) and not re.search(nonmonetary, cell, re.I)
                columns.append(_scale(explicit[0] if explicit else common) if amount_column else 1)
        else:
            position = offset
            for index, cell in enumerate(cells):
                if index < len(columns) and columns[index] != 1:
                    ranges.append((position, position + len(cell), columns[index]))
                position += len(cell) + 1
        offset += len(line)
    return ranges


def validate_grounded_quantities(text: str, grounding: str) -> None:
    available = [float(match.group(1).replace(",", "")) * _scale(match.group(2)) for match in _NUMERIC_PATTERN.finditer(grounding)]
    enumeration_spans = [match.span(1) for match in re.finditer(r"(?m)^\s*(?:[-*]\s*)?(\d+)[.)、](?:\s|[^\d])", text)]
    table_scales = _table_amount_scales(text)
    for match in _NUMERIC_PATTERN.finditer(text):
        if any(start <= match.start(1) < end for start, end in enumeration_spans):
            continue
        token = match.group(1).replace(",", "")
        scale = _scale(match.group(2)) if match.group(2) else next(
            (scale for start, end, scale in table_scales if start <= match.start(1) < end), 1)
        requested = float(token) * scale
        places = len(token.split(".", 1)[1]) if "." in token else 0
        tolerance = max(1e-9, 0.5 * 10 ** (-places) * scale)
        if not any(abs(requested - value) <= tolerance for value in available):
            raise ValueError("explanation_contains_unbound_number")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if any(date not in grounding for date in dates):
        raise ValueError("explanation_contains_unbound_date")

