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
    SYNTHESIS_PROMPT = """
    你是金融研究主持人。根据各 Agent 分析结果生成综合报告：

    【用户画像】
    风险偏好: {risk_tolerance}
    投资风格: {investment_style}
    {user_instruction}

    ## 价格 Agent: {price}
    ## 新闻 Agent: {news}
    ## 深度搜索 Agent: {deep_search}
    ## 宏观 Agent: {macro}
    ## 技术 Agent: {technical}
    ## 基本面 Agent: {fundamental}

    输出：
    1. 【共识观点】各 Agent 一致认同的结论
    2. 【分歧观点】存在冲突的判断及原因
    3. 【置信度】根据数据质量给出 0-1 分数
    4. 【投资建议】BUY/HOLD/SELL 及理由（请根据用户画像调整建议口吻）
    5. 【风险提示】关键风险因素
    """

    def __init__(self, llm):
        self.llm = llm

    async def synthesize(self, outputs: Dict[str, AgentOutput], user_profile: Optional[Any] = None) -> ForumOutput:
        # 1. 提取各 Agent 的摘要
        context_parts = {}
        for name, output in outputs.items():
            # 简单处理：使用 Agent 名称的小写作为键，如果需要更复杂的映射可以在此添加
            key = name.lower().replace("agent", "")
            summary_info = f'''Summary: {output.summary}
Evidence Count: {len(output.evidence)}
Confidence: {output.confidence}'''
            context_parts[key] = summary_info

        # 补全缺失的 Agent 数据，避免 Prompt 报错
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

            # 根据画像生成指令
            if risk_tolerance == "low" or risk_tolerance == "conservative":
                user_instruction = "用户风险厌恶。请重点强调下行风险，建议偏保守。"
            elif risk_tolerance == "high" or risk_tolerance == "aggressive":
                user_instruction = "用户风险偏好高。可重点关注高增长机会，但也需提示波动风险。"

        # 3. 构建 Prompt (这里仅做 Prompt 准备，实际调用逻辑待接入真实 LLM)
        # prompt = self.SYNTHESIS_PROMPT.format(
        #     risk_tolerance=risk_tolerance,
        #     investment_style=investment_style,
        #     user_instruction=user_instruction,
        #     **context_parts
        # )

        # 4. 模拟 LLM 综合逻辑 (MVP)
        # 在实际实现中，这里会调用 self.llm.ainvoke(prompt)

        # 简单的基于规则的合成 (Placeholder)
        price_summary = context_parts.get("price", "")
        news_summary = context_parts.get("news", "")

        consensus = "综合各方数据，市场目前处于波动状态。"
        if "无数据" not in price_summary:
            consensus += f" 价格数据表明: {price_summary[:50]}..."

        disagreement = "暂无明显分歧。"

        # 简单的加权置信度
        total_conf = 0.0
        count = 0
        for out in outputs.values():
            total_conf += out.confidence
            count += 1
        avg_conf = total_conf / count if count > 0 else 0.5

        return ForumOutput(
            consensus=consensus,
            disagreement=disagreement,
            confidence=avg_conf,
            recommendation="HOLD", # 默认观望
            risks=["市场波动风险", "数据延迟风险"]
        )

    def _detect_conflicts(self, outputs: Dict[str, AgentOutput]) -> List[str]:
        # 简单的冲突检测逻辑
        conflicts = []
        # 例如：价格显示大跌，但新闻全是利好 -> 冲突
        return conflicts
