from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging
import os
from backend.agents.base_agent import AgentOutput
from backend.prompts.system_prompts import FORUM_SYNTHESIS_PROMPT

@dataclass
class ForumOutput:
    consensus: str
    disagreement: str
    confidence: float
    recommendation: str  # BUY/HOLD/SELL
    risks: List[str]

class ForumHost:
    BULLISH_KEYWORDS = (
        "bullish", "buy", "看涨", "利好", "上涨", "增持", "买入", "强势", "上行",
    )
    BEARISH_KEYWORDS = (
        "bearish", "sell", "看跌", "利空", "下跌", "减持", "卖出", "弱势", "下行",
    )

    def __init__(self, llm):
        self.llm = llm
        self.logger = logging.getLogger(__name__)

    def _infer_sentiment(self, text: str) -> str:
        text_lower = (text or "").lower()
        bullish_hit = any(kw in text_lower for kw in self.BULLISH_KEYWORDS)
        bearish_hit = any(kw in text_lower for kw in self.BEARISH_KEYWORDS)
        if bullish_hit and bearish_hit:
            return "mixed"
        if bullish_hit:
            return "bullish"
        if bearish_hit:
            return "bearish"
        return "neutral"

    def _detect_conflicts(self, outputs: Dict[str, AgentOutput]) -> List[str]:
        conflicts: List[str] = []
        sentiments: Dict[str, str] = {}
        for name, output in outputs.items():
            summary = getattr(output, "summary", "") if output else ""
            if not summary:
                continue
            sentiments[name] = self._infer_sentiment(summary)

        bullish_agents = [name for name, s in sentiments.items() if s == "bullish"]
        bearish_agents = [name for name, s in sentiments.items() if s == "bearish"]
        mixed_agents = [name for name, s in sentiments.items() if s == "mixed"]

        if bullish_agents and bearish_agents:
            conflicts.append(
                f"情绪冲突：{', '.join(bullish_agents)}偏多 vs {', '.join(bearish_agents)}偏空"
            )
        if mixed_agents:
            conflicts.append(f"混合情绪：{', '.join(mixed_agents)}存在正反结论并存")
        return conflicts

    async def synthesize(
        self,
        outputs: Dict[str, AgentOutput],
        user_profile: Optional[Any] = None,
        context_summary: str = None,
    ) -> ForumOutput:
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

        # 3. 冲突检测与 Prompt 构建
        conflicts = self._detect_conflicts(outputs)
        conflict_notes = "；".join(conflicts) if conflicts else "无明显冲突"
        conflict_penalty = 0.1 * len(conflicts)

        context_info = context_summary if context_summary else "无"

        prompt = FORUM_SYNTHESIS_PROMPT.format(
            risk_tolerance=risk_tolerance,
            investment_style=investment_style,
            user_instruction=user_instruction,
            context_info=context_info,
            conflict_notes=conflict_notes,
            **context_parts
        )

        try:
            from langchain_core.messages import HumanMessage
            from backend.services.llm_retry import ainvoke_with_rate_limit_retry
            
            # 在 LLM 调用前获取速率限制令牌
            from backend.services.rate_limiter import acquire_llm_token
            token_acquired = await acquire_llm_token(timeout=120.0, agent_name="forum_synthesis")
            if not token_acquired:
                self.logger.warning("[Forum] Rate limit timeout, using fallback synthesis")
                consensus = self._fallback_synthesis(context_parts)
            else:
                llm_factory = None
                try:
                    from backend.llm_config import create_llm

                    llm_provider = os.getenv("LLM_PROVIDER", "openai_compatible")
                    llm_temperature = float(os.getenv("FORUM_LLM_TEMPERATURE", "0.3"))
                    llm_timeout = int(os.getenv("FORUM_LLM_REQUEST_TIMEOUT", "600"))
                    llm_factory = lambda: create_llm(  # noqa: E731
                        provider=llm_provider,
                        temperature=llm_temperature,
                        request_timeout=llm_timeout,
                    )
                except Exception:
                    llm_factory = None

                max_attempts = max(1, int(os.getenv("FORUM_LLM_MAX_ATTEMPTS", "4")))
                response = await ainvoke_with_rate_limit_retry(
                    self.llm,
                    [HumanMessage(content=prompt)],
                    llm_factory=llm_factory,
                    max_attempts=max_attempts,
                    acquire_token=False,
                )
                consensus_raw = response.content if hasattr(response, 'content') else str(response)
                consensus = str(consensus_raw or "").strip() or self._fallback_synthesis(context_parts)
        except Exception as e:
            # 如果 LLM 调用失败，使用简单的规则合成
            import traceback
            self.logger.error("[Forum] LLM synthesis failed!")
            self.logger.error("[Forum] Exception type: %s", type(e).__name__)
            self.logger.error("[Forum] Exception message: %s", str(e))
            self.logger.error("[Forum] Prompt length: %d chars, LLM type: %s", len(prompt), type(self.llm).__name__)
            self.logger.error("[Forum] Prompt preview (first 500 chars): %s", prompt[:500])
            self.logger.error("[Forum] Full traceback:\n%s", traceback.format_exc())
            consensus = self._fallback_synthesis(context_parts)

        # 4. 计算加权置信度
        total_conf = 0.0
        count = 0
        for out in outputs.values():
            if out and hasattr(out, 'confidence'):
                total_conf += out.confidence
                count += 1
        avg_conf = total_conf / count if count > 0 else 0.5
        avg_conf = max(0.1, avg_conf - conflict_penalty)

        return ForumOutput(
            consensus=consensus,
            disagreement=conflict_notes if conflict_penalty > 0 else "",
            confidence=avg_conf,
            recommendation="HOLD",
            risks=["市场波动风险", "数据延迟风险"]
            + (["结论存在冲突，请谨慎判断"] if conflict_penalty > 0 else [])
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
