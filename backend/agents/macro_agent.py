from typing import Dict, Any, List, Optional
from datetime import datetime
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

class MacroAgent(BaseFinancialAgent):
    """
    MacroAgent - 宏观经济专家
    负责：
    1. 监测宏观指标 (CPI, GDP, Interest Rates)
    2. 分析美联储政策 (Fed Policy)
    3. 识别市场周期 (Cycle Identification)
    """
    AGENT_NAME = "macro"

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        """
        宏观搜索策略：
        忽略 ticker (个股)，关注 query 中的宏观关键词
        """
        # 关键词提取 (Mock)
        macro_keywords = ["inflation", "rate", "fed", "recession", "gdp"]
        relevant = any(k in query.lower() for k in macro_keywords)

        if not relevant and not "macro" in query.lower():
            # 如果查询不涉及宏观，返回空或通用背景
            return {"status": "skipped", "reason": "No macro intent detected"}

        # 模拟获取 FRED 数据
        return {
            "cpi": "3.2%",
            "fed_rate": "5.25-5.50%",
            "gdp_growth": "2.1%",
            "status": "success"
        }

    async def _first_summary(self, data: Dict[str, Any]) -> str:
        if data.get("status") == "skipped":
            return "当前市场宏观环境相对稳定。"

        return (
            f"宏观数据更新：CPI 为 {data.get('cpi')}，美联储利率维持在 {data.get('fed_rate')}。"
            "当前处于高利率环境末期，通胀温和回落，软着陆概率增加。"
        )

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence = []
        if isinstance(raw_data, dict) and raw_data.get("status") == "success":
            evidence.append(EvidenceItem(
                text=f"CPI: {raw_data.get('cpi')}",
                source="FRED",
                confidence=1.0
            ))

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=0.9, # 官方数据置信度高
            data_sources=["FRED", "Government Reports"],
            as_of=datetime.now().isoformat(),
            risks=["政策滞后效应"]
        )
