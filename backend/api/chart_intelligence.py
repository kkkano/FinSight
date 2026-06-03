# -*- coding: utf-8 -*-
"""
图表智能选型（LLM 决策版）

目标：把 Chat 对话里"该不该出图、出什么图"的决策从
"关键词匹配 + 默认折线图"升级为"LLM 理解 query 语义后智能决定"。

设计要点：
- LLM 在 8 秒内返回严格 JSON；超时 / 失败 / 解析失败 → 回退到
  chart_detector 关键词匹配（detector="keyword_fallback"），永不阻断主流程。
- 返回结构向后兼容现有 /api/chart/detect 响应，并扩展
  data_kind / reason / detector / title 字段。
- 诚实原则：图表类型必须与可取到的数据匹配。前端只在
  data_kind 为 kline/technical 时才真正注入 [CHART] 标记走 InlineChart，
  其余 data_kind（composition/comparison/financial）诚实跳过，
  绝不拿股价折线冒充"营收构成"等图。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# LLM 可选的图表类型清单（与前端 SmartChart / InlineChart 支持的类型对齐）。
# value 为该类型的适用场景说明，会注入到 prompt 里帮助 LLM 选型。
SUPPORTED_CHART_TYPES: dict[str, str] = {
    "line": "时间序列趋势：股价走势 / 指标历史变化",
    "candlestick": "K线图：价格行为 / 技术分析（开高低收）",
    "price_volume": "价量图：价格叠加成交量",
    "bar": "柱状对比：多标的对比 / 排名 / 排序",
    "pie": "构成占比：营收构成 / 持仓分布 / 板块占比",
    "radar": "多维度对比：风险维度 / 竞争力雷达",
    "gauge": "单值仪表盘：评分 / 健康度 / 恐慌贪婪指数",
    "scatter": "散点分布：估值 vs 增长等两维关系",
    "area": "面积图：累计收益 / 堆叠趋势",
    "heatmap": "热力图：相关性矩阵 / 强度密度",
}

# 取数方式：决定前端如何为该图准备数据。
# - kline / technical：InlineChart 可用 fetchKline 真出图。
# - composition / comparison / financial：当前 InlineChart 无对应数据源，前端诚实跳过。
# - none：不出图。
DATA_KINDS = {"kline", "financial", "comparison", "composition", "technical", "none"}

# chart_type -> 默认 data_kind 的兜底映射（当 LLM 漏给 data_kind 时使用）。
_CHART_TYPE_TO_DATA_KIND = {
    "line": "kline",
    "candlestick": "technical",
    "price_volume": "technical",
    "area": "kline",
    "bar": "comparison",
    "pie": "composition",
    "radar": "financial",
    "gauge": "financial",
    "scatter": "financial",
    "heatmap": "financial",
}

# keyword fallback 检测器输出的 chart_type -> data_kind 推断。
_FALLBACK_DIMENSION_TO_DATA_KIND = {
    "price": "kline",
    "volume": "technical",
    "comparison": "comparison",
    "distribution": "composition",
    "sentiment": "financial",
}

# LLM 决策超时（秒）。超时即回退关键词匹配。
_LLM_DECIDE_TIMEOUT_SEC = 8.0


def _build_prompt(query: str, ticker: str | None) -> str:
    """构造中文决策 prompt，要求 LLM 输出严格 JSON。"""
    type_lines = "\n".join(f"- {name}: {desc}" for name, desc in SUPPORTED_CHART_TYPES.items())
    ticker_text = ticker or "未提供"
    return f"""<角色>你是金融图表选型助手。</角色>

<任务>
分析用户的查询，判断「该不该出图」以及「出什么图最合适」。
只输出一个严格 JSON 对象，禁止任何解释、禁止 markdown 代码块、禁止多余文字。
</任务>

<可选图表类型>
{type_lines}
</可选图表类型>

<取数方式 data_kind>
- kline: 走势 / 股价类，取 K 线数据（line / area）
- technical: 技术指标类，取 K 线及技术数据（candlestick / price_volume）
- composition: 构成 / 占比类（pie），需要财务构成数据
- comparison: 多标的对比 / 排名（bar）
- financial: 财务 / 估值 / 多维评估（radar / gauge / scatter）
- none: 不需要出图
</取数方式>

