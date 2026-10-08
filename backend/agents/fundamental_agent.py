from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import os
from typing import Any, Dict, List, Optional, Tuple

from backend.agents.base_agent import AgentOutput, BaseFinancialAgent, ConflictClaim, EvidenceItem
from backend.agents.chart_specs import build_fundamental_chart_specs
from backend.research.agent_quality_contract import assign_evidence_source_ids, build_agent_claim
from backend.services.circuit_breaker import CircuitBreaker
from backend.tools.financial_facts import (
    comparison_point, duration_frequency, growth_rate, statement_dates, statement_frequency, statement_row,
)


# 方向枚举 → 中文文案（用户可见 claim 中文化，B 类固定模板）
_DIRECTION_CN: Dict[str, str] = {
    "positive": "向好",
    "negative": "转弱",
    "mixed": "分化",
    "neutral": "中性",
}


def _direction_cn(direction: str) -> str:
    """将方向枚举映射为中文，未知值原样返回。"""
    return _DIRECTION_CN.get(str(direction or "").strip().lower(), str(direction or ""))


class FundamentalAgent(BaseFinancialAgent):
    AGENT_NAME = "fundamental"
    CACHE_TTL = 86400  # 24 hours
    ERROR_CACHE_TTL = int(os.getenv("FUNDAMENTAL_ERROR_CACHE_TTL_SECONDS", "300"))

    _METRIC_DEFINITIONS: List[Dict[str, Any]] = [
        {"key": "revenue", "label": "营收", "table": "income", "candidates": ["total revenue", "revenue"]},
        {"key": "net_income", "label": "净利润", "table": "income", "candidates": ["net income"]},
        {"key": "operating_income", "label": "营业利润", "table": "income", "candidates": ["operating income"]},
        {"key": "operating_cash_flow", "label": "经营现金流", "table": "cashflow", "candidates": ["operating cash flow"]},
        {"key": "total_assets", "label": "总资产", "table": "balance", "candidates": ["total assets"]},
        {"key": "total_liabilities", "label": "总负债", "table": "balance", "candidates": ["total liabilities", "total liabilities net minority interest"]},
    ]

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
        earnings_func = getattr(self.tools, "get_earnings_estimates", None)
        eps_revision_func = getattr(self.tools, "get_eps_revisions", None)

        financials = (
            await asyncio.to_thread(financials_func, ticker)
            if financials_func
            else {"error": "missing_financials_tool"}
        )
        if isinstance(financials, dict) and financials.get("ticker") and str(financials["ticker"]).upper() != ticker.upper():
            financials = {"error": "issuer_mismatch", "ticker": ticker}
        company_info = await asyncio.to_thread(company_func, ticker) if company_func else ""
        earnings_estimates = (
            await asyncio.to_thread(earnings_func, ticker)
            if earnings_func
            else {"error": "missing_earnings_estimates_tool"}
        )
        eps_revisions = (
            await asyncio.to_thread(eps_revision_func, ticker)
            if eps_revision_func
            else {"error": "missing_eps_revisions_tool"}
        )

        if not isinstance(earnings_estimates, dict):
            earnings_estimates = {"error": "invalid_earnings_estimates_payload"}
        if not isinstance(eps_revisions, dict):
            eps_revisions = {"error": "invalid_eps_revisions_payload"}

        if isinstance(earnings_estimates, dict) and not earnings_estimates.get("eps_revisions"):
            if isinstance(eps_revisions.get("eps_revisions"), list):
                earnings_estimates["eps_revisions"] = eps_revisions.get("eps_revisions")
            if eps_revisions.get("revision_signal"):
                earnings_estimates["revision_signal"] = eps_revisions.get("revision_signal")

        normalized_metrics = self._build_normalized_metrics(financials if isinstance(financials, dict) else {})

        data = {
            "ticker": ticker,
            "financials": financials,
            "company_info": company_info,
            "earnings_estimates": earnings_estimates,
            "eps_revisions": eps_revisions,
            "normalized_metrics": normalized_metrics,
        }
        cache_ttl = self.CACHE_TTL
        if self._is_financials_error_payload(financials):
            cache_ttl = max(30, int(self.ERROR_CACHE_TTL))
        self.cache.set(cache_key, data, cache_ttl)
        return data

    async def _first_summary(self, data: Any) -> str:
        return self._deterministic_summary(data)

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
        missing_labels = [definition["label"] for definition in self._METRIC_DEFINITIONS if definition["table"] != "balance" and metric_map.get(definition["key"], {}).get("latest") is None]
        if missing_labels:
            summary_parts.append(f"[数据缺失] 当前报告期同口径的{'、'.join(missing_labels)}不可用，未使用其他财期或累计值补齐。")
        if revenue.get("latest") is not None and revenue.get("yoy") is None:
            summary_parts.append("[数据缺失] 未取得可对齐的上年同期营收，不能计算营收同比。")
        if any(metric.get("latest") is not None and not metric.get("currency") for metric in metric_map.values()):
            summary_parts.append("[数据缺失] 部分财务数值的报表币种未核验。")

        assets_value = self._safe_float(total_assets.get("latest"))
        liabilities_value = self._safe_float(total_liabilities.get("latest"))
        if assets_value is not None and liabilities_value is not None and assets_value != 0:
            debt_ratio = liabilities_value / assets_value
            summary_parts.append(f"负债/资产 {debt_ratio:.1%}。")

        earnings_payload = data.get("earnings_estimates") if isinstance(data.get("earnings_estimates"), dict) else {}
        eps_revisions_payload = data.get("eps_revisions") if isinstance(data.get("eps_revisions"), dict) else {}
        revision_signal = str(
            earnings_payload.get("revision_signal")
            or eps_revisions_payload.get("revision_signal")
            or "unknown"
        ).lower()
        # EPS 修正趋势中文文案映射（B 类固定模板中文化）
        signal_text_map = {
            "positive": "EPS 预期修正趋势向好。",
            "neutral": "EPS 预期修正趋势中性。",
            "negative": "EPS 预期修正趋势转弱。",
        }
        if revision_signal in signal_text_map:
            summary_parts.append(signal_text_map[revision_signal])

        calendar_payload = earnings_payload.get("calendar") if isinstance(earnings_payload, dict) else {}
        if isinstance(calendar_payload, dict):
            for key in ("Earnings Date", "earningsDate", "EarningsDate"):
                value = calendar_payload.get(key)
                if value:
                    summary_parts.append(f"即将到来的财报窗口：{value}")
                    break

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
            source = str(financials.get("source") or financials.get("provider") or "unknown")
            data_sources.append(source)
            # 构造 Yahoo Finance 财务页面 URL，供证据池可点击跳转
            _ticker = str(raw_data.get("ticker") or "").strip().upper()
            _yf_financials_url = f"https://finance.yahoo.com/quote/{_ticker}/financials/" if _ticker and source == "yfinance" else None
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
                        text=f"{definition['label']}: {self._format_value(latest_value, metric.get('currency'))}",
                        source=source,
                        url=metric.get("source_url") or _yf_financials_url,
                        timestamp=str(metric.get("latest_period") or ""),
                        meta={
                            "value": latest_value,
                            "metric_key": key,
                            "metric": key,
                            "subject": _ticker,
                            "period_type": metric.get("period_type"),
                            "frequency": metric.get("period_type"),
                            "period_end": metric.get("latest_period"),
                            "yoy": metric.get("yoy"),
                            "yoy_period": metric.get("yoy_period"),
                            "series": metric.get("series"),
                            "qoq": metric.get("qoq"),
                            "latest_period": metric.get("latest_period"),
                            "comparison_period": metric.get("comparison_period"),
                            "currency": metric.get("currency"),
                            "period_start": metric.get("period_start"),
                            "unit": metric.get("unit"),
                            "source": metric.get("source"),
                            "filed": metric.get("filed"),
                            "concept": metric.get("concept"),
                            "accession": metric.get("accession"),
                        },
                    )
                )

            earnings_payload = raw_data.get("earnings_estimates") if isinstance(raw_data.get("earnings_estimates"), dict) else {}
            eps_revisions_payload = raw_data.get("eps_revisions") if isinstance(raw_data.get("eps_revisions"), dict) else {}
            revision_signal = str(
                earnings_payload.get("revision_signal")
                or eps_revisions_payload.get("revision_signal")
                or "unknown"
            ).lower()
            if revision_signal in {"positive", "neutral", "negative"}:
                evidence.append(
                    EvidenceItem(
                        text=f"EPS revision signal: {revision_signal}",
                        source="yfinance_earnings",
                        url=_yf_financials_url,  # Yahoo Finance 财务页面，供证据池点击跳转
                        timestamp=str(earnings_payload.get("as_of") or eps_revisions_payload.get("as_of") or ""),
                        meta={
                            "metric_key": "eps_revision_signal",
                            "revision_signal": revision_signal,
                            "eps_revisions_count": len(
                                earnings_payload.get("eps_revisions")
                                if isinstance(earnings_payload.get("eps_revisions"), list)
                                else (eps_revisions_payload.get("eps_revisions") or [])
                            ),
                        },
                    )
                )
                data_sources.append("yfinance_earnings")

            evidence_quality = self._compute_evidence_quality(normalized)

        quality_score = self._safe_float(evidence_quality.get("overall_score")) if isinstance(evidence_quality, dict) else None
        # P0-2: 无证据时不演戏——confidence 压到 0.1，禁止 0.2 下限保护制造"有点信心"的假象
        if evidence:
            confidence = quality_score if quality_score is not None else 0.7
            confidence = max(0.2, min(0.92, confidence))
        else:
            confidence = 0.1
            fallback_used = True
        risks = self._build_risks(raw_data, normalized)
        source_ids = assign_evidence_source_ids(evidence, agent_name=self.AGENT_NAME)
        claims = self._build_native_claims(
            query=self._current_query or "",
            ticker=str(raw_data.get("ticker") or "") if isinstance(raw_data, dict) else "",
            normalized=normalized,
            evidence=evidence,
            risks=risks,
            confidence=confidence,
            source_ids=source_ids,
        )

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
            # P0-2: 无证据是最严重的缺失，覆盖为明确原因
            if not evidence:
                fallback_reason = "no_fundamental_data"

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=data_sources or ["yfinance"],
            as_of=datetime.now(timezone.utc).isoformat(),
            claims=claims,
            chart_specs=build_fundamental_chart_specs(
                str(raw_data.get("ticker") or "") if isinstance(raw_data, dict) else "",
                normalized,
            ),
            evidence_quality=evidence_quality,
            fallback_used=fallback_used,
            risks=risks,
            conflict_flags=conflict_flags,
            conflicting_claims=conflicting_claims,
            fallback_reason=fallback_reason,
            retryable=True,
        )

    def _build_native_claims(
        self,
        *,
        query: str,
        ticker: str,
        normalized: Dict[str, Any],
        evidence: List[EvidenceItem],
        risks: List[str],
        confidence: float,
        source_ids: List[str],
    ) -> List[Dict[str, Any]]:
        del source_ids
        metric_map = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
        if not metric_map:
            return []

        evidence_by_metric: Dict[str, str] = {}
        for item in evidence:
            metric_key = str((item.meta or {}).get("metric_key") or "").strip()
            source_id = str((item.meta or {}).get("source_id") or "").strip()
            if metric_key and source_id:
                evidence_by_metric[metric_key] = source_id

        def _metric(key: str) -> Dict[str, Any]:
            payload = metric_map.get(key)
            return payload if isinstance(payload, dict) else {}

        def _metric_evidence(*keys: str) -> List[str]:
            return [evidence_by_metric[key] for key in keys if evidence_by_metric.get(key)]

        claims: List[Dict[str, Any]] = []
        revenue = _metric("revenue")
        net_income = _metric("net_income")
        operating_income = _metric("operating_income")
        revenue_yoy = self._safe_float(revenue.get("yoy"))
        net_income_yoy = self._safe_float(net_income.get("yoy"))
        growth_evidence = _metric_evidence("revenue", "net_income", "operating_income")
        if growth_evidence:
            if revenue_yoy is not None and revenue_yoy > 0 and (net_income_yoy is None or net_income_yoy >= 0):
                stance = "bull"
                direction = "positive"
            elif revenue_yoy is not None and revenue_yoy < 0 and (net_income_yoy is None or net_income_yoy <= 0):
                stance = "bear"
                direction = "negative"
            else:
                stance = "neutral"
                direction = "mixed"
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=(
                        f"{ticker} 成长质量{_direction_cn(direction)}：营收同比 "
                        f"{revenue_yoy:.1%}。" if revenue_yoy is not None else f"{ticker} 营收趋势数据已获取。"
                    ),
                    evidence_ids=growth_evidence,
                    stance=stance,
                    confidence=confidence,
                    limitations=["财务报表快照，最终投资决策前请核对原始申报文件。"],
                    metadata={"claim_type": "growth_quality"},
                )
            )

        cash_flow = _metric("operating_cash_flow")
        cash_flow_evidence = _metric_evidence("operating_cash_flow", "net_income")
        ocf_value = self._safe_float(cash_flow.get("latest"))
        net_income_value = self._safe_float(net_income.get("latest"))
        if cash_flow_evidence and ocf_value is not None:
            if net_income_value is not None and ocf_value >= net_income_value:
                stance = "bull"
                claim_text = f"{ticker} 经营现金流覆盖净利润，支撑盈利质量。"
            elif net_income_value is not None and ocf_value < net_income_value * 0.7:
                stance = "bear"
                claim_text = f"{ticker} 经营现金流明显低于净利润，削弱盈利质量。"
            else:
                stance = "neutral"
                claim_text = f"{ticker} 经营现金流数据已获取，但需结合盈利情况综合判断。"
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=claim_text,
                    evidence_ids=cash_flow_evidence,
                    stance=stance,
                    confidence=confidence,
                    limitations=["现金流质量结论仅基于可用报表行项目。"],
                    metadata={"claim_type": "cash_flow_quality"},
                )
            )

        eps_source_id = evidence_by_metric.get("eps_revision_signal")
        if eps_source_id:
            eps_signal = ""
            for item in evidence:
                if (item.meta or {}).get("metric_key") == "eps_revision_signal":
                    eps_signal = str((item.meta or {}).get("revision_signal") or "").lower()
                    break
            stance = "bull" if eps_signal == "positive" else ("bear" if eps_signal == "negative" else "neutral")
            eps_signal_cn = _direction_cn(eps_signal) if eps_signal else "数据已获取"
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=f"{ticker} EPS 预期修正信号为{eps_signal_cn}，影响前瞻盈利信心。",
                    evidence_ids=[eps_source_id],
                    stance=stance,
                    confidence=min(0.9, confidence),
                    limitations=["EPS 修正数据是前瞻预估信号，并非已实现结果。"],
                    metadata={"claim_type": "eps_revision"},
                )
            )

        assets = _metric("total_assets")
        liabilities = _metric("total_liabilities")
        leverage_evidence = _metric_evidence("total_assets", "total_liabilities")
        assets_value = self._safe_float(assets.get("latest"))
        liabilities_value = self._safe_float(liabilities.get("latest"))
        if leverage_evidence and assets_value not in (None, 0) and liabilities_value is not None:
            leverage = liabilities_value / assets_value
            stance = "risk" if leverage >= 0.6 else "neutral"
            claims.append(
                build_agent_claim(
                    agent_name=self.AGENT_NAME,
                    ticker=ticker,
                    query=query,
                    claim=f"{ticker} 负债/资产比为 {leverage:.1%}，影响资产负债表风险。",
                    evidence_ids=leverage_evidence,
                    stance=stance,
                    confidence=confidence,
                    limitations=risks[:2],
                    metadata={"claim_type": "balance_sheet_risk", "leverage": round(leverage, 4)},
                )
            )

        return claims[:6]

    def _build_normalized_metrics(self, financials: Dict[str, Any]) -> Dict[str, Any]:
        income = financials.get("financials") if isinstance(financials, dict) else None
        balance = financials.get("balance_sheet") if isinstance(financials, dict) else None
        cashflow = financials.get("cashflow") if isinstance(financials, dict) else None

        columns = self._extract_columns(income, balance, cashflow)
        primary_table = next((table for table in (income, balance, cashflow) if isinstance(table, dict) and statement_dates(table)), {})
        period_type = statement_frequency(primary_table, columns)
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
            table_columns = statement_dates(table)
            metric_period_type = statement_frequency(table, table_columns)
            series = self._extract_metric_series(table, definition["candidates"], table_columns)
            is_balance = definition["table"] == "balance"
            same_end = bool(table_columns and table_columns[0] == latest_period)
            same_frequency = is_balance or metric_period_type == period_type
            missing_reason = None
            if not same_end:
                missing_reason = "report_period_mismatch"
            elif not same_frequency:
                missing_reason = "statement_frequency_mismatch"
            latest = series[0]["value"] if series and not missing_reason else None
            previous_point = comparison_point(series, days=91, tolerance=20) if metric_period_type == "quarterly" else None
            yoy_point = comparison_point(series, days=365, tolerance=15) if metric_period_type in {"quarterly", "annual", "instant"} else None
            previous = previous_point.get("value") if previous_point else None
            qoq = growth_rate(latest, previous) if not is_balance else None
            yoy = growth_rate(latest, yoy_point.get("value")) if yoy_point else None
            metadata = table.get("fact_metadata") or {}
            raw_facts = (metadata.get(definition["key"]) or []) if isinstance(metadata, dict) else []
            fact = next((item for item in raw_facts if isinstance(item, dict) and item.get("period_end") == latest_period), {})
            period_start = fact.get("period_start")
            if not period_start and not is_balance and len(table_columns) > 1:
                candidate_start = (datetime.fromisoformat(table_columns[1]) + timedelta(days=1)).date().isoformat()
                if duration_frequency(candidate_start, table_columns[0]) == metric_period_type:
                    period_start = candidate_start

            metrics[definition["key"]] = {
                "label": definition["label"],
                "latest": latest,
                "previous": previous,
                "latest_period": table_columns[0] if table_columns else None,
                "comparison_period": previous_point.get("period") if previous_point else None,
                "period_type": "instant" if is_balance else metric_period_type,
                "qoq": qoq,
                "yoy": yoy,
                "yoy_period": yoy_point.get("period") if yoy_point else None,
                "series": series[:8],
                "currency": table.get("currency") or financials.get("currency"),
                "unit": fact.get("unit") or table.get("currency") or financials.get("currency"),
                "period_start": period_start,
                "source": table.get("source") or financials.get("source"),
                "source_url": fact.get("source_url"),
                "filed": fact.get("filed"),
                "concept": fact.get("concept"),
                "accession": fact.get("accession"),
                "missing_reason": missing_reason or ("metric_not_available" if latest is None else None),
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
            normalized = statement_dates(table)
            if normalized:
                return normalized
        return []

    def _extract_metric_series(self, table: Dict[str, Any], candidates: List[str], columns: List[str]) -> List[Dict[str, Any]]:
        if not isinstance(table, dict) or not columns:
            return []

        row = statement_row(table, candidates)
        if row is None:
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
        bits = [f"{label} {self._format_value(latest, metric.get('currency'))}"]
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

    def _format_value(self, value: float, currency: str | None = None) -> str:
        prefix = "$" if currency == "USD" else f"{currency} " if currency else ""
        if abs(value) >= 1e12:
            return f"{prefix}{value/1e12:.2f}T"
        if abs(value) >= 1e9:
            return f"{prefix}{value/1e9:.2f}B"
        if abs(value) >= 1e6:
            return f"{prefix}{value/1e6:.2f}M"
        return f"{prefix}{value:.2f}"

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
        earnings_payload = raw_data.get("earnings_estimates") if isinstance(raw_data, dict) and isinstance(raw_data.get("earnings_estimates"), dict) else {}
        eps_revisions_payload = raw_data.get("eps_revisions") if isinstance(raw_data, dict) and isinstance(raw_data.get("eps_revisions"), dict) else {}
        revision_signal = str(
            earnings_payload.get("revision_signal")
            or eps_revisions_payload.get("revision_signal")
            or "unknown"
        ).lower()
        if revision_signal == "negative":
            risks.append("EPS 预期修正趋势转弱，前瞻盈利预期可能承压。")
        if isinstance(financials, dict) and financials.get("error") and not self._has_financial_tables(financials):
            risks.append("财务数据获取异常，建议核实原始财报。")

        return risks or ["基本面数据未见重大风险信号。"]
