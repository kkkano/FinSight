# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/synthesize.py（WP3 Task4，零行为变更）。
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RenderVars(BaseModel):
    """
    Template injection variables (Phase 4/5).

    NOTE: Keep this model permissive (extra=ignore) so we can evolve templates
    without breaking older model outputs.
    """

    model_config = ConfigDict(extra="ignore")

    # common-ish
    risks: str = ""
    conflict_disclosure: str = ""

    # news
    news_summary: str = ""
    impact_analysis: str = ""
    next_watch: str = ""

    # company
    conclusion: str = ""
    investment_summary: str = ""
    investment_thesis: str = ""
    company_overview: str = ""
    catalysts: str = ""
    valuation: str = ""
    price_snapshot: str = ""
    technical_snapshot: str = ""
    comparison_conclusion: str = ""
    comparison_metrics: str = ""

    # filing/doc
    summary: str = ""
    highlights: str = ""
    analysis: str = ""
