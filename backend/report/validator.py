# -*- coding: utf-8 -*-
"""
Report Validator - 研报结构校验器
确保 Agent 生成的数据符合 ReportIR 标准，防止前端渲染崩溃。
"""

import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from backend.report.ir import ReportIR, ReportSection, ReportContent, Citation, ContentType, Sentiment
from backend.report.evidence_policy import (
    EvidencePolicy,
    extract_report_quality,
    merge_quality_states,
    normalize_quality_state,
)
from backend.report.quality_engine import merge_report_quality_payload

logger = logging.getLogger(__name__)


class ReportValidator:
    """
    研报校验器
    """

    @staticmethod
    def validate_and_fix(data: Dict[str, Any], as_dict: bool = True) -> Union[ReportIR, Dict[str, Any]]:
        """
        校验字典数据并转换为 ReportIR 对象或字典。
        如果字段缺失，尝试填充默认值；如果结构严重错误，返回最小可用结构。
        """
        incoming_quality = extract_report_quality(data if isinstance(data, dict) else {})
        report = ReportValidator._build_report(data)
        EvidencePolicy.apply(report)
        ReportValidator._merge_report_quality(report, incoming_quality)

        if not as_dict:
            return report

        report_dict = report.to_dict()
        if isinstance(report_dict, dict):
            meta = report_dict.get("meta")
            if isinstance(meta, dict):
                quality = meta.get("report_quality")
                if isinstance(quality, dict):
                    report_dict["report_quality"] = quality
        return report_dict

    @staticmethod
    def _merge_report_quality(report: ReportIR, incoming_quality: Dict[str, Any]) -> None:
        if not isinstance(report.meta, dict):
            report.meta = {}

        policy_quality = report.meta.get("report_quality")
        if not isinstance(policy_quality, dict):
            policy_quality = {"state": "pass", "reasons": []}

        merged_payload = merge_report_quality_payload(
            existing_quality=policy_quality,
            reason_groups=[
                incoming_quality.get("reasons") if isinstance(incoming_quality, dict) else [],
            ],
        )
        merged_payload["state"] = merge_quality_states(
            merged_payload.get("state"),
            normalize_quality_state((incoming_quality or {}).get("state")),
        )
        report.meta["report_quality"] = merged_payload

    @staticmethod
    def _build_report(data: Dict[str, Any]) -> ReportIR:
        try:
            # 1. 基础字段校验
            report_id = str(data.get("report_id", f"rpt_{int(datetime.now().timestamp())}"))
            ticker = str(data.get("ticker", "UNKNOWN"))
            company_name = str(data.get("company_name", ticker))
            title = str(data.get("title", f"{company_name} Analysis"))
            summary = str(data.get("summary", "No summary provided."))
            generated_at = str(data.get("generated_at", datetime.now().isoformat()))

            # 2. 枚举校验
            sentiment_str = str(data.get("sentiment", "neutral")).lower()
            try:
                sentiment = Sentiment(sentiment_str)
            except ValueError:
                sentiment = Sentiment.NEUTRAL

            # 3. 数值校验
            try:
                confidence_score = float(data.get("confidence_score", 0.5))
                confidence_score = max(0.0, min(1.0, confidence_score))
            except (ValueError, TypeError):
                confidence_score = 0.5

            # 4. 引用校验 (Citations)
            raw_citations = data.get("citations", [])
            citations = []
            if isinstance(raw_citations, list):
                for idx, c in enumerate(raw_citations):
                    if isinstance(c, dict):
                        published_date = str(c.get("published_date", ""))
                        confidence = c.get("confidence", 0.7)
                        try:
                            confidence = float(confidence)
                        except (TypeError, ValueError):
                            confidence = 0.7
                        confidence = max(0.0, min(1.0, confidence))

                        freshness_hours = c.get("freshness_hours")
                        if freshness_hours is None:
                            freshness_hours = 24.0
                            if published_date:
                                try:
                                    pub_dt = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
                                    now = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
                                    delta = now - pub_dt
                                    freshness_hours = max(0.0, delta.total_seconds() / 3600)
                                except Exception:
                                    pass
                        else:
                            try:
                                freshness_hours = float(freshness_hours)
                                freshness_hours = max(0.0, freshness_hours)
                            except (TypeError, ValueError):
                                freshness_hours = 24.0

                        citations.append(Citation(
                            source_id=str(c.get("source_id", str(idx + 1))),
                            title=str(c.get("title", "Unknown Source")),
                            url=str(c.get("url", "#")),
                            snippet=str(c.get("snippet", "")),
                            published_date=published_date,
                            confidence=confidence,
                            freshness_hours=freshness_hours,
                        ))

            # 5. 章节校验 (Sections)
            raw_sections = data.get("sections", [])
            sections = []
            if isinstance(raw_sections, list):
                for idx, s in enumerate(raw_sections):
                    if isinstance(s, dict):
                        sections.append(ReportValidator._parse_section(s, idx))

            if not sections:
                sections = [
                    ReportSection(
                        title="Summary",
                        order=1,
                        contents=[ReportContent(type=ContentType.TEXT, content=summary)],
                    )
                ]

            risks_raw = data.get("risks", [])
            risks = [str(r) for r in risks_raw] if isinstance(risks_raw, list) else []
            recommendation = data.get("recommendation")
            if recommendation is not None:
                recommendation = str(recommendation)

            meta = data.get("meta", {})
            if not isinstance(meta, dict):
                meta = {}

            return ReportIR(
                report_id=report_id,
                ticker=ticker,
                company_name=company_name,
                title=title,
                summary=summary,
                sentiment=sentiment,
                confidence_score=confidence_score,
                sections=sections,
                citations=citations,
                risks=risks,
                recommendation=recommendation,
                generated_at=generated_at,
                meta=meta,
            )

        except Exception as e:
            logger.info(f"[ReportValidator] Validation failed: {e}")
            return ReportIR(
                report_id="error",
                ticker="ERROR",
                company_name="Error",
                title="Report Generation Failed",
                summary=f"Data validation failed: {str(e)}",
                sentiment=Sentiment.NEUTRAL,
                confidence_score=0.0,
                sections=[],
                citations=[],
                risks=[],
                recommendation=None,
                generated_at=datetime.now().isoformat(),
                meta={},
            )

    @staticmethod
    def _parse_section(data: Dict[str, Any], default_order: int) -> ReportSection:
        """递归解析章节"""
        title = str(data.get("title", "Untitled Section"))
        try:
            order = int(data.get("order", default_order))
        except (TypeError, ValueError):
            order = default_order
        confidence = data.get("confidence", None)
        if confidence is not None:
            try:
                confidence = float(confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = None
        agent_name = data.get("agent_name")
        if agent_name is not None:
            agent_name = str(agent_name)
        data_sources = data.get("data_sources", [])
        if not isinstance(data_sources, list):
            data_sources = []

        # 解析内容块
        raw_contents = data.get("contents", [])
        contents = []
        if isinstance(raw_contents, list):
            for c in raw_contents:
                if isinstance(c, dict):
                    type_str = c.get("type", "text")
                    try:
                        content_type = ContentType(type_str)
                    except ValueError:
                        content_type = ContentType.TEXT

                    contents.append(ReportContent(
                        type=content_type,
                        content=c.get("content", ""),
                        citation_refs=c.get("citation_refs", []) if isinstance(c.get("citation_refs"), list) else [],
                        metadata=c.get("metadata", {}) if isinstance(c.get("metadata"), dict) else {},
                    ))
        if not contents:
            contents = [ReportContent(type=ContentType.TEXT, content="")]

        # 递归解析子章节
        raw_subsections = data.get("subsections", [])
        subsections = []
        if isinstance(raw_subsections, list):
            for idx, sub in enumerate(raw_subsections):
                if isinstance(sub, dict):
                    subsections.append(ReportValidator._parse_section(sub, idx))

        return ReportSection(
            title=title,
            order=order,
            contents=contents,
            subsections=subsections,
            is_collapsible=data.get("is_collapsible", True),
            default_collapsed=data.get("default_collapsed", False),
            confidence=confidence,
            agent_name=agent_name,
            data_sources=data_sources,
        )