<决策规则>
1. 寒暄、泛泛、无明确数据诉求的问题（如"最近怎么样""你好""帮我看看"）→ should_generate=false, chart_type=null, data_kind=none。
2. 只有明确的数据型问题才出图。
3. 构成 / 占比 / 营收结构 → pie（data_kind=composition）。
4. 多标的对比 / 排名 / 谁更强 → bar（data_kind=comparison）。
5. 技术指标（RSI / MACD / K线 / 支撑阻力） → candlestick 或 price_volume（data_kind=technical）。
6. 风险评估 / 多维度打分 → radar（data_kind=financial）。
7. 单一评分 / 健康度 / 指数 → gauge（data_kind=financial）。
8. 价格走势 / 涨跌 / 趋势 → line（data_kind=kline）。
9. chart_type 必须从上面"可选图表类型"里选，不要发明新类型。
10. title 用中文，简洁描述图表内容（如"AAPL 营收构成"）。
</决策规则>

<输入>
用户查询: {query}
股票代码: {ticker_text}
</输入>

<输出格式>
严格输出如下 JSON（confidence 为 0~1 小数）：
{{"should_generate": true 或 false, "chart_type": "类型名 或 null", "data_kind": "取数方式", "confidence": 0.0, "title": "中文标题", "reason": "一句话中文理由"}}
</输出格式>

