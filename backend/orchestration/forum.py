from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from backend.agents.base_agent import AgentOutput

@dataclass
class ForumOutput:
    consensus: str
    disagreement: str
    confidence: float
    recommendation: str  # BUY/HOLD/SELL
    risks: List[str]

class ForumHost:
    SYNTHESIS_PROMPT = """你是 FinSight AI 首席金融分析师，负责整合多位专业 Agent 的分析结果，生成机构级投资研究报告。

【用户画像】
风险偏好: {risk_tolerance}
投资风格: {investment_style}
{user_instruction}

【对话上下文】
{context_info}

【各Agent分析结果】
## 价格分析 (PriceAgent)
{price}

## 新闻分析 (NewsAgent)
{news}

## 技术分析 (TechnicalAgent)
{technical}

## 基本面分析 (FundamentalAgent)
{fundamental}

## 深度搜索 (DeepSearchAgent)
{deep_search}

## 宏观分析 (MacroAgent)
{macro}

---

## 报告输出要求

请根据以上多源数据，生成一份**专业深度研究报告**，必须包含以下全部章节：

### 1. 📊 执行摘要 (EXECUTIVE SUMMARY)
- **投资评级**: BUY / HOLD / SELL（根据用户风险偏好调整表述）
- **目标价位**: 基于技术面和基本面综合判断（如数据不足则注明）
- **风险等级**: 低/中/高
- **核心观点**: 2-3句话概括投资逻辑

### 2. 📈 当前市场表现 (MARKET POSITION)
- 最新价格与涨跌幅
- 52周高低点对比
- 成交量分析
- 关键支撑/阻力位

### 3. 💰 基本面分析 (FUNDAMENTAL ANALYSIS)
- 关键估值指标（P/E、P/S、EV/EBITDA 等，如有）
- 营收/利润趋势
- 竞争格局与护城河
- 增长驱动因素

### 4. 🌍 宏观环境与催化剂 (MACRO & CATALYSTS)
- 行业发展趋势
- 近期重要事件（财报、产品发布、政策等）
- 监管环境变化
- 宏观经济影响

### 5. ⚠️ 风险评估 (RISK ASSESSMENT)
- 公司特定风险
- 市场系统性风险
- 行业风险
- 风险缓释建议

### 6. 🎯 投资策略 (INVESTMENT STRATEGY)
- 建议入场点位
- 仓位管理建议（根据用户风险偏好）
- 止损位设置
- 投资时间周期

### 7. 📐 情景分析 (SCENARIO ANALYSIS)
- **乐观情景**: 上行目标及触发条件
- **悲观情景**: 下行风险及触发条件
- **基准情景**: 最可能的走势

### 8. 📅 关注事件 (MONITORING EVENTS)
- 需关注的关键日期
- 需跟踪的核心指标
- 建议设置的预警条件

---

## 质量标准
- 报告需**至少800字**，内容充实详尽
- 必须包含**具体数据**和**来源引用**
- 所有建议必须有**理由支撑**
- 明确区分**事实**与**观点**
- 保持**专业客观**的分析立场

## 重要提醒
- 如某 Agent 数据缺失，在对应章节注明"数据暂不可用"
- 根据用户风险偏好调整建议语气（保守用户强调风险，激进用户可提及机会）
- 如对话上下文有相关话题，将其自然融入分析
- 请用**中文**输出，保持专业但易于理解

---
请开始生成完整的深度研究报告："""

    def __init__(self, llm):
        self.llm = llm

    async def synthesize(self, outputs: Dict[str, AgentOutput], user_profile: Optional[Any] = None, context_summary: str = None) -> ForumOutput:
        # 1. 提取各 Agent 的摘要
        context_parts = {}
        for name, output in outputs.items():
            key = name.lower().replace("agent", "")
            if output and hasattr(output, 'summary'):
                summary_info = f"摘要: {output.summary}\n置信度: {output.confidence:.0%}"
                if output.evidence:
                    summary_info += f"\n证据数量: {len(output.evidence)}"
            else:
                summary_info = "无数据"
            context_parts[key] = summary_info

        # 补全缺失的 Agent 数据
        for key in ["price", "news", "technical", "fundamental", "deep_search", "macro"]:
            if key not in context_parts:
                context_parts[key] = "无数据"

        # 2. 准备用户画像上下文
        risk_tolerance = "中等 (Medium)"
        investment_style = "平衡型 (Balanced)"
        user_instruction = ""

        if user_profile:
            risk_tolerance = getattr(user_profile, "risk_tolerance", "medium")
            investment_style = getattr(user_profile, "investment_style", "balanced")

            if risk_tolerance in ("low", "conservative"):
                user_instruction = "用户风险厌恶。请重点强调下行风险，建议偏保守。"
            elif risk_tolerance in ("high", "aggressive"):
                user_instruction = "用户风险偏好高。可重点关注高增长机会，但也需提示波动风险。"

        # 3. 构建 Prompt 并调用 LLM
        context_info = context_summary if context_summary else "无"

        prompt = self.SYNTHESIS_PROMPT.format(
            risk_tolerance=risk_tolerance,
            investment_style=investment_style,
            user_instruction=user_instruction,
            context_info=context_info,
            **context_parts
        )

        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            consensus = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            # 如果 LLM 调用失败，使用简单的规则合成
            print(f"[Forum] LLM synthesis failed: {e}, using fallback")
            consensus = self._fallback_synthesis(context_parts)

        # 4. 计算加权置信度
        total_conf = 0.0
        count = 0
        for out in outputs.values():
            if out and hasattr(out, 'confidence'):
                total_conf += out.confidence
                count += 1
        avg_conf = total_conf / count if count > 0 else 0.5

        return ForumOutput(
            consensus=consensus,
            disagreement="",
            confidence=avg_conf,
            recommendation="HOLD",
            risks=["市场波动风险", "数据延迟风险"]
        )

    def _fallback_synthesis(self, context_parts: Dict[str, str]) -> str:
        """LLM 调用失败时的结构化规则合成"""
        sections = []

        # 1. 执行摘要
        sections.append("### 1. 📊 执行摘要 (EXECUTIVE SUMMARY)")
        sections.append("- **投资评级**: HOLD (观望)")
        sections.append("- **风险等级**: 中等")
        sections.append("- **核心观点**: 基于当前数据，建议保持观望态度，等待更多信号确认。")
        sections.append("")

        # 2. 当前市场表现
        sections.append("### 2. 📈 当前市场表现 (MARKET POSITION)")
        if context_parts.get("price") != "无数据":
            sections.append(context_parts["price"][:300])
        else:
            sections.append("- 价格数据暂不可用")
        sections.append("")

        # 3. 基本面分析
        sections.append("### 3. 💰 基本面分析 (FUNDAMENTAL ANALYSIS)")
        if context_parts.get("fundamental") != "无数据":
            sections.append(context_parts["fundamental"][:300])
        else:
            sections.append("- 基本面数据暂不可用")
        sections.append("")

        # 4. 宏观环境与催化剂
        sections.append("### 4. 🌍 宏观环境与催化剂 (MACRO & CATALYSTS)")
        if context_parts.get("macro") != "无数据":
            sections.append(context_parts["macro"][:300])
        else:
            sections.append("- 宏观数据暂不可用")
        sections.append("")

        # 5. 风险评估
        sections.append("### 5. ⚠️ 风险评估 (RISK ASSESSMENT)")
        sections.append("- 市场波动风险")
        sections.append("- 数据延迟风险")
        sections.append("- 行业政策风险")
        sections.append("")

        # 6. 投资策略
        sections.append("### 6. 🎯 投资策略 (INVESTMENT STRATEGY)")
        sections.append("- 建议保持观望，等待市场明确方向")
        sections.append("- 如已持仓，建议设置止损保护")
        sections.append("")

        # 7. 情景分析
        sections.append("### 7. 📐 情景分析 (SCENARIO ANALYSIS)")
        sections.append("- **乐观情景**: 待数据完善后评估")
        sections.append("- **悲观情景**: 待数据完善后评估")
        sections.append("- **基准情景**: 短期震荡为主")
        sections.append("")

        # 8. 关注事件
        sections.append("### 8. 📅 关注事件 (MONITORING EVENTS)")
        if context_parts.get("news") != "无数据":
            sections.append(f"近期新闻动态:\n{context_parts['news'][:200]}")
        else:
            sections.append("- 建议关注近期财报及行业政策")

        # 添加新闻和技术分析作为补充
        if context_parts.get("technical") != "无数据":
            sections.append("")
            sections.append("### 补充: 技术分析")
            sections.append(context_parts["technical"][:300])

        return "\n".join(sections)

    def _detect_conflicts(self, outputs: Dict[str, AgentOutput]) -> List[str]:
        # 简单的冲突检测逻辑
        conflicts = []
        return conflicts
