import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)



class MacroAgent(BaseFinancialAgent):
    """
    
    MacroAgent - 宏观经济专家
    负责：
    1. 监测宏观指标 (CPI, GDP, Interest Rates) - 使用 FRED API
    2. 分析美联储政策 (Fed Policy)
    3. 识别市场周期 (Cycle Identification)
    
    """
    
    AGENT_NAME = "macro"

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module
        self._last_convergence = None

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        """
        宏观搜索策略：使用 FRED API 获取真实宏观经济数据
        """
        # 使用 FRED API 获取真实数据
        try:
            if hasattr(self.tools, 'get_fred_data'):
                fred_data = self.tools.get_fred_data()
                fred_data["status"] = "success"
                self._last_convergence = None
                return fred_data
        except Exception as e:
            logger.info(f"[MacroAgent] FRED API failed: {e}")

        # 回退到搜索（结构化兜底）
        try:
            if hasattr(self.tools, 'search'):
                search_result = self.tools.search("current US CPI inflation rate federal funds rate unemployment")
                try:
                    from dataclasses import asdict
                    from backend.agents.search_convergence import SearchConvergence
                    sc = SearchConvergence()
                    docs = [{
                        "url": "",
                        "content": str(search_result)[:2000],
                        "source": "search",
                    }]
                    _, metrics = sc.process_round(docs, previous_summary="")
                    self._last_convergence = asdict(metrics)
                except Exception:
                    self._last_convergence = None
                return {
                    "status": "fallback",
                    "source": "search",
                    "raw": search_result,
                    "indicators": [
                        {"name": "CPI", "value": None, "unit": "%", "as_of": None, "source": "search"},
                        {"name": "Fed Funds Rate", "value": None, "unit": "%", "as_of": None, "source": "search"},
                        {"name": "Unemployment", "value": None, "unit": "%", "as_of": None, "source": "search"},
                        {"name": "GDP Growth", "value": None, "unit": "%", "as_of": None, "source": "search"},
                        {"name": "10Y Treasury", "value": None, "unit": "%", "as_of": None, "source": "search"},
                        {"name": "10Y-2Y Spread", "value": None, "unit": "%", "as_of": None, "source": "search"},
                    ],
                }
        except Exception as e:
            logger.info(f"[MacroAgent] Search fallback failed: {e}")

        return {"status": "error", "reason": "Failed to fetch macro data"}

    async def _first_summary(self, data: Dict[str, Any]) -> str:
        if data.get("status") == "skipped":
            return "当前市场宏观环境相对稳定。"

        if data.get("status") == "error":
            return "无法获取宏观经济数据，请稍后重试。"

        if data.get("status") == "fallback":
            indicators = data.get("indicators", []) if isinstance(data, dict) else []
            names = [item.get("name") for item in indicators if isinstance(item, dict) and item.get("name")]
            summary = "宏观数据源不可用，使用搜索回退。"
            if names:
                summary += f"关注指标: {'、'.join(names)}。"
            return summary

        # 构建详细摘要
        parts = ["📊 **美国宏观经济数据更新**\n"]

        if data.get("fed_rate_formatted"):
            parts.append(f"• **联邦基金利率**: {data['fed_rate_formatted']}")
        if data.get("cpi_formatted"):
            parts.append(f"• **CPI 指数**: {data['cpi_formatted']}")
        if data.get("unemployment_formatted"):
            parts.append(f"• **失业率**: {data['unemployment_formatted']}")
        if data.get("gdp_growth_formatted"):
            parts.append(f"• **GDP 增长率**: {data['gdp_growth_formatted']}")
        if data.get("treasury_10y_formatted"):
            parts.append(f"• **10年期国债收益率**: {data['treasury_10y_formatted']}")
        if data.get("yield_spread_formatted"):
            spread = data['yield_spread_formatted']
            warning = " ⚠️ 收益率曲线倒挂" if data.get("recession_warning") else ""
            parts.append(f"• **10Y-2Y 利差**: {spread}{warning}")

        # 添加分析
        parts.append("\n**分析**:")
        if data.get("fed_rate") and data["fed_rate"] > 4:
            parts.append("当前处于高利率环境，美联储维持紧缩政策。")
        if data.get("recession_warning"):
            parts.append("收益率曲线倒挂通常是经济衰退的先行指标，需密切关注。")
        else:
            parts.append("收益率曲线正常，短期内衰退风险较低。")

        return "\n".join(parts)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence = []
        data_sources = ["FRED"]
        risks = []

        if isinstance(raw_data, dict):
            if raw_data.get("status") == "success":
                # 添加各项指标作为证据
                if raw_data.get("fed_rate"):
                    evidence.append(EvidenceItem(
                        text=f"Federal Funds Rate: {raw_data.get('fed_rate_formatted', raw_data['fed_rate'])}",
                        source="FRED - FEDFUNDS",
                        confidence=1.0
                    ))
                if raw_data.get("cpi"):
                    evidence.append(EvidenceItem(
                        text=f"CPI Index: {raw_data.get('cpi_formatted', raw_data['cpi'])}",
                        source="FRED - CPIAUCSL",
                        confidence=1.0
                    ))
                if raw_data.get("unemployment"):
                    evidence.append(EvidenceItem(
                        text=f"Unemployment Rate: {raw_data.get('unemployment_formatted', raw_data['unemployment'])}",
                        source="FRED - UNRATE",
                        confidence=1.0
                    ))
                if raw_data.get("recession_warning"):
                    risks.append("收益率曲线倒挂 - 潜在衰退信号")

            elif raw_data.get("source") == "estimate":
                data_sources = ["Estimate"]
                risks.append("使用估计值，非实时数据")

            elif raw_data.get("status") == "fallback":
                data_sources = ["Web Search"]
                risks.append("使用搜索回退，数据可能不完整")
                indicators = raw_data.get("indicators", [])
                for item in indicators[:3]:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name", "Macro indicator")
                    evidence.append(EvidenceItem(
                        text=f"{name}: 暂无可靠数值（搜索回退）",
                        source="search",
                        confidence=0.3
                    ))

        if not risks:
            risks = ["政策滞后效应", "数据发布延迟"]

        confidence_value = 0.95 if evidence else 0.7
        if isinstance(raw_data, dict):
            if raw_data.get("status") == "fallback":
                confidence_value = 0.4
            elif raw_data.get("status") == "error":
                confidence_value = 0.2

        trace = []
        if self._last_convergence:
            try:
                from backend.orchestration.trace_schema import create_trace_event
                trace.append(create_trace_event(
                    "convergence_check",
                    agent=self.AGENT_NAME,
                    **self._last_convergence,
                ))
            except Exception:
                pass

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence_value,
            data_sources=data_sources,
            as_of=datetime.now().isoformat(),
            risks=risks,
            trace=trace,
        )
