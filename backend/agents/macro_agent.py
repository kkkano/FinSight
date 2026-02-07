from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.agents.base_agent import AgentOutput, BaseFinancialAgent, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class MacroAgent(BaseFinancialAgent):
    """
    Macro agent:
    - Prioritize primary macro data source (FRED)
    - Add secondary external sources (sentiment, calendar, search cross-check)
    - Merge with explicit source-priority and conflict handling
    """

    AGENT_NAME = "macro"

    _INDICATORS: Dict[str, Dict[str, str]] = {
        "fed_rate": {"label": "Federal Funds Rate", "unit": "%"},
        "cpi": {"label": "CPI", "unit": "%"},
        "unemployment": {"label": "Unemployment Rate", "unit": "%"},
        "gdp_growth": {"label": "GDP Growth", "unit": "%"},
        "treasury_10y": {"label": "10Y Treasury Yield", "unit": "%"},
        "yield_spread": {"label": "10Y-2Y Spread", "unit": "%"},
    }

    _SOURCE_PRIORITY = {
        "fred": 1,
        "market_sentiment": 2,
        "economic_events": 3,
        "search_cross_check": 4,
    }

    _CONFLICT_TOLERANCE = {
        "fed_rate": 0.35,
        "cpi": 0.60,
        "unemployment": 0.40,
        "gdp_growth": 0.80,
        "treasury_10y": 0.35,
        "yield_spread": 0.35,
    }

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    async def _initial_search(self, query: str, ticker: str) -> Dict[str, Any]:
        source_health: Dict[str, str] = {}
        used_sources: List[str] = []

        fred_metrics: Dict[str, float] = {}
        fred_payload: Dict[str, Any] = {}
        try:
            if hasattr(self.tools, "get_fred_data"):
                payload = self.tools.get_fred_data()
                if isinstance(payload, dict):
                    fred_payload = payload
                    fred_metrics = self._extract_numeric_metrics(payload)
                    if fred_metrics:
                        source_health["fred"] = "ok"
                        used_sources.append("fred")
                    else:
                        source_health["fred"] = "empty"
                else:
                    source_health["fred"] = "invalid_payload"
            else:
                source_health["fred"] = "unavailable"
        except Exception as exc:
            source_health["fred"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] FRED fetch failed: %s", exc)

        market_sentiment = ""
        try:
            if hasattr(self.tools, "get_market_sentiment"):
                market_sentiment = str(self.tools.get_market_sentiment() or "").strip()
                if market_sentiment:
                    source_health["market_sentiment"] = "ok"
                    used_sources.append("market_sentiment")
                else:
                    source_health["market_sentiment"] = "empty"
            else:
                source_health["market_sentiment"] = "unavailable"
        except Exception as exc:
            source_health["market_sentiment"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] Market sentiment fetch failed: %s", exc)

        economic_events = ""
        try:
            if hasattr(self.tools, "get_economic_events"):
                economic_events = str(self.tools.get_economic_events() or "").strip()
                if economic_events:
                    source_health["economic_events"] = "ok"
                    used_sources.append("economic_events")
                else:
                    source_health["economic_events"] = "empty"
            else:
                source_health["economic_events"] = "unavailable"
        except Exception as exc:
            source_health["economic_events"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] Economic events fetch failed: %s", exc)

        cross_check_text = ""
        cross_check_metrics: Dict[str, float] = {}
        try:
            if hasattr(self.tools, "search"):
                cross_check_text = str(
                    self.tools.search("latest US CPI federal funds rate unemployment 10Y Treasury yield")
                    or ""
                )
                cross_check_metrics = self._extract_numeric_metrics_from_text(cross_check_text)
                if cross_check_text:
                    source_health["search_cross_check"] = "ok"
                    used_sources.append("search_cross_check")
                else:
                    source_health["search_cross_check"] = "empty"
        except Exception as exc:
            source_health["search_cross_check"] = f"failed:{exc.__class__.__name__}"
            logger.info("[MacroAgent] Search cross-check failed: %s", exc)

        merged = self._merge_indicator_sources(
            primary_source="fred",
            primary=fred_metrics,
            secondary_source="search_cross_check",
            secondary=cross_check_metrics,
        )

        if merged["coverage_count"] <= 0:
            status = "fallback" if cross_check_text else "error"
        elif source_health.get("fred") == "ok":
            status = "success"
        else:
            status = "fallback"

        payload: Dict[str, Any] = {
            "status": status,
            "source": "FRED" if source_health.get("fred") == "ok" else "search",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "used_sources": sorted(set(used_sources), key=lambda s: self._SOURCE_PRIORITY.get(s, 999)),
            "source_health": source_health,
            "source_priority": sorted(self._SOURCE_PRIORITY, key=lambda s: self._SOURCE_PRIORITY[s]),
            "market_sentiment": market_sentiment,
            "economic_events": economic_events,
            "cross_check_raw": cross_check_text[:2000] if cross_check_text else "",
            "indicators": merged["indicators"],
            "conflicts": merged["conflicts"],
            "merge": {
                "coverage_count": merged["coverage_count"],
                "indicator_total": len(self._INDICATORS),
                "conflict_count": len(merged["conflicts"]),
                "resolved_with_priority": True,
                "winner_source": "fred",
            },
        }

        # Keep flat fields for summary/backward compatibility.
        for key in self._INDICATORS:
            value = merged["selected"].get(key)
            payload[key] = value
            if value is not None:
                payload[f"{key}_formatted"] = self._format_percentage_value(value, digits=2 if key in ("fed_rate", "treasury_10y", "yield_spread") else 1)
        if payload.get("yield_spread") is not None and float(payload["yield_spread"]) < 0:
            payload["recession_warning"] = True

        payload["evidence_quality"] = self._compute_evidence_quality(
            source_health=source_health,
            conflicts=merged["conflicts"],
            coverage_count=merged["coverage_count"],
            source_count=len(set(used_sources)),
        )

        # Preserve original FRED metadata if useful.
        for key in ("fred_release", "fred_series", "fred_as_of"):
            if key in fred_payload:
                payload[key] = fred_payload.get(key)

        return payload

    async def _first_summary(self, data: Dict[str, Any]) -> str:
        status = str(data.get("status") or "").lower()
        if status == "error":
            return "Unable to fetch macro data from configured sources."

        if status == "fallback":
            names = [
                item.get("name")
                for item in data.get("indicators", [])
                if isinstance(item, dict) and item.get("name")
            ]
            summary = "Primary macro source unavailable. Using search fallback."
            if names:
                summary += " Indicators: " + ", ".join(names[:6]) + "."
            return summary

        parts: List[str] = ["US macro snapshot:"]
        if data.get("fed_rate_formatted"):
            parts.append(f"Fed funds {data['fed_rate_formatted']}")
        if data.get("cpi_formatted"):
            parts.append(f"CPI {data['cpi_formatted']}")
        if data.get("unemployment_formatted"):
            parts.append(f"Unemployment {data['unemployment_formatted']}")
        if data.get("gdp_growth_formatted"):
            parts.append(f"GDP growth {data['gdp_growth_formatted']}")
        if data.get("treasury_10y_formatted"):
            parts.append(f"10Y yield {data['treasury_10y_formatted']}")
        if data.get("yield_spread_formatted"):
            spread_line = f"10Y-2Y spread {data['yield_spread_formatted']}"
            if data.get("recession_warning"):
                spread_line += " (inversion warning)"
            parts.append(spread_line)

        if data.get("market_sentiment"):
            parts.append(f"Sentiment: {str(data['market_sentiment'])[:120]}")

        conflicts = data.get("conflicts") or []
        if isinstance(conflicts, list) and conflicts:
            conflict_names = [str(item.get("indicator")) for item in conflicts if isinstance(item, dict)]
            parts.append(f"Cross-source conflicts: {', '.join(conflict_names[:3])}")

        return ". ".join(p for p in parts if p).strip() + "."

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence: List[EvidenceItem] = []
        data_sources: List[str] = []
        risks: List[str] = []
        fallback_used = False
        evidence_quality: Dict[str, Any] = {}

        if isinstance(raw_data, dict):
            source_name_map = {
                "fred": "FRED",
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
                name = item.get("name") or "Macro Indicator"
                source = item.get("source") or "unknown"
                conflict = bool(item.get("conflict"))
                evidence.append(
                    EvidenceItem(
                        text=f"{name}: {self._format_percentage_value(float(value), digits=2)}",
                        source=source_name_map.get(str(source), str(source)),
                        confidence=0.9 if source == "fred" else 0.6,
                        meta={
                            "indicator_key": item.get("key"),
                            "conflict_flag": conflict,
                            "candidates": item.get("candidates") if isinstance(item.get("candidates"), list) else [],
                        },
                    )
                )

            sentiment = str(raw_data.get("market_sentiment") or "").strip()
            if sentiment:
                evidence.append(
                    EvidenceItem(
                        text=f"Sentiment monitor: {sentiment[:240]}",
                        source="CNN Fear & Greed",
                        confidence=0.65,
                    )
                )

            events = str(raw_data.get("economic_events") or "").strip()
            if events:
                evidence.append(
                    EvidenceItem(
                        text=f"Economic calendar: {events[:240]}",
                        source="Economic Calendar",
                        confidence=0.60,
                    )
                )

            evidence_quality = raw_data.get("evidence_quality") if isinstance(raw_data.get("evidence_quality"), dict) else {}
            fallback_used = str(raw_data.get("status") or "").lower() in {"fallback", "error"}
            conflicts = raw_data.get("conflicts") if isinstance(raw_data.get("conflicts"), list) else []
            if conflicts:
                risks.append("Cross-source macro conflicts detected; verify against primary releases.")
            if raw_data.get("recession_warning"):
                risks.append("Yield curve inversion indicates elevated recession risk.")
            if fallback_used:
                risks.append("Primary macro feed degraded; result relies on fallback signals.")

        if not data_sources:
            data_sources = ["FRED"]
        if not risks:
            risks = ["Policy lag risk", "Macro release revision risk"]

        overall_quality = evidence_quality.get("overall_score") if isinstance(evidence_quality, dict) else None
        try:
            confidence = float(overall_quality) if overall_quality is not None else 0.6
        except (TypeError, ValueError):
            confidence = 0.6
        confidence = max(0.2, min(0.95, confidence))
        if fallback_used:
            confidence = min(confidence, 0.6)

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=confidence,
            data_sources=sorted(set(data_sources)),
            as_of=datetime.now(timezone.utc).isoformat(),
            evidence_quality=evidence_quality,
            fallback_used=fallback_used,
            risks=risks,
            trace=[],
        )

    def _extract_numeric_metrics(self, payload: Dict[str, Any]) -> Dict[str, float]:
        values: Dict[str, float] = {}
        for key in self._INDICATORS:
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
                r"(?:cpi|inflation(?: rate)?)\D{0,25}(-?\d{1,2}(?:\.\d+)?)\s*%",
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
    ) -> Dict[str, Any]:
        selected: Dict[str, Optional[float]] = {}
        indicators: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []

        for key, config in self._INDICATORS.items():
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
    ) -> Dict[str, Any]:
        coverage_score = min(1.0, coverage_count / max(1, len(self._INDICATORS)))
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
