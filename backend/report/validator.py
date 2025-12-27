# -*- coding: utf-8 -*-
"""
Report Validator - 研报结构校验器
确保 Agent 生成的数据符合 ReportIR 标准，防止前端渲染崩溃。
"""

from typing import Dict, Any, List, Optional
from backend.report.ir import ReportIR, ReportSection, ReportContent, Citation, ContentType, Sentiment

class ReportValidator:
    """
    研报校验器
    """

    @staticmethod
    def validate_and_fix(data: Dict[str, Any]) -> ReportIR:
        """
        校验字典数据并转换为 ReportIR 对象。
        如果字段缺失，尝试填充默认值；如果结构严重错误，抛出异常。
        """
        try:
            # 1. 基础字段校验
            report_id = str(data.get("report_id", "unknown"))
            ticker = str(data.get("ticker", "UNKNOWN"))
            company_name = str(data.get("company_name", ticker))
            title = str(data.get("title", f"{company_name} Analysis"))
            summary = str(data.get("summary", "No summary provided."))

            # 2. 枚举校验
            sentiment_str = data.get("sentiment", "neutral").lower()
            try:
                sentiment = Sentiment(sentiment_str)
            except ValueError:
                sentiment = Sentiment.NEUTRAL

            # 3. 数值校验
            try:
                confidence_score = float(data.get("confidence_score", 0.5))
                confidence_score = max(0.0, min(1.0, confidence_score)) # Clamp 0-1
            except (ValueError, TypeError):
                confidence_score = 0.5

            # 4. 引用校验 (Citations)
            raw_citations = data.get("citations", [])
            citations = []
            if isinstance(raw_citations, list):
                for idx, c in enumerate(raw_citations):
                    if isinstance(c, dict):
                        citations.append(Citation(
                            source_id=str(c.get("source_id", str(idx + 1))),
                            title=str(c.get("title", "Unknown Source")),
                            url=str(c.get("url", "#")),
                            snippet=str(c.get("snippet", "")),
                            published_date=str(c.get("published_date", ""))
                        ))

            # 5. 章节校验 (Sections)
            raw_sections = data.get("sections", [])
            sections = []
            if isinstance(raw_sections, list):
                for idx, s in enumerate(raw_sections):
                    if isinstance(s, dict):
                        sections.append(ReportValidator._parse_section(s, idx))

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
                meta=data.get("meta", {})
            )

        except Exception as e:
            print(f"[ReportValidator] Validation failed: {e}")
            # 返回一个最小可用对象，避免 crash
            return ReportIR(
                report_id="error",
                ticker="ERROR",
                company_name="Error",
                title="Report Generation Failed",
                summary=f"Data validation failed: {str(e)}",
                sentiment=Sentiment.NEUTRAL,
                confidence_score=0.0,
                sections=[],
                citations=[]
            )

    @staticmethod
    def _parse_section(data: Dict[str, Any], default_order: int) -> ReportSection:
        """递归解析章节"""
        title = str(data.get("title", "Untitled Section"))
        order = data.get("order", default_order)

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
                        citation_refs=c.get("citation_refs", []),
                        metadata=c.get("metadata", {})
                    ))

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
            default_collapsed=data.get("default_collapsed", False)
        )
