# -*- coding: utf-8 -*-
"""
Disclaimer template for compliance gating.
"""

DISCLAIMER_TITLE = "Disclaimer"
DISCLAIMER_TEXT = (
    "This report is for informational purposes only and does not constitute investment advice. "
    "Financial markets involve risk, and past performance does not guarantee future results. "
    "Please consult a qualified financial advisor before making investment decisions."
)


def build_disclaimer_section(order: int) -> dict:
    return {
        "title": DISCLAIMER_TITLE,
        "order": order,
        "contents": [{"type": "text", "content": DISCLAIMER_TEXT}],
    }
