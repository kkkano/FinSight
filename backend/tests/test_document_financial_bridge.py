"""已有原文与数值跨工具/Agent 进入同一事实合同，不重新抓取或解释格式化金额。"""
from unittest.mock import MagicMock

from backend.tools import disclosure_financial_facts
from backend.tools.local_disclosure import verified_disclosure_document


def test_official_document_requires_declared_issuer_and_website():
    body = "证券代码：300750\n发行人2025年度报告\n公司网址：www.issuer.example\n"
    assert verified_disclosure_document(body, "https://issuer.example/report.pdf", "300750.SZ")
    assert not verified_disclosure_document(body, "https://media.example/report.pdf", "300750.SZ")
    assert not verified_disclosure_document(body, "https://issuer.example/report.pdf", "600519.SS")
