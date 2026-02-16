from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional, Tuple

from backend.agents.base_agent import AgentOutput, BaseFinancialAgent, ConflictClaim, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker


class FundamentalAgent(BaseFinancialAgent):
    AGENT_NAME = "fundamental"
    CACHE_TTL = 86400  # 24 hours
    ERROR_CACHE_TTL = int(os.getenv("FUNDAMENTAL_ERROR_CACHE_TTL_SECONDS", "300"))
    MAX_REFLECTIONS = 1  # Chain-of-Thought: one reflection to check for missed risk signals

    _METRIC_DEFINITIONS: List[Dict[str, Any]] = [
        {"key": "revenue", "label": "营收", "table": "income", "candidates": ["total revenue", "revenue"]},
        {"key": "net_income", "label": "净利润", "table": "income", "candidates": ["net income"]},
        {"key": "operating_income", "label": "营业利润", "table": "income", "candidates": ["operating income", "ebit"]},
        {"key": "operating_cash_flow", "label": "经营现金流", "table": "cashflow", "candidates": ["operating cash flow"]},
        {"key": "total_assets", "label": "总资产", "table": "balance", "candidates": ["total assets"]},
        {"key": "total_liabilities", "label": "总负债", "table": "balance", "candidates": ["total liabilities"]},
    ]

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    def _get_tool_registry(self) -> dict:
        """FundamentalAgent tool registry: financial APIs + search for CoT reflection."""
        registry = {}
        tools = self.tools
        if not tools:
            return registry
        search_fn = getattr(tools, "search", None)
        if search_fn:
            registry["search"] = {
                "func": search_fn,
                "description": "通用网络搜索，查询公司基本面、行业对比等",
                "call_with": "query",
            }
        financials_fn = getattr(tools, "get_financial_statements", None)
        if financials_fn:
            registry["get_financial_statements"] = {
                "func": financials_fn,
                "description": "获取财务报表(ticker)，包含利润表、资产负债表、现金流量表",
                "call_with": "ticker",
            }
        company_fn = getattr(tools, "get_company_info", None)
        if company_fn:
            registry["get_company_info"] = {
                "func": company_fn,
                "description": "获取公司概况(ticker)，包含行业、市值、主营业务",
                "call_with": "ticker",
            }
        return registry

    @staticmethod
    def _has_financial_tables(financials: Any) -> bool:
        if not isinstance(financials, dict):
            return False
        for key in ("financials", "balance_sheet", "cashflow"):
            table = financials.get(key)
            if isinstance(table, dict) and bool(table):
                return True
        return False

    @classmethod
    def _is_financials_error_payload(cls, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return True
        if cls._has_financial_tables(payload):
            return False
        return bool(payload.get("error"))

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        cache_key = f"{ticker}:fundamental:financials"
        cached = self.cache.get(cache_key)
        if isinstance(cached, dict):
            cached_financials = cached.get("financials")
            if not self._is_financials_error_payload(cached_financials):
                if "normalized_metrics" not in cached:
                    cached["normalized_metrics"] = self._build_normalized_metrics(cached_financials or {})
                return cached

        financials_func = getattr(self.tools, "get_financial_statements", None)
        company_func = getattr(self.tools, "get_company_info", None)

        financials = financials_func(ticker) if financials_func else {"error": "missing_financials_tool"}
        company_info = company_func(ticker) if company_func else ""
        normalized_metrics = self._build_normalized_metrics(financials if isinstance(financials, dict) else {})

        data = {
            "ticker": ticker,
            "financials": financials,
            "company_info": company_info,
            "normalized_metrics": normalized_metrics,
        }
        cache_ttl = self.CACHE_TTL
        if self._is_financials_error_payload(financials):
            cache_ttl = max(30, int(self.ERROR_CACHE_TTL))
        self.cache.set(cache_key, data, cache_ttl)
        return data

    async def _first_summary(self, data: Any) -> str:
        """True Chain-of-Thought: 2-step LLM analysis with chained dependency.

        Step 1: Profitability quality + financial health analysis.
        Step 2: Growth sustainability + risk signals (builds on Step 1 output).

        If any step fails, gracefully degrades to the previous step or deterministic.
        """
        deterministic = self._deterministic_summary(data)
        if not isinstance(data, dict):
            return deterministic

        # Build rich context: deterministic metrics + raw financial hints
        context_parts = [deterministic]
        company_info = data.get("company_info", "")
        if isinstance(company_info, str) and company_info.strip():
            context_parts.append(f"\n公司概况: {company_info[:500]}")
        base_context = "\n".join(context_parts)

        # ── Step 1: Profitability & Financial Health ──
        step1 = await self._llm_analyze(
            base_context,
            role="资深卖方基本面分析师（Chain-of-Thought 推理模式 — 第一步）",
            focus=(
                "按链式推理（CoT）进行第一阶段分析：\n"
                "1. 盈利质量：营收与净利润的增长是否可持续？利润率趋势如何？\n"
                "2. 财务健康：杠杆水平、现金流覆盖能力、偿债风险\n"
                "3. 关键发现：最值得注意的 1-2 个财务信号\n"
                "输出一段连贯的财务分析文本，为后续分析奠定基础。"
            ),
        )
        if not step1:
            return deterministic

        # ── Step 2: Growth + Valuation + Risk (chains on Step 1) ──
        step2_input = f"{base_context}\n\n--- 第一步分析结果 ---\n{step1}"
        step2 = await self._llm_analyze(
            step2_input,
            role="资深卖方基本面分析师（Chain-of-Thought 推理模式 — 第二步）",
            focus=(
                "基于第一步的盈利质量和财务健康分析，继续推理：\n"
                "1. 增长持续性：同比/环比趋势是加速还是减速？关键驱动因素是什么？\n"
                "2. 估值含义：当前财务表现对估值倍数的支撑或压力\n"
                "3. 风险信号：是否存在盈利粉饰、现金流与利润背离、异常一次性项目\n"
                "4. 综合判断：整合第一步和第二步的分析，给出整体评价\n"
                "输出一段连贯的分析文本，体现从第一步到第二步的推理链条。"
            ),
        )
        if not step2:
            return step1  # Degrade to step1 if step2 fails

        return f"{step1}\n\n{step2}"

    def _deterministic_summary(self, data: Any) -> str:
        """Deterministic metrics-based summary (fallback)."""
        if not isinstance(data, dict):
            return "基本面数据读取失败。"

        financials = data.get("financials") or {}
        if isinstance(financials, dict) and financials.get("error") and not self._has_financial_tables(financials):
            return f"财务报表获取失败: {financials.get('error')}"

        normalized = data.get("normalized_metrics")
        if not isinstance(normalized, dict):
            normalized = self._build_normalized_metrics(financials if isinstance(financials, dict) else {})

        summary_parts: List[str] = []
        company_meta = self._parse_company_info(data.get("company_info", ""))
        if company_meta:
            meta_text = " | ".join(
                part
                for part in [
                    company_meta.get("name"),
                    company_meta.get("sector"),
                    company_meta.get("industry"),
                    company_meta.get("market_cap"),
                ]
                if part
            )
            if meta_text:
                summary_parts.append(meta_text)

        period_context = normalized.get("period_context") if isinstance(normalized.get("period_context"), dict) else {}
        latest_period = period_context.get("latest_period")
        period_type = period_context.get("period_type") or "unknown"
        if latest_period:
            summary_parts.append(f"最新报告期: {latest_period}（{period_type}）。")

        metric_map = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
        revenue = metric_map.get("revenue") if isinstance(metric_map.get("revenue"), dict) else {}
        net_income = metric_map.get("net_income") if isinstance(metric_map.get("net_income"), dict) else {}
        operating_income = metric_map.get("operating_income") if isinstance(metric_map.get("operating_income"), dict) else {}
        operating_cash_flow = metric_map.get("operating_cash_flow") if isinstance(metric_map.get("operating_cash_flow"), dict) else {}
        total_assets = metric_map.get("total_assets") if isinstance(metric_map.get("total_assets"), dict) else {}
        total_liabilities = metric_map.get("total_liabilities") if isinstance(metric_map.get("total_liabilities"), dict) else {}

        summary_parts.append(self._format_metric_sentence("营收", revenue))
        summary_parts.append(self._format_metric_sentence("净利润", net_income))
        summary_parts.append(self._format_metric_sentence("营业利润", operating_income))
        summary_parts.append(self._format_metric_sentence("经营现金流", operating_cash_flow))

        assets_value = self._safe_float(total_assets.get("latest"))
        liabilities_value = self._safe_float(total_liabilities.get("latest"))
        if assets_value is not None and liabilities_value is not None and assets_value != 0:
            debt_ratio = liabilities_value / assets_value
            summary_parts.append(f"负债/资产 {debt_ratio:.1%}。")

        summary_parts = [item for item in summary_parts if item]
        if not summary_parts:
            return "最新财报中未找到可用的基本面指标。"
        return " ".join(summary_parts)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence: List[EvidenceItem] = []
        data_sources: List[str] = []
        fallback_used = False
        evidence_quality: Dict[str, Any] = {}

        normalized: Dict[str, Any] = {}
        if isinstance(raw_data, dict):
            financials = raw_data.get("financials") or {}
            source = "yfinance"
            data_sources.append(source)
            fallback_used = bool(
                isinstance(financials, dict)
                and financials.get("error")
                and not self._has_financial_tables(financials)
            )

            normalized = raw_data.get("normalized_metrics")
            if not isinstance(normalized, dict):
                normalized = self._build_normalized_metrics(financials if isinstance(financials, dict) else {})

            metric_map = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
            for definition in self._METRIC_DEFINITIONS:
                key = definition["key"]
                metric = metric_map.get(key)
                if not isinstance(metric, dict):
                    continue
                latest_value = self._safe_float(metric.get("latest"))
                if latest_value is None:
                    continue
                evidence.append(
                    EvidenceItem(
                        text=f"{definition['label']}: {self._format_value(latest_value)}",
                        source=source,
                        timestamp=str(metric.get("latest_period") or ""),
                        meta={
                            "metric_key": key,
                            "period_type": metric.get("period_type"),
                            "yoy": metric.get("yoy"),
                            "qoq": metric.get("qoq"),
                            "latest_period": metric.get("latest_period"),
                            "comparison_period": metric.get("comparison_period"),
                        },
                    )
                )

            evidence_quality = self._compute_evidence_quality(normalized)

        quality_score = self._safe_float(evidence_quality.get("overall_score")) if isinstance(evidence_quality, dict) else None
        confidence = quality_score if quality_score is not None else (0.7 if evidence else 0.2)
        confidence = max(0.2, min(0.92, confidence))
        risks = self._build_risks(raw_data, normalized)

        # --- Conflict detection: revenue growth vs margin direction ---
        conflict_flags: List[str] = []
        conflicting_claims: List[ConflictClaim] = []
        if isinstance(normalized, dict):
            metric_map_for_conflict = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
            revenue_m = metric_map_for_conflict.get("total_revenue", {})
            margin_m = metric_map_for_conflict.get("gross_margin", {})
            rev_yoy = self._safe_float(revenue_m.get("yoy")) if isinstance(revenue_m, dict) else None
            margin_qoq = self._safe_float(margin_m.get("qoq")) if isinstance(margin_m, dict) else None
            if rev_yoy is not None and margin_qoq is not None:
                if rev_yoy > 10 and margin_qoq < -5:
                    conflict_flags.append("营收高增长 vs 毛利率下滑")
                    conflicting_claims.append(ConflictClaim(
                        claim="盈利质量一致性",
                        source_a="营收同比",
                        value_a=f"+{rev_yoy:.1f}% (高增长)",
                        source_b="毛利率环比",
                        value_b=f"{margin_qoq:+.1f}% (下滑)",
                        severity="medium",
                    ))
                elif rev_yoy < -5 and margin_qoq > 5:
                    conflict_flags.append("营收下滑 vs 毛利率扩张")
                    conflicting_claims.append(ConflictClaim(
                        claim="盈利质量一致性",
                        source_a="营收同比",
                        value_a=f"{rev_yoy:+.1f}% (下滑)",
                        source_b="毛利率环比",
                        value_b=f"+{margin_qoq:.1f}% (扩张)",
                        severity="low",
                    ))

        # Fallback observability
        fallback_reason = None
        if fallback_used:
            if isinstance(raw_data, dict):
                err_msg = raw_data.get("financials", {})
                if isinstance(err_msg, dict):
                    fallback_reason = str(err_msg.get("error") or "financial_data_incomplete")
                else:
                    fallback_reason = "financial_data_unavailable"
            else:
                fallback_reason = "no_structured_data"

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=data_sources or ["yfinance"],
            as_of=datetime.now(timezone.utc).isoformat(),
            evidence_quality=evidence_quality,
            fallback_used=fallback_used,
            risks=risks,
            conflict_flags=conflict_flags,
            conflicting_claims=conflicting_claims,
            fallback_reason=fallback_reason,
            retryable=True,
        )

    def _build_normalized_metrics(self, financials: Dict[str, Any]) -> Dict[str, Any]:
        income = financials.get("financials") if isinstance(financials, dict) else None
        balance = financials.get("balance_sheet") if isinstance(financials, dict) else None
        cashflow = financials.get("cashflow") if isinstance(financials, dict) else None

        columns = self._extract_columns(income, balance, cashflow)
        period_type = self._infer_period_type(columns)
        latest_period = columns[0] if columns else None
        comparison_period = columns[1] if len(columns) > 1 else None

        table_map = {
            "income": income if isinstance(income, dict) else {},
            "balance": balance if isinstance(balance, dict) else {},
            "cashflow": cashflow if isinstance(cashflow, dict) else {},
        }

        metrics: Dict[str, Dict[str, Any]] = {}
        for definition in self._METRIC_DEFINITIONS:
            table = table_map.get(definition["table"], {})
            series = self._extract_metric_series(table, definition["candidates"], columns)
            latest = series[0]["value"] if series else None
            previous = series[1]["value"] if len(series) > 1 else None

            yoy: Optional[float] = None
            yoy_period: Optional[str] = None
            qoq: Optional[float] = None
            if period_type == "quarterly":
                if len(series) > 1:
                    qoq = self._growth_pct(latest, previous)
                if len(series) > 4:
                    yoy = self._growth_pct(latest, series[4]["value"])
                    yoy_period = series[4]["period"]
                elif len(series) > 1:
                    yoy = self._growth_pct(latest, previous)
                    yoy_period = series[1]["period"]
            else:
                if len(series) > 1:
                    yoy = self._growth_pct(latest, previous)
                    yoy_period = series[1]["period"]

            metrics[definition["key"]] = {
                "label": definition["label"],
                "latest": latest,
                "previous": previous,
                "latest_period": latest_period,
                "comparison_period": comparison_period,
                "period_type": period_type,
                "qoq": qoq,
                "yoy": yoy,
                "yoy_period": yoy_period,
                "series": series[:8],
            }

        return {
            "period_context": {
                "latest_period": latest_period,
                "comparison_period": comparison_period,
                "period_type": period_type,
                "column_count": len(columns),
            },
            "metrics": metrics,
        }

    def _extract_columns(self, *tables: Any) -> List[str]:
        for table in tables:
            if not isinstance(table, dict):
                continue
            cols = table.get("columns")
            if not isinstance(cols, list) or not cols:
                continue
            normalized = [self._normalize_period_label(col) for col in cols]
            normalized = [item for item in normalized if item]
            if normalized:
                return normalized
        return []

    def _extract_metric_series(self, table: Dict[str, Any], candidates: List[str], columns: List[str]) -> List[Dict[str, Any]]:
        if not isinstance(table, dict) or not columns:
            return []

        index = table.get("index")
        rows = table.get("data")
        if not isinstance(index, list) or not isinstance(rows, list):
            return []

        row_idx: Optional[int] = None
        for idx, row_name in enumerate(index):
            row_name_lower = str(row_name).lower()
            if any(candidate in row_name_lower for candidate in candidates):
                row_idx = idx
                break
        if row_idx is None or row_idx >= len(rows):
            return []

        row = rows[row_idx] if isinstance(rows[row_idx], dict) else {}
        if not isinstance(row, dict):
            return []

        series: List[Dict[str, Any]] = []
        for col in columns:
            value = self._row_value_by_period(row, col)
            series.append({"period": col, "value": self._safe_float(value)})
        return series

    def _row_value_by_period(self, row: Dict[str, Any], period: str) -> Any:
        if period in row:
            return row.get(period)
        for key, value in row.items():
            if self._normalize_period_label(key) == period:
                return value
        return None

    def _normalize_period_label(self, value: Any) -> str:
        text = str(value).strip()
        if not text:
            return ""
        if " " in text:
            text = text.split(" ", 1)[0]
        if "T" in text:
            text = text.split("T", 1)[0]
        return text

    def _infer_period_type(self, columns: List[str]) -> str:
        if len(columns) < 2:
            return "unknown"
        latest = self._parse_date(columns[0])
        prev = self._parse_date(columns[1])
        if latest is None or prev is None:
            return "unknown"
        days = abs((latest - prev).days)
        if days <= 130:
            return "quarterly"
        if days >= 300:
            return "annual"
        return "unknown"

    def _parse_date(self, value: str) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _growth_pct(self, latest: Optional[float], base: Optional[float]) -> Optional[float]:
        if latest is None or base in (None, 0):
            return None
        return (latest - base) / abs(base)

    def _format_metric_sentence(self, label: str, metric: Dict[str, Any]) -> str:
        if not isinstance(metric, dict):
            return ""
        latest = self._safe_float(metric.get("latest"))
        if latest is None:
            return ""
        bits = [f"{label} {self._format_value(latest)}"]
        growth_bits: List[str] = []
        qoq = self._safe_float(metric.get("qoq"))
        yoy = self._safe_float(metric.get("yoy"))
        if qoq is not None:
            growth_bits.append(f"环比 {qoq:.1%}")
        if yoy is not None:
            growth_bits.append(f"同比 {yoy:.1%}")
        if growth_bits:
            bits.append(f"({', '.join(growth_bits)})")
        return " ".join(bits) + "."

    def _compute_evidence_quality(self, normalized: Dict[str, Any]) -> Dict[str, Any]:
        metric_map = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
        if not metric_map:
            return {
                "overall_score": 0.0,
                "metric_coverage": 0.0,
                "growth_coverage": 0.0,
                "source_diversity": 1,
                "has_conflicts": False,
            }

        total = len(metric_map)
        metric_with_values = 0
        metric_with_growth = 0
        for metric in metric_map.values():
            if not isinstance(metric, dict):
                continue
            if self._safe_float(metric.get("latest")) is not None:
                metric_with_values += 1
            if self._safe_float(metric.get("yoy")) is not None or self._safe_float(metric.get("qoq")) is not None:
                metric_with_growth += 1

        coverage = metric_with_values / max(1, total)
        growth_coverage = metric_with_growth / max(1, total)
        overall = coverage * 0.60 + growth_coverage * 0.40
        overall = max(0.0, min(1.0, overall))

        return {
            "overall_score": round(overall, 4),
            "metric_coverage": round(coverage, 4),
            "growth_coverage": round(growth_coverage, 4),
            "source_diversity": 1,
            "has_conflicts": False,
        }

    def _safe_float(self, value: Any) -> Optional[float]:
        from backend.utils.quote import safe_float

        return safe_float(value)

    def _format_value(self, value: float) -> str:
        if abs(value) >= 1e12:
            return f"${value/1e12:.2f}T"
        if abs(value) >= 1e9:
            return f"${value/1e9:.2f}B"
        if abs(value) >= 1e6:
            return f"${value/1e6:.2f}M"
        return f"${value:.2f}"

    def _parse_company_info(self, text: str) -> Dict[str, str]:
        if not text:
            return {}
        info: Dict[str, str] = {}
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

    def _build_risks(self, raw_data: Any, normalized: Dict[str, Any]) -> List[str]:
        metric_map = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
        net_income = metric_map.get("net_income") if isinstance(metric_map.get("net_income"), dict) else {}
        total_assets = metric_map.get("total_assets") if isinstance(metric_map.get("total_assets"), dict) else {}
        total_liabilities = metric_map.get("total_liabilities") if isinstance(metric_map.get("total_liabilities"), dict) else {}

        net_income_value = self._safe_float(net_income.get("latest"))
        assets_value = self._safe_float(total_assets.get("latest"))
        liabilities_value = self._safe_float(total_liabilities.get("latest"))

        risks: List[str] = []
        if net_income_value is not None and net_income_value < 0:
            risks.append("净利润为负，盈利能力存在风险。")
        if assets_value is not None and liabilities_value is not None and assets_value != 0:
            leverage = liabilities_value / assets_value
            if leverage > 0.6:
                risks.append(f"杠杆率偏高（负债/资产 = {leverage:.0%} > 60%），偿债压力较大。")

        financials = raw_data.get("financials") if isinstance(raw_data, dict) else {}
        if isinstance(financials, dict) and financials.get("error") and not self._has_financial_tables(financials):
            risks.append("财务数据获取异常，建议核实原始财报。")

        return risks or ["基本面数据未见重大风险信号。"]