现在只输出 JSON："""


def _extract_json(text: str) -> dict[str, Any] | None:
    """从 LLM 文本里抽取第一个 JSON 对象。容忍 ```json 代码块包裹。"""
    if not text:
        return None
    cleaned = text.strip()
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


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "是")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _coerce_confidence(value: Any, default: float = 0.5) -> float:
    try:
        conf = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, conf))


def _normalize_llm_result(parsed: dict[str, Any], query: str, ticker: str | None) -> dict[str, Any] | None:
    """把 LLM JSON 规整为标准返回结构；非法 chart_type 返回 None 触发回退。"""
    should_generate = _coerce_bool(parsed.get("should_generate"), default=False)

    raw_type = parsed.get("chart_type")
    chart_type = str(raw_type).strip().lower() if raw_type not in (None, "", "null") else None

    # 不出图：直接返回干净结构（不强求 chart_type）
    if not should_generate or chart_type is None:
        return {
            "should_generate": False,
            "chart_type": None,
            "confidence": _coerce_confidence(parsed.get("confidence"), default=0.6),
            "title": str(parsed.get("title") or "").strip(),
            "data_kind": "none",
            "reason": str(parsed.get("reason") or "无明确出图诉求").strip(),
            "detector": "llm",
        }

    # 要出图：chart_type 必须在支持清单内，否则交给关键词回退
    if chart_type not in SUPPORTED_CHART_TYPES:
        logger.info("[ChartIntelligence] LLM 返回不支持的 chart_type=%r，回退关键词匹配", chart_type)
        return None

    raw_kind = parsed.get("data_kind")
    data_kind = str(raw_kind).strip().lower() if raw_kind else ""
    if data_kind not in DATA_KINDS:
        data_kind = _CHART_TYPE_TO_DATA_KIND.get(chart_type, "kline")

    title = str(parsed.get("title") or "").strip()
    if not title:
        title = f"{ticker} {SUPPORTED_CHART_TYPES[chart_type].split('：')[0]}".strip() if ticker else SUPPORTED_CHART_TYPES[chart_type].split("：")[0]

    return {
        "should_generate": True,
        "chart_type": chart_type,
        "confidence": _coerce_confidence(parsed.get("confidence"), default=0.7),
        "title": title,
        "data_kind": data_kind,
        "reason": str(parsed.get("reason") or "LLM 语义决策").strip(),
        "detector": "llm",
    }


def _keyword_fallback(query: str, ticker: str | None) -> dict[str, Any]:
    """回退到现有关键词检测器，并补齐扩展字段。"""
    try:
        from backend.api.chart_detector import ChartTypeDetector

        detected = ChartTypeDetector.detect_chart_type(query, ticker)
    except Exception as exc:  # 极端情况：连关键词检测器都不可用
        logger.warning("[ChartIntelligence] keyword fallback 失败: %s", exc)
        return {
            "should_generate": False,
            "chart_type": None,
            "confidence": 0.0,
            "title": "",
            "data_kind": "none",
            "reason": f"fallback_unavailable: {exc}",
            "detector": "keyword_fallback",
        }

    chart_type = detected.get("chart_type") if isinstance(detected, dict) else None
    confidence = _coerce_confidence(detected.get("confidence") if isinstance(detected, dict) else 0.0, default=0.0)
    dimension = detected.get("data_dimension") if isinstance(detected, dict) else None
    reason = str(detected.get("reason") or "") if isinstance(detected, dict) else ""

    # 关键词检测器只产出 8 类，其中 tree 前端 InlineChart 无法渲染，统一收敛。
    if chart_type == "tree":
        chart_type = "bar"

    should_generate = bool(chart_type) and confidence >= 0.35
    if not should_generate or not chart_type:
        return {
            "should_generate": False,
            "chart_type": None,
            "confidence": confidence,
            "title": "",
            "data_kind": "none",
            "reason": reason or "未检测到图表需求",
            "detector": "keyword_fallback",
        }

    data_kind = _FALLBACK_DIMENSION_TO_DATA_KIND.get(
        dimension or "", _CHART_TYPE_TO_DATA_KIND.get(chart_type, "kline")
    )
    title = f"{ticker} 走势" if ticker else "图表"
    return {
        "should_generate": True,
        "chart_type": chart_type,
        "confidence": confidence,
        "title": title,
        "data_kind": data_kind,
        "reason": reason or "关键词匹配",
        "detector": "keyword_fallback",
    }


async def _llm_decide(query: str, ticker: str | None) -> dict[str, Any] | None:
    """调用 LLM 做决策；任何异常 / 超时 / 非法输出返回 None。"""
    try:
        from langchain_core.messages import HumanMessage

        from backend.llm_config import create_llm
        from backend.services.llm_retry import ainvoke_with_rate_limit_retry
    except Exception as exc:
        logger.warning("[ChartIntelligence] LLM 依赖导入失败: %s", exc)
        return None

    try:
        # 低温 + 限制 token，要求简洁 JSON。
        llm = create_llm(temperature=0.1, max_tokens=256, request_timeout=int(_LLM_DECIDE_TIMEOUT_SEC) + 2)
    except Exception as exc:
        logger.warning("[ChartIntelligence] create_llm 失败: %s", exc)
        return None

    prompt = _build_prompt(query, ticker)

    try:
        response = await asyncio.wait_for(
            ainvoke_with_rate_limit_retry(
                llm,
                [HumanMessage(content=prompt)],
                llm_factory=None,
                max_attempts=1,  # 决策走快路径，失败立即回退关键词匹配
                acquire_token=False,
                agent_name="chart_intelligence",
            ),
            timeout=_LLM_DECIDE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.info("[ChartIntelligence] LLM 决策超时 %.1fs，回退关键词匹配", _LLM_DECIDE_TIMEOUT_SEC)
        return None
    except Exception as exc:
        logger.info("[ChartIntelligence] LLM 决策失败: %s，回退关键词匹配", exc)
        return None

    response_text = response.content if hasattr(response, "content") else str(response)
    parsed = _extract_json(response_text)
    if not isinstance(parsed, dict):
        logger.info("[ChartIntelligence] LLM 输出非法 JSON，回退关键词匹配")
        return None

    return _normalize_llm_result(parsed, query, ticker)


async def decide_chart(query: str, ticker: str | None = None) -> dict[str, Any]:
    """LLM 理解 query 语义，决定该不该出图、出什么图。

    返回（与现有 /api/chart/detect 响应兼容 + 扩展字段）：
    {
        "should_generate": bool,
        "chart_type": str | None,
        "confidence": float,
        "title": str,
        "data_kind": str,        # kline|financial|comparison|composition|technical|none
        "reason": str,
        "detector": "llm" | "keyword_fallback",
    }
    """
    query = str(query or "").strip()
    if not query:
        return {
            "should_generate": False,
            "chart_type": None,
            "confidence": 0.0,
            "title": "",
            "data_kind": "none",
            "reason": "empty_query",
            "detector": "keyword_fallback",
        }

    llm_result = await _llm_decide(query, ticker)
    if llm_result is not None:
        return llm_result

    # LLM 不可用 / 超时 / 非法 → 关键词回退
    return _keyword_fallback(query, ticker)


__all__ = [
    "decide_chart",
    "SUPPORTED_CHART_TYPES",
    "DATA_KINDS",
]
