from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker


class FundamentalAgent(BaseFinancialAgent):
    AGENT_NAME = "fundamental"
    CACHE_TTL = 86400  # 24 hours

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        cache_key = f"{ticker}:fundamental:financials"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        financials_func = getattr(self.tools, "get_financial_statements", None)
        company_func = getattr(self.tools, "get_company_info", None)

        financials = financials_func(ticker) if financials_func else {"error": "missing_financials_tool"}
        company_info = company_func(ticker) if company_func else ""

        data = {
            "ticker": ticker,
            "financials": financials,
            "company_info": company_info,
        }
        self.cache.set(cache_key, data, self.CACHE_TTL)
        return data

    async def _first_summary(self, data: Any) -> str:
        if not isinstance(data, dict):
            return "Unable to read fundamental data."

        financials = data.get("financials") or {}
        if financials.get("error"):
            return f"Unable to fetch financial statements: {financials.get('error')}"

        income = financials.get("financials")
        balance = financials.get("balance_sheet")
        cashflow = financials.get("cashflow")
        latest_col, prev_col = self._latest_columns(income)

        revenue, revenue_prev = self._find_metric(income, ["total revenue", "revenue"], latest_col, prev_col)
        net_income, net_income_prev = self._find_metric(income, ["net income"], latest_col, prev_col)
        op_income, _ = self._find_metric(income, ["operating income", "ebit"], latest_col, prev_col)
        op_cf, _ = self._find_metric(cashflow, ["operating cash flow"], latest_col, prev_col)
        assets, _ = self._find_metric(balance, ["total assets"], latest_col, prev_col)
        liabilities, _ = self._find_metric(balance, ["total liabilities"], latest_col, prev_col)

        summary_parts = []
        company_meta = self._parse_company_info(data.get("company_info", ""))
        if company_meta:
            meta_text = " | ".join(
                part for part in [
                    company_meta.get("name"),
                    company_meta.get("sector"),
                    company_meta.get("industry"),
                    company_meta.get("market_cap"),
                ] if part
            )
            if meta_text:
                summary_parts.append(meta_text)

        if latest_col:
            summary_parts.append(f"Latest fiscal period: {latest_col}.")

        if revenue is not None:
            rev_text = f"Revenue {self._format_value(revenue)}"
            rev_yoy = self._format_growth(revenue, revenue_prev)
            if rev_yoy:
                rev_text += f" (YoY {rev_yoy})"
            summary_parts.append(rev_text + ".")

        if net_income is not None:
            ni_text = f"Net income {self._format_value(net_income)}"
            ni_yoy = self._format_growth(net_income, net_income_prev)
            if ni_yoy:
                ni_text += f" (YoY {ni_yoy})"
            summary_parts.append(ni_text + ".")

        if op_income is not None:
            summary_parts.append(f"Operating income {self._format_value(op_income)}.")

        if op_cf is not None:
            summary_parts.append(f"Operating cash flow {self._format_value(op_cf)}.")

        debt_ratio = None
        if assets is not None and liabilities is not None and assets != 0:
            debt_ratio = liabilities / assets
            summary_parts.append(f"Liabilities / Assets {debt_ratio:.1%}.")

        if not summary_parts:
            return "No usable fundamental metrics were found in the latest financials."

        return " ".join(summary_parts)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence: List[EvidenceItem] = []
        data_sources: List[str] = []
        fallback_used = False

        if isinstance(raw_data, dict):
            financials = raw_data.get("financials") or {}
            source = "yfinance"
            data_sources.append(source)
            fallback_used = bool(financials.get("error"))

            income = financials.get("financials")
            balance = financials.get("balance_sheet")
            cashflow = financials.get("cashflow")
            latest_col, prev_col = self._latest_columns(income)

            metrics = [
                ("Total Revenue", income, ["total revenue", "revenue"]),
                ("Net Income", income, ["net income"]),
                ("Operating Income", income, ["operating income", "ebit"]),
                ("Operating Cash Flow", cashflow, ["operating cash flow"]),
                ("Total Assets", balance, ["total assets"]),
                ("Total Liabilities", balance, ["total liabilities"]),
            ]

            for label, table, candidates in metrics:
                latest_val, _ = self._find_metric(table, candidates, latest_col, prev_col)
                if latest_val is not None:
                    evidence.append(EvidenceItem(
                        text=f"{label}: {self._format_value(latest_val)}",
                        source=source,
                        timestamp=latest_col,
                    ))

        confidence = 0.75 if evidence else 0.2
        risks = self._build_risks(raw_data)

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=data_sources or ["yfinance"],
            as_of=datetime.now().isoformat(),
            fallback_used=fallback_used,
            risks=risks,
        )

    def _latest_columns(self, table: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
        if not table or not table.get("columns"):
            return None, None
        columns = table.get("columns") or []
        latest_col = columns[0] if columns else None
        prev_col = columns[1] if len(columns) > 1 else None
        return latest_col, prev_col

    def _find_metric(
        self,
        table: Optional[Dict[str, Any]],
        candidates: List[str],
        latest_col: Optional[str],
        prev_col: Optional[str],
    ) -> Tuple[Optional[float], Optional[float]]:
        if not table or not latest_col:
            return None, None
        index = table.get("index") or []
        data_rows = table.get("data") or []
        for idx, row_name in enumerate(index):
            row_name_lower = str(row_name).lower()
            if any(candidate in row_name_lower for candidate in candidates):
                row = data_rows[idx] if idx < len(data_rows) else {}
                latest_val = self._to_float(row.get(latest_col))
                prev_val = self._to_float(row.get(prev_col)) if prev_col else None
                return latest_val, prev_val
        return None, None

    def _to_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_value(self, value: float) -> str:
        if abs(value) >= 1e12:
            return f"${value/1e12:.2f}T"
        if abs(value) >= 1e9:
            return f"${value/1e9:.2f}B"
        if abs(value) >= 1e6:
            return f"${value/1e6:.2f}M"
        return f"${value:.2f}"

    def _format_growth(self, latest: Optional[float], prev: Optional[float]) -> Optional[str]:
        if latest is None or prev in (None, 0):
            return None
        growth = (latest - prev) / abs(prev)
        return f"{growth:.1%}"

    def _parse_company_info(self, text: str) -> Dict[str, str]:
        if not text:
            return {}
        info = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("- Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Sector:"):
                info["sector"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Industry:"):
                info["industry"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Market Cap:"):
                info["market_cap"] = line.split(":", 1)[1].strip()
        return info

    def _build_risks(self, raw_data: Any) -> List[str]:
        if not isinstance(raw_data, dict):
            return ["Limited fundamental data available."]

        financials = raw_data.get("financials") or {}
        income = financials.get("financials")
        balance = financials.get("balance_sheet")
        latest_col, prev_col = self._latest_columns(income)
        net_income, _ = self._find_metric(income, ["net income"], latest_col, prev_col)
        assets, _ = self._find_metric(balance, ["total assets"], latest_col, prev_col)
        liabilities, _ = self._find_metric(balance, ["total liabilities"], latest_col, prev_col)

        risks = []
        if net_income is not None and net_income < 0:
            risks.append("Net income remains negative.")
        if assets is not None and liabilities is not None and assets != 0:
            leverage = liabilities / assets
            if leverage > 0.6:
                risks.append("Leverage ratio is elevated (liabilities/assets > 60%).")
        return risks or ["Fundamental data shows no major red flags."]
