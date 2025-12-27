from typing import Dict, Any, List, Optional
from datetime import datetime
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

class DeepSearchAgent(BaseFinancialAgent):
    """
    DeepSearchAgent - 深度研报专家
    负责：
    1. 长文检索 (比 NewsAgent 更深，抓取完整文章/PDF)
    2. 长窗口阅读 (Long Context Reading)
    3. 生成深度观点 (Investment Thesis)
    """
    AGENT_NAME = "deep_search"
    MAX_REFLECTIONS = 3  # 深度搜索需要更多反思轮次

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    async def _initial_search(self, query: str, ticker: str) -> List[Dict[str, Any]]:
        """
        第一阶段：广撒网 (Broad Search)
        寻找高质量的研报、深度文章链接
        """
        # 使用 tavily (research_tool) 进行深度搜索
        # 构建更具体的搜索词
        deep_query = f"{ticker} investment thesis 2025 deep analysis long term outlook"

        try:
            # 假设 tools_module 有 web_search 工具
            # 这里需要适配实际的工具调用方式，暂时模拟
            # raw_results = await self.tools.search(deep_query)
            # 暂时返回模拟数据
            return [
                {"url": "https://example.com/report1", "title": f"{ticker} Deep Dive", "snippet": "Detailed analysis..."},
                {"url": "https://example.com/report2", "title": f"Why {ticker} is a buy", "snippet": "Financial breakdown..."}
            ]
        except Exception as e:
            print(f"[DeepSearch] Search failed: {e}")
            return []

    async def _first_summary(self, data: List[Dict[str, Any]]) -> str:
        """
        第二阶段：初步阅读与摘要
        """
        if not data:
            return "未能找到深度资料。"

        # 这里应该调用 LLM 对搜索结果进行初步归纳
        # 暂时返回简单拼接
        titles = [item.get("title") for item in data]
        return f"找到相关深度文章：{', '.join(titles)}。初步判断该公司具有长期增长潜力，但在高估值下存在回调风险。"

    async def _identify_gaps(self, summary: str) -> List[str]:
        """
        反思：信息缺口识别
        """
        # 模拟：如果没有提到"竞争对手"，则认为有缺口
        if "competitor" not in summary.lower() and "risk" not in summary.lower():
            return ["competitor analysis", "downside risks"]
        return []

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Any:
        """
        针对性补全搜索
        """
        new_evidence = []
        for gap in gaps:
            query = f"{ticker} {gap}"
            # 模拟搜索
            new_evidence.append({"title": f"{gap} report", "snippet": f"Found info about {gap}"})
        return new_evidence

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        """
        更新摘要
        """
        # 简单追加
        additional_info = "; ".join([item.get("snippet") for item in new_data])
        return f"{summary} 补充信息：{additional_info}"

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        # 构建 EvidenceItem 列表
        evidence = []
        # 处理 raw_data (列表)
        if isinstance(raw_data, list):
            for item in raw_data:
                evidence.append(EvidenceItem(
                    text=item.get("snippet", ""),
                    source=item.get("title", "Web"),
                    url=item.get("url"),
                    confidence=0.8
                ))

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=0.85, # 深度搜索通常置信度较高
            data_sources=["Tavily", "Deep Web"],
            as_of=datetime.now().isoformat(),
            risks=["数据可能包含主观观点"]
        )
