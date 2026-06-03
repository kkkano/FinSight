# -*- coding: utf-8 -*-
"""P2-3 同质化章节数据化改造 — 报告生成 prompt 结构化要求断言测试。

这是 prompt 文本断言测试（不调 LLM），轻量但能防止结构化要求被误删。
通过读取 synthesize.py 源码做字符串断言，覆盖两条报告生成 prompt 链路：
  1. _generate_narrative_draft 的 <report_structure>（投资报告叙述正文）
  2. synthesize 节点的 <field_quality_guidelines>（catalysts/risks/conclusion 字段填充）
"""

from pathlib import Path

_SYNTHESIZE_SRC = (
    Path(__file__).resolve().parents[1] / "graph" / "nodes" / "synthesize.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. 催化剂章节：事件状态标记（已确认 / 预期 / 传言）
# ---------------------------------------------------------------------------
def test_catalyst_section_requires_event_status_markers():
    src = _SYNTHESIZE_SRC
    assert "【已确认】" in src
    assert "【预期】" in src
    assert "【传言】" in src
    # 明确要求标注事件状态，禁止无法标注状态的模糊催化剂
    assert "事件状态" in src
    assert "禁止列出无法标注状态的模糊催化剂" in src


# ---------------------------------------------------------------------------
# 2. 风险章节：可追踪触发条件（指标 + 阈值），禁止空话
# ---------------------------------------------------------------------------
def test_risk_section_requires_trackable_trigger_conditions():
    src = _SYNTHESIZE_SRC
    assert "触发条件" in src
    # 禁止无法验证的空话（点名"宏观环境波动"）
    assert "宏观环境波动" in src
    # 给出指标+阈值的范例格式
    assert "毛利率跌破 40%" in src


# ---------------------------------------------------------------------------
# 3. 结论与展望章节：强制"观察点清单"（指标 + 窗口 + 阈值 + 含义）
# ---------------------------------------------------------------------------
def test_conclusion_section_requires_watchpoint_checklist():
    src = _SYNTHESIZE_SRC
    assert "观察点清单" in src
    # 观察点四要素
    assert "观察窗口" in src and "触发阈值" in src
    # 表格表头四列
    assert "| 观察点 | 窗口 | 阈值 | 触发含义 |" in src
    # 禁止无行动指引的模糊表述
    assert "建议持续关注" in src


# ---------------------------------------------------------------------------
# 4. 结构化要求贯穿两条 prompt 链路（叙述正文 + JSON 字段填充）
# ---------------------------------------------------------------------------
def test_field_quality_guidelines_also_carry_structured_requirements():
    src = _SYNTHESIZE_SRC
    field_block_start = src.find("<field_quality_guidelines>")
    field_block_end = src.find("</field_quality_guidelines>")
    assert field_block_start != -1 and field_block_end != -1
    field_block = src[field_block_start:field_block_end]
    # catalysts 字段要求事件状态标记
    assert "事件状态" in field_block
    # risks 字段要求可追踪触发条件
    assert "触发条件" in field_block
    # conclusion 字段要求观察点清单
    assert "观察点" in field_block


# ---------------------------------------------------------------------------
# 5. 防回归：改动不破坏原有章节结构定义关键词
# ---------------------------------------------------------------------------
def test_existing_report_structure_keywords_preserved():
    src = _SYNTHESIZE_SRC
    # <report_structure> 五大章节标题仍在
    assert "<report_structure>" in src
    assert "## 投资论点" in src
    assert "## 基本面分析" in src
    assert "## 技术面分析" in src
    assert "## 催化剂与风险" in src
    assert "## 结论" in src
    # 原有催化剂三要素要求未被删除
    assert "影响路径（事件" in src
    # 原有约束块仍在
    assert "<constraints>" in src
