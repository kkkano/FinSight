from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from contextvars import ContextVar
from calendar import monthrange
from typing import Any, Dict, List, Optional

from backend.agents.base_agent import AgentOutput, BaseFinancialAgent, ConflictClaim, EvidenceItem
from backend.agents.chart_specs_extra import build_macro_chart_specs
from backend.graph.request_task_contract import output_is_error_like
from backend.services.circuit_breaker import CircuitBreaker
from backend.tools.financial_facts import search_line_is_noise
from backend.tools.macro_official import official_macro_query

logger = logging.getLogger(__name__)


class MacroAgent(BaseFinancialAgent):
    """从官方和市场数据源采集、交叉校验宏观证据。"""

    AGENT_NAME = "macro"
    _MISSING_QUALITY_CONFIDENCE = 0.35  # P0-2: 质量分缺失时的诚实上限
    _indicator_request = ContextVar("macro_indicator_request", default=(None, None))
    _EMPLOYMENT_INDICATORS = {"nonfarm_payroll_change": {"label": "Nonfarm payroll monthly net change", "unit": "persons"}}

    _INDICATORS: Dict[str, Dict[str, str]] = {
        "fed_rate": {"label": "Federal funds rate", "unit": "%"},
        "cpi": {"label": "CPI inflation (year-over-year)", "unit": "%"},
        "unemployment": {"label": "Unemployment rate", "unit": "%"},
        "gdp_growth": {"label": "GDP growth", "unit": "%"},
        "treasury_10y": {"label": "10Y Treasury yield", "unit": "%"},
        "yield_spread": {"label": "10Y-2Y spread", "unit": "%"},
    }

    _SOURCE_PRIORITY = {
        "fred": 1,
        "official_releases": 2,
        "market_sentiment": 3,
        "economic_events": 4,
        "search_cross_check": 5,
    }

    _CONFLICT_TOLERANCE = {
        "fed_rate": 0.35,
        "cpi": 0.60,
        "unemployment": 0.40,
        "gdp_growth": 0.80,
        "treasury_10y": 0.35,
        "yield_spread": 0.35,
    }

    @staticmethod
    def _source_text(value: Any) -> tuple[str, str]:
        """复用执行失败合同，并识别现有文本工具的明确失败信封。"""
        text = str(value or "").strip()
        if output_is_error_like(value) or text.lower().startswith((
            "search error:", "error:", "fear & greed index: unable to fetch.",
        )):
            return "", "failed:tool_error"
        if not text or all(search_line_is_noise(line) for line in text.splitlines()):
            return "", "empty"
        return text, "ok"

    async def research(self, query: str, ticker: str, on_event=None, *, indicators: list[str] | None = None,
        as_of: str | None = None) -> AgentOutput:
        token = self._indicator_request.set((indicators, as_of))
        try:
            return await super().research(query, ticker, on_event=on_event)
        finally:
            self._indicator_request.reset(token)

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        source_health: Dict[str, str] = {}
        used_sources: List[str] = []
        requested, requested_as_of = self._indicator_request.get()
        active_keys = requested if requested is not None else list(self._INDICATORS)
        employment_requested = requested is not None and any(key in {"nonfarm_payroll_change", "unemployment"} for key in requested)

        fred_metrics: Dict[str, float] = {}
        fred_payload: Dict[str, Any] = {}
        try:
            if hasattr(self.tools, "get_fred_data"):
                kwargs = {"indicators": requested, "as_of": requested_as_of} if requested is not None else {}
                payload = await asyncio.to_thread(self.tools.get_fred_data, **kwargs)
                if isinstance(payload, dict) and payload.get("status") == "data_unavailable":
                    # FRED 不可用（如无 API key）：明确走 fallback 路径，不把空 payload 当数据用（P0-1）
                    logger.info("[MacroAgent] FRED unavailable: %s", payload.get("unavailable_reason"))
                    payload = None
                if isinstance(payload, dict):
                    fred_payload = payload
                    fred_metrics = self._extract_numeric_metrics(payload)
                    if fred_metrics:
                        source_health["fred"] = "ok"
                        used_sources.append("fred")
                    else:
                        source_health["fred"] = "empty"
                elif payload is None:
                    source_health["fred"] = "unavailable"
                else:
                    source_health["fred"] = "invalid_payload"
            else:
                source_health["fred"] = "unavailable"
        except Exception as exc:
            source_health["fred"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] FRED fetch failed: %s", exc)

        official_payload: Dict[str, Any] = {}
        official_releases: List[Dict[str, Any]] = []
        try:
            if hasattr(self.tools, "get_official_macro_releases"):
                kwargs = {"include_content": True} if employment_requested else {}
                payload = await asyncio.to_thread(
                    self.tools.get_official_macro_releases,
                    query=official_macro_query(query, requested),
                    max_results=8,
                    **kwargs,
                )
                if isinstance(payload, dict):
                    official_payload = payload
                    rows = payload.get("releases")
                    if isinstance(rows, list):
                        official_releases = [row for row in rows if isinstance(row, dict)]
                    if official_releases:
                        source_health["official_releases"] = "ok"
                        used_sources.append("official_releases")
                    else:
                        source_health["official_releases"] = "empty"
                else:
                    source_health["official_releases"] = "invalid_payload"
            else:
                source_health["official_releases"] = "unavailable"
        except Exception as exc:
            source_health["official_releases"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] Official release fetch failed: %s", exc)

        market_sentiment = ""
        try:
            if hasattr(self.tools, "get_market_sentiment"):
                market_sentiment, health = self._source_text(await asyncio.to_thread(self.tools.get_market_sentiment))
                if market_sentiment:
                    source_health["market_sentiment"] = "ok"
                    used_sources.append("market_sentiment")
                else:
                    source_health["market_sentiment"] = health
            else:
                source_health["market_sentiment"] = "unavailable"
        except Exception as exc:
            source_health["market_sentiment"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] Market sentiment fetch failed: %s", exc)

        economic_events = ""
        try:
            if hasattr(self.tools, "get_economic_events"):
                economic_events, health = self._source_text(await asyncio.to_thread(self.tools.get_economic_events))
                if economic_events:
                    source_health["economic_events"] = "discovery_only"
                    used_sources.append("economic_events")
                else:
                    source_health["economic_events"] = health
            else:
                source_health["economic_events"] = "unavailable"
        except Exception as exc:
            source_health["economic_events"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] Economic events fetch failed: %s", exc)

        cross_check_text = ""
        try:
            if hasattr(self.tools, "search"):
                cross_check_text, health = self._source_text(
                    await asyncio.to_thread(
                        self.tools.search,
                        "latest US CPI federal funds rate unemployment 10Y Treasury yield",
                    )
                )
                if cross_check_text:
                    source_health["search_cross_check"] = "discovery_only"
                    used_sources.append("search_cross_check")
                else:
                    source_health["search_cross_check"] = health
            else:
                source_health["search_cross_check"] = "unavailable"
        except Exception as exc:
            source_health["search_cross_check"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] Search cross-check failed: %s", exc)

        official_metrics = {}
        official_metadata = {}
        for release in official_releases:
            report = release.get("employment_report") if release.get("content_read") is True else None
            if not isinstance(report, dict) or not report.get("report_month"):
                continue
            if report.get("published_at"):
                published = datetime.fromisoformat(report["published_at"].replace("Z", "+00:00"))
                cutoff = datetime.now(timezone.utc)
                if requested_as_of:
                    cutoff = datetime.fromisoformat(requested_as_of.replace("Z", "+00:00"))
                    if len(requested_as_of) == 10:
                        cutoff = cutoff.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
                if cutoff.tzinfo is None or published > cutoff:
                    continue
            month = report["report_month"]
            point = datetime.strptime(month, "%Y-%m").date()
            for key in ("nonfarm_payroll_change", "unemployment"):
                if report.get(key) is None:
                    continue
                fred_month = (fred_payload.get("indicator_metadata") or {}).get(key, {}).get("report_month")
                if fred_month and fred_month != month:
                    continue
                official_metrics[key] = report[key]
                official_metadata[key] = {"subject": "US", "metric": key, "value": report[key],
                    "unit": "persons" if key == "nonfarm_payroll_change" else "percent", "frequency": "monthly",
                    "definition": "monthly_nonfarm_payroll_net_change" if key == "nonfarm_payroll_change" else "household_survey_unemployment_rate",
                    "report_month": month, "period_start": point.isoformat(),
                    "period_end": point.replace(day=monthrange(point.year, point.month)[1]).isoformat(),
                    "source_url": report.get("source_url"), "source": "BLS", "published_at": report.get("published_at"),
                    "timestamp_semantics": "publication", "content_read": True,
                    "source_time_status": "provided" if report.get("published_at") else "unknown"}
        merged = self._merge_indicator_sources(
            primary_source="fred",
            primary=fred_metrics,
            secondary_source="official_releases",
            # 未核验搜索文本没有发布期/指标口径，不构成正式读数或数据冲突。
            secondary=official_metrics,
            indicator_keys=active_keys,
        )

        if merged["coverage_count"] <= 0:
            status = "fallback" if cross_check_text or economic_events or official_releases or market_sentiment else "error"
        elif source_health.get("fred") == "ok":
            status = "success"
        elif official_metrics:
            status = "success"
        else:
            status = "fallback"

        payload: Dict[str, Any] = {
            "status": status,
            "source": "FRED" if source_health.get("fred") == "ok" else "BLS" if official_metrics else "search",
            "requested_indicators": requested,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "used_sources": sorted(set(used_sources), key=lambda s: self._SOURCE_PRIORITY.get(s, 999)),
            "source_health": source_health,
            "source_priority": sorted(self._SOURCE_PRIORITY, key=lambda s: self._SOURCE_PRIORITY[s]),
            "market_sentiment": market_sentiment,
            "economic_events": economic_events,
            "official_releases": official_releases[:8],
            "official_release_sources": official_payload.get("sources") if isinstance(official_payload, dict) else [],
            "cross_check_raw": cross_check_text[:2000] if cross_check_text else "",
            "indicators": merged["indicators"],
            "conflicts": merged["conflicts"],
            "merge": {
                "coverage_count": merged["coverage_count"],
                "indicator_total": len(active_keys),
                "conflict_count": len(merged["conflicts"]),
                "resolved_with_priority": True,
                "winner_source": "fred",
            },
        }

        # Keep flat fields for summary/backward compatibility.
        for key in active_keys:
            value = merged["selected"].get(key)
            payload[key] = value
            if value is not None:
                payload[f"{key}_formatted"] = f"{value:+,.0f} 人（月度净变动）" if key == "nonfarm_payroll_change" else self._format_percentage_value(value, digits=2 if key in ("fed_rate", "treasury_10y", "yield_spread") else 1)
                if key == "cpi":
                    payload[f"{key}_formatted"] += " (同比)"
        fact_metadata = fred_payload.get("indicator_metadata") or {}
        for indicator in payload["indicators"]:
            metadata = fact_metadata.get(indicator["key"], {}) if indicator.get("source") == "fred" else official_metadata.get(indicator["key"], {})
            if indicator["key"] in official_metadata and metadata.get("report_month") == official_metadata[indicator["key"]].get("report_month"):
                metadata = {**metadata, "published_at": official_metadata[indicator["key"]].get("published_at"),
                    "publication_source_url": official_metadata[indicator["key"]].get("source_url")}
                if metadata.get("published_at"):
                    metadata.update(timestamp_semantics="publication", source_time_status="provided")
            indicator.update({key: value for key, value in metadata.items() if key != "source"})
            indicator["period_end"] = metadata.get("period_end")
            indicator["definition"] = metadata.get("definition")
            indicator["transformation"] = metadata.get("transformation")
        if payload.get("yield_spread") is not None and float(payload["yield_spread"]) < 0:
            payload["recession_warning"] = True

        payload["evidence_quality"] = self._compute_evidence_quality(
            source_health=source_health,
            conflicts=merged["conflicts"],
            coverage_count=merged["coverage_count"],
            source_count=len(set(used_sources)),
            indicator_total=len(active_keys),
        )

        # Preserve original FRED metadata if useful.
        for key in ("fred_release", "fred_series", "fred_as_of"):
            if key in fred_payload:
                payload[key] = fred_payload.get(key)

        return payload

    async def _first_summary(self, data: Dict[str, Any]) -> str:
        return self._deterministic_summary(data)

    def _deterministic_summary(self, data: Dict[str, Any]) -> str:
        """确定性宏观快照（兜底文案，用户可见，B 类中文化）。"""
        status = str(data.get("status") or "").lower()
        if status == "error":
            return "无法从已配置的数据源获取宏观数据。"

        if status == "fallback":
            return "主要宏观指标不可用；兜底公告与检索线索需按来源核验，不能据此给出当前指标读数。"

        parts: List[str] = ["美国宏观快照："]
        if data.get("fed_rate_formatted"):
            parts.append(f"联邦基金利率 {data['fed_rate_formatted']}")
        if data.get("cpi_formatted"):
            parts.append(f"CPI {data['cpi_formatted']}")
        if data.get("unemployment_formatted"):
            parts.append(f"失业率 {data['unemployment_formatted']}")
        if data.get("nonfarm_payroll_change_formatted"):
            parts.append(f"新增非农 {data['nonfarm_payroll_change_formatted']}")
        for key in data.get("requested_indicators") or []:
            if key in {"nonfarm_payroll_change", "unemployment"} and data.get(key) is None:
                parts.append(f"[数据缺失] {'新增非农' if key == 'nonfarm_payroll_change' else '失业率'}尚未获取可核验数值")
        employment = [item for item in data.get("indicators", []) if item.get("key") in {"nonfarm_payroll_change", "unemployment"} and item.get("report_month")]
        if employment:
            parts.append(f"就业报告月份：{'、'.join(dict.fromkeys(item['report_month'] for item in employment))}")
            if len({item["report_month"] for item in employment}) > 1:
                parts.append("[数据缺失] 两项就业指标不属于同一报告月，未拼接成完整就业报告")
            if not all(item.get("published_at") for item in employment):
                parts.append("[数据缺失] BLS 原始发布时刻尚未核验，报告月份不代表发布时间")
        if data.get("gdp_growth_formatted"):
            parts.append(f"GDP 增速 {data['gdp_growth_formatted']}")
        if data.get("treasury_10y_formatted"):
            parts.append(f"10 年期美债 {data['treasury_10y_formatted']}")
        if data.get("yield_spread_formatted"):
            spread_line = f"10Y-2Y 利差 {data['yield_spread_formatted']}"
            if data.get("recession_warning"):
                spread_line += "（倒挂预警）"
            parts.append(spread_line)

        if data.get("market_sentiment"):
            parts.append(f"市场情绪：{str(data['market_sentiment'])[:120]}")

        official_releases = data.get("official_releases") if isinstance(data.get("official_releases"), list) else []
        if official_releases:
            parts.append(f"官方发布：{len(official_releases)} 条")

        conflicts = data.get("conflicts") or []
        if isinstance(conflicts, list) and conflicts:
            conflict_names = [str(item.get("indicator")) for item in conflicts if isinstance(item, dict)]
            parts.append(f"数据冲突：{'、'.join(conflict_names[:3])}")

        # 首段为标题，其余用顿号串接，保持中文标点
        if not parts:
            return ""
        head = parts[0]
        body = "；".join(part for part in parts[1:] if part)
        return f"{head}{body}。" if body else head

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence: List[EvidenceItem] = []
        data_sources: List[str] = []
        risks: List[str] = []
        fallback_used = False
        evidence_quality: Dict[str, Any] = {}
        source_health: Dict[str, str] = {}

        if isinstance(raw_data, dict):
            source_health = dict(raw_data.get("source_health") or {})
            source_name_map = {
                "fred": "FRED",
                "official_releases": "US Official Releases",
                "market_sentiment": "CNN Fear & Greed",
                "economic_events": "Economic Calendar",
                "search_cross_check": "Web Search",
            }
            used_sources = raw_data.get("used_sources") if isinstance(raw_data.get("used_sources"), list) else []
            data_sources = [source_name_map.get(str(src), str(src)) for src in used_sources]

            indicators = raw_data.get("indicators") if isinstance(raw_data.get("indicators"), list) else []
            for item in indicators:
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                if value is None:
                    continue
                name = item.get("name") or "宏观指标"
                source = item.get("source") or "unknown"
                discovery = source not in {"fred", "official_releases"}
                conflict = bool(item.get("conflict"))
                evidence.append(
                    EvidenceItem(
                        text=f"{name}: {float(value):+,.0f} 人（月度净变动）" if item.get("key") == "nonfarm_payroll_change" else f"{name}: {self._format_percentage_value(float(value), digits=2)}",
                        source=source_name_map.get(str(source), str(source)),
                        confidence=0.9 if source == "fred" else 0.6,
                        url=item.get("source_url"),
                        meta={
                            **{key: item[key] for key in ("subject", "metric", "report_month", "period_start", "frequency", "published_at",
                                "source_updated_at", "timestamp_semantics", "source_time_status", "source_url", "publication_source_url", "derivation_inputs", "formula") if key in item},
                            "value": value,
                            "structured_data": dict(item),
                            "indicator_key": item.get("key"),
                            "conflict_flag": conflict,
                            "candidates": item.get("candidates") if isinstance(item.get("candidates"), list) else [],
                            "unit": item.get("unit"),
                            "definition": item.get("definition"),
                            "period_end": item.get("period_end"),
                            "transformation": item.get("transformation"),
                            "usage": "raw" if discovery else "fact",
                            "verification": "discovery_only" if discovery else "provider_reported",
                        },
                        timestamp=(item.get("published_at") or item.get("source_updated_at")) if item.get("report_month") else item.get("period_end"),
                    )
                )

            sentiment, sentiment_health = self._source_text(raw_data.get("market_sentiment"))
            if sentiment_health.startswith("failed"):
                source_health["market_sentiment"] = sentiment_health
            if sentiment:
                evidence.append(
                    EvidenceItem(
                        text=f"市场情绪监测: {sentiment[:240]}",
                        source="CNN Fear & Greed",
                        confidence=0.65,
                        meta={"usage": "raw", "verification": "discovery_only"} if "via search" in sentiment.lower() else {"usage": "fact", "verification": "provider_reported"},
                    )
                )

            events, events_health = self._source_text(raw_data.get("economic_events"))
            if events_health.startswith("failed"):
                source_health["economic_events"] = events_health
            if events:
                evidence.append(
                    EvidenceItem(
                        text=f"宏观日程检索线索（待核实）: {events[:240]}",
                        source="Economic Calendar",
                        confidence=0.60,
                        meta={"usage": "raw", "verification": "discovery_only", "evidence_kind": "macro_context"},
                    )
                )

            cross_check, cross_check_health = self._source_text(raw_data.get("cross_check_raw"))
            if cross_check_health.startswith("failed"):
                source_health["search_cross_check"] = cross_check_health
            if cross_check:
                evidence.append(EvidenceItem(
                    text=f"宏观检索线索（待核实）: {cross_check[:2000]}",
                    source="Web Search", confidence=0.4,
                    meta={"usage": "raw", "verification": "discovery_only", "evidence_kind": "macro_context"},
                ))

            official_releases = raw_data.get("official_releases") if isinstance(raw_data.get("official_releases"), list) else []
            for item in official_releases[:5]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                snippet = str(item.get("snippet") or "").strip()
                url = str(item.get("url") or "").strip()
                source_label = str(item.get("source") or "Official Release").strip()
                if not (title or snippet):
                    continue
                evidence.append(
                    EvidenceItem(
                        text=f"{title or 'Official release'}: {(snippet or title)[:220]}",
                        source=source_label,
                        url=url if url else None,  # BUG FIX: pass real URL to evidence pool
                        confidence=0.88,
                        meta={
                            "url": url,
                            "published_date": item.get("published_date"),
                            "domain": item.get("domain"),
                            "doc_type": "official_release",
                            "usage": "raw" if item.get("content_read") is False else "fact",
                            "verification": "discovery_only" if item.get("content_read") is False else "official_body_read" if item.get("content_read") else "provider_reported",
                            "content_read": item.get("content_read"),
                            "structured_data": item.get("structured_data"),
                        },
                        timestamp=item.get("published_date"),
                    )
                )
            evidence_quality = dict(raw_data.get("evidence_quality") or {})
            evidence_quality["source_health"] = source_health
            fallback_used = str(raw_data.get("status") or "").lower() in {"fallback", "error"}
            conflicts = raw_data.get("conflicts") if isinstance(raw_data.get("conflicts"), list) else []
            if conflicts:
                risks.append("多个数据源之间存在宏观信号冲突。")
            if raw_data.get("recession_warning"):
                risks.append("收益率曲线倒挂预警仍处于高位。")
            if fallback_used:
                risks.append("主要宏观数据源不可用，正在使用兜底信号。")
                fallback_reason = str(raw_data.get("fallback_detail") or raw_data.get("status") or "primary_source_unavailable")
            else:
                fallback_reason = None

            # --- Conflict tracking: convert raw conflicts -> ConflictClaim ---
            conflict_flags: List[str] = []
            conflicting_claims: List[ConflictClaim] = []
            source_name_map_for_conflict = {
                "fred": "FRED",
                "official_releases": "US Official Releases",
                "market_sentiment": "CNN Fear & Greed",
                "economic_events": "Economic Calendar",
                "search_cross_check": "Web Search",
            }
            for conflict_item in conflicts:
                if not isinstance(conflict_item, dict):
                    continue
                indicator_key = str(conflict_item.get("indicator", "unknown"))
                indicator_label = self._INDICATORS.get(indicator_key, {}).get("label", indicator_key)
                delta = conflict_item.get("delta", 0)
                threshold = conflict_item.get("threshold", 0.5)
                severity = "high" if delta > threshold * 2 else ("medium" if delta > threshold else "low")
                chosen_src = str(conflict_item.get("chosen_source", ""))
                other_src = str(conflict_item.get("other_source", ""))
                conflict_flags.append(f"{indicator_label}({chosen_src} vs {other_src}, Δ={delta:.2f})")
                conflicting_claims.append(ConflictClaim(
                    claim=indicator_label,
                    source_a=source_name_map_for_conflict.get(chosen_src, chosen_src),
                    value_a=f"{conflict_item.get('chosen_value', 'N/A')}",
                    source_b=source_name_map_for_conflict.get(other_src, other_src),
                    value_b=f"{conflict_item.get('other_value', 'N/A')}",
                    severity=severity,
                    resolved=True,
                    resolution=f"采信优先级更高的 {source_name_map_for_conflict.get(chosen_src, chosen_src)} 数据",
                ))
        else:
            fallback_reason = None
            conflict_flags = []
            conflicting_claims = []

        data_sources = [source for source in data_sources if source not in {
            source_name_map.get(key, key) for key, health in source_health.items() if health.startswith("failed")
        }] if isinstance(raw_data, dict) else data_sources
        if not data_sources:
            data_sources = sorted({item.source for item in evidence})
        if not risks:
            risks = ["Policy transmission lag risk", "Macro data revision risk"]

        overall_quality = evidence_quality.get("overall_score") if isinstance(evidence_quality, dict) else None
        try:
            confidence = float(overall_quality) if overall_quality is not None else self._MISSING_QUALITY_CONFIDENCE
        except (TypeError, ValueError):
            confidence = self._MISSING_QUALITY_CONFIDENCE
        if overall_quality is None:
            # P0-2: 质量分缺失时压低置信度并在风险中明示
            risks = list(risks or [])
            risks.append("宏观数据质量未评估（评分缺失），本节置信度已下调")
        confidence = max(0.2, min(0.95, confidence))
        if fallback_used:
            confidence = min(confidence, 0.6)

        # P2-8：宏观指标横截面柱状图（各指标当前读数），无有效数值时返回 []
        chart_payload = {**raw_data, "indicators": [item for item in raw_data.get("indicators", [])
                         if isinstance(item, dict) and item.get("source") in {"fred", "official_releases"}
                         and item.get("key") != "nonfarm_payroll_change"]} if isinstance(raw_data, dict) else {}
        chart_specs = build_macro_chart_specs(chart_payload)

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=sorted(set(data_sources)),
            as_of=datetime.now(timezone.utc).isoformat(),
            chart_specs=chart_specs,
            evidence_quality=evidence_quality,
            fallback_used=fallback_used,
            risks=risks,
            trace=[],
            conflict_flags=conflict_flags,
            conflicting_claims=conflicting_claims,
            fallback_reason=fallback_reason,
            retryable=not fallback_used,
        )

    def _extract_numeric_metrics(self, payload: Dict[str, Any]) -> Dict[str, float]:
        values: Dict[str, float] = {}
        for key in {**self._INDICATORS, **self._EMPLOYMENT_INDICATORS}:
            if key == "cpi":
                metadata = (payload.get("indicator_metadata") or {}).get("cpi", {})
                if metadata.get("unit") != "percent" or metadata.get("definition") != "inflation_yoy":
                    continue
            if key == "nonfarm_payroll_change":
                metadata = (payload.get("indicator_metadata") or {}).get(key, {})
                if metadata.get("unit") != "persons" or metadata.get("definition") != "monthly_nonfarm_payroll_net_change":
                    continue
            value = payload.get(key)
            try:
                if value is not None:
                    values[key] = float(value)
            except (TypeError, ValueError):
                continue
        return values

    def _extract_numeric_metrics_from_text(self, text: str) -> Dict[str, float]:
        if not text:
            return {}
        metrics: Dict[str, float] = {}
        patterns: Dict[str, List[str]] = {
            "fed_rate": [
                r"(?:federal funds(?: rate)?|fed funds(?: rate)?)\D{0,25}(-?\d{1,2}(?:\.\d+)?)\s*%",
            ],
            "cpi": [
                r"(?:cpi|inflation(?: rate)?|通胀)\D{0,20}(?:yoy|year[- ]over[- ]year|同比|annual)\D{0,12}(-?\d{1,2}(?:\.\d+)?)\s*%",
                r"(?:cpi|inflation(?: rate)?|通胀)\D{0,20}(-?\d{1,2}(?:\.\d+)?)\s*%\s*(?:yoy|year[- ]over[- ]year|同比)",
            ],
            "unemployment": [
                r"(?:unemployment(?: rate)?)\D{0,25}(-?\d{1,2}(?:\.\d+)?)\s*%",
            ],
            "gdp_growth": [
                r"(?:gdp(?: growth)?|real gdp)\D{0,30}(-?\d{1,2}(?:\.\d+)?)\s*%",
            ],
            "treasury_10y": [
                r"(?:10[- ]?year(?: treasury)?(?: yield| rate)?|10y(?: treasury)?)\D{0,25}(-?\d{1,2}(?:\.\d+)?)\s*%",
            ],
            "yield_spread": [
                r"(?:10y[- ]?2y(?: spread)?|yield spread|10[- ]?2 spread)\D{0,25}(-?\d{1,2}(?:\.\d+)?)\s*%",
            ],
        }
        lowered = text.lower()
        for key, regex_list in patterns.items():
            for pattern in regex_list:
                match = re.search(pattern, lowered, flags=re.IGNORECASE)
                if not match:
                    continue
                try:
                    metrics[key] = float(match.group(1))
                    break
                except (TypeError, ValueError):
                    continue
        return metrics

    def _merge_indicator_sources(
        self,
        *,
        primary_source: str,
        primary: Dict[str, float],
        secondary_source: str,
        secondary: Dict[str, float],
        indicator_keys: list[str] | None = None,
    ) -> Dict[str, Any]:
        selected: Dict[str, Optional[float]] = {}
        indicators: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []

        configs = {**self._INDICATORS, **self._EMPLOYMENT_INDICATORS}
        for key in indicator_keys if indicator_keys is not None else self._INDICATORS:
            config = configs.get(key)
            if config is None:
                continue
            candidates: List[Dict[str, Any]] = []
            if key in primary:
                candidates.append(
                    {
                        "source": primary_source,
                        "value": float(primary[key]),
                        "priority": self._SOURCE_PRIORITY.get(primary_source, 999),
                    }
                )
            if key in secondary:
                candidates.append(
                    {
                        "source": secondary_source,
                        "value": float(secondary[key]),
                        "priority": self._SOURCE_PRIORITY.get(secondary_source, 999),
                    }
                )

            candidates.sort(key=lambda item: (item["priority"], item["source"]))
            chosen = candidates[0] if candidates else None
            selected[key] = float(chosen["value"]) if chosen else None

            conflict = False
            if len(candidates) >= 2:
                top = float(candidates[0]["value"])
                alt = float(candidates[1]["value"])
                delta = abs(top - alt)
                threshold = self._CONFLICT_TOLERANCE.get(key, 0.5)
                if delta > threshold:
                    conflict = True
                    conflicts.append(
                        {
                            "indicator": key,
                            "delta": round(delta, 4),
                            "threshold": threshold,
                            "chosen_source": candidates[0]["source"],
                            "chosen_value": top,
                            "other_source": candidates[1]["source"],
                            "other_value": alt,
                        }
                    )

            indicators.append(
                {
                    "key": key,
                    "name": config["label"],
                    "value": selected[key],
                    "unit": config["unit"],
                    "source": chosen["source"] if chosen else None,
                    "conflict": conflict,
                    "candidates": [
                        {
                            "source": item["source"],
                            "value": item["value"],
                            "priority": item["priority"],
                        }
                        for item in candidates
                    ],
                }
            )

        coverage_count = sum(1 for value in selected.values() if value is not None)
        return {
            "selected": selected,
            "indicators": indicators,
            "conflicts": conflicts,
            "coverage_count": coverage_count,
        }

    def _compute_evidence_quality(
        self,
        *,
        source_health: Dict[str, str],
        conflicts: List[Dict[str, Any]],
        coverage_count: int,
        source_count: int,
        indicator_total: int | None = None,
    ) -> Dict[str, Any]:
        coverage_score = min(1.0, coverage_count / max(1, indicator_total if indicator_total is not None else len(self._INDICATORS)))
        diversity_score = min(1.0, source_count / 4.0)
        source_ok_count = sum(1 for value in source_health.values() if str(value).startswith("ok"))
        source_health_score = min(1.0, source_ok_count / max(1, len(source_health)))
        conflict_penalty = min(0.35, 0.12 * len(conflicts))
        overall = coverage_score * 0.45 + diversity_score * 0.20 + source_health_score * 0.35 - conflict_penalty
        overall = max(0.0, min(1.0, overall))
        return {
            "overall_score": round(overall, 4),
            "coverage_score": round(coverage_score, 4),
            "source_diversity": source_count,
            "source_health_score": round(source_health_score, 4),
            "has_conflicts": bool(conflicts),
            "conflict_count": len(conflicts),
        }

    def _format_percentage_value(self, value: float, *, digits: int = 2) -> str:
        return f"{value:.{digits}f}%"
