"""本人研究消息的展示投影；思考与工具详情不作为金融证据或公开报告正文。"""
from __future__ import annotations

from copy import deepcopy
import re
import math

from .diagnostics import clean_text, safe_preview

MAX_PROVIDER_REASONING_CHARS = 20_000


def repair_has_complete_ending(text: str) -> bool:
    """修正长答须以完整句子或完整Markdown块结束，不能用半句覆盖原稿。"""
    value = text.strip()
    if not value or value.count("```") % 2:
        return False
    last = value.splitlines()[-1].strip()
    if re.match(r"^#{1,6}\s", last):
        return False
    if len(value) < 200:
        return True
    if last.endswith("```") or last.startswith("|") and last.endswith("|"):
        return True
    if re.search(r"\]\([^\n)]+\)$|https?://\S+$|\[(?:S[a-fA-F0-9]+|\d+)\]$", last):
        return True
    return bool(re.search(r'''[。！？.!?；;][”’"'）)\]*_]*$''', last))


class PublicTextFilter:
    """过滤供应商混入正文的内部工具标记；不解析或执行其中的指令。"""
    prefixes = ("<｜DSML｜", "</｜DSML｜", "<|DSML|", "</|DSML|")

    def __init__(self):
        self.pending = ""

    def feed(self, text: str) -> str:
        self.pending += text
        result = []
        while self.pending:
            start = self.pending.find("<")
            if start < 0:
                result.append(self.pending); self.pending = ""; break
            if start:
                result.append(self.pending[:start]); self.pending = self.pending[start:]
            if any(prefix.startswith(self.pending) for prefix in self.prefixes):
                break
            if any(self.pending.startswith(prefix) for prefix in self.prefixes):
                end = self.pending.find(">")
                if end < 0:
                    if len(self.pending) > 1024:
                        self.pending = ""
                    break
                self.pending = self.pending[end + 1:]
                continue
            result.append("<"); self.pending = self.pending[1:]
        return "".join(result)

    def finish(self) -> str:
        text, self.pending = self.pending, ""
        return "" if any(text.startswith(prefix) or (text != "<" and prefix.startswith(text)) for prefix in self.prefixes) else text


def clean_public_text(text: str, agent_labels: dict[str, str] | None = None) -> str:
    text = re.sub(r"</?[|｜]DSML[|｜][^>]*>", "", text, flags=re.I)
    text = re.sub(r"\A\s*(?:核对后的段落|修正后的回答|修正后的结论)\s*[:：]\s*", "", text)
    text = re.sub(r"\A\s*以下修正后的结论", "以下结论", text)
    parts = re.split(r"(```[\s\S]*?```)", text)
    aliases = {"twelve_data": "Twelve Data", "yfinance": "Yahoo Finance", "sec_companyfacts": "SEC 公司财报", "as_of": "数据截至", "1wk": "周线", "1d": "日线",
               "regular_close": "常规时段收盘", "after_hours": "盘后", "pre_market": "盘前", "session": "交易时段",
               "Time precision": "时间精度", "time_precision": "时间精度", "source_id": "引用来源", "data_ref": "资料引用",
               "crossovers": "领先方交换", "strictly_increasing": "全程持续上涨"}
    for index in range(0, len(parts), 2):
        segments = re.split(r"(https?://[^\s<>）)]+)", parts[index])
        for offset in range(0, len(segments), 2):
            value = segments[offset]
            value = re.sub(r"\b(?:session|Session)\s*(?:为|[:：=])\s*regular_close\b", "常规时段收盘", value)
            value = re.sub(r"\b(?:Time precision|time_precision)\s*[:：=]\s*date\b", "时间仅精确到日期", value)
            for before, after in aliases.items():
                value = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(before) + r"(?![A-Za-z0-9_])", after, value)
            value = re.sub(r"[（(]\s*chart_[a-f0-9]{8,}\s*[）)]", "", value)
            value = re.sub(r"\bchart_[a-f0-9]{8,}\b", "本轮图表", value)
            # 数据引用只用于回读；正文保留有效来源编号，让用户能打开实际出处。
            value = re.sub(r"\[数据集\s+(?:dataset_)?[a-f0-9]{8,}\s*[，,；;]\s*来源\s*[:：]?\s*(S[a-f0-9]+)\s*\]",
                           lambda match: f"[{match.group(1)}]", value)
            value = re.sub(r"[（(]\s*dataset_[a-zA-Z0-9_-]+\s*[）)]", "", value)
            value = re.sub(r"数据集\s+(?:dataset_)?[a-f0-9]{8,}\b", "研究数据", value)
            value = re.sub(r"\bdataset_[a-zA-Z0-9_-]+\b", "研究数据", value)
            for agent_id, label in (agent_labels or {}).items():
                value = value.replace(agent_id, label)
            segments[offset] = value
        parts[index] = "".join(segments)
    return "".join(parts)


def message_blocks(values) -> list[dict]:
    remaining = MAX_PROVIDER_REASONING_CHARS
    result = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict) or value.get("kind") not in {"text", "artifact", "action", "reasoning"}:
            continue
        block = deepcopy(value)
        if block["kind"] == "reasoning":
            content = str(block.get("content") or "")
            if block.get("reasoning_kind") == "provider_raw":
                block["content"] = content[:remaining]
                block["truncated"] = bool(block.get("truncated") or len(content) > remaining)
                remaining -= len(block["content"])
            else:
                block["content"] = content[:8000]
        result.append(block)
    return result


def message_activities(values) -> list[dict]:
    result = []
    for step in values if isinstance(values, list) else []:
        if not isinstance(step, dict):
            continue
        detail = step.get("result") if isinstance(step.get("result"), dict) else {}
        kind = str(detail.get("runtime_type") or "")
        if not kind.startswith(("tool.", "agent.", "skill.", "activity.")):
            continue
        if str(detail.get("activity_id") or "").endswith("_model"):
            continue
        result.append({"stage": str(step.get("stage") or "trace"), "eventType": str(step.get("eventType") or "trace"),
                       "message": clean_text(str(step.get("message") or ""), 400),
                       "timestamp": str(step.get("timestamp") or ""), "runId": step.get("runId"),
                       "sessionId": step.get("sessionId"), "result": safe_preview(detail, max_chars=8000)})
    return result[-400:]


def price_levels_from_blocks(blocks: list[dict], tickers: list[str]) -> list[dict]:
    """只提取已经通过正文校验的明确价位措辞，不按K线或数字猜测支撑/阻力。"""
    pattern = re.compile(r"(支撑(?:位)?|阻力(?:位)?|止损(?:位)?|目标价)[^\d\n]{0,12}(?:[$¥￥]\s*)?(\d+(?:\.\d+)?)")
    result = []
    for block in blocks:
        if block.get("kind") != "text" or not block.get("id"):
            continue
        text = str(block.get("content") or "")
        if "[数据缺失]" in text or "已撤回" in text:
            continue
        explicit = [ticker for ticker in tickers if re.search(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])", text, re.I)]
        ticker = explicit[0] if len(explicit) == 1 else tickers[0] if len(tickers) == 1 else None
        if ticker is None:
            continue
        for match in pattern.finditer(text):
            price = float(match.group(2))
            if not math.isfinite(price) or price <= 0 or re.match(r"\s*(?:年|月|日|%|％|万|亿|千)", text[match.end():]):
                continue
            item = {"ticker": ticker, "price": price, "label": match.group(1), "source_block_id": block["id"]}
            if item not in result:
                result.append(item)
    return result[:12]
