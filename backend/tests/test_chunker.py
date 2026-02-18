# -*- coding: utf-8 -*-
"""Tests for backend.rag.chunker — document chunking strategies."""
from __future__ import annotations

from backend.rag.chunker import ChunkResult, chunk_document


def test_short_news_not_chunked():
    """News articles under 2000 chars should not be split."""
    content = "Apple stock surged 5% on strong Q3 earnings. Revenue beat expectations."
    result = chunk_document(content, "news")
    assert isinstance(result, ChunkResult)
    assert len(result.chunks) == 1
    assert result.chunks[0] == content.strip()
    assert result.metadata[0]["doc_type"] == "news"
    assert result.metadata[0]["total_chunks"] == 1


def test_long_web_page_chunked():
    """Long web pages should be split into multiple chunks."""
    # Generate a long document (~5000 chars)
    paragraph = "This is a detailed analysis paragraph about market conditions. " * 20
    content = "\n\n".join([paragraph] * 5)
    assert len(content) > 2000

    result = chunk_document(content, "web_page")
    assert len(result.chunks) > 1
    assert all(len(c) <= 1400 for c in result.chunks)  # chunk_size + some tolerance
    assert all(m["doc_type"] == "web_page" for m in result.metadata)


def test_filing_chunking():
    """Filing documents use 1000/200 parameters."""
    paragraph = "Risk factor: The company faces significant competition in the market. " * 30
    content = "\n\n".join([paragraph] * 3)
    result = chunk_document(content, "filing")
    assert len(result.chunks) > 1
    assert all(m["doc_type"] == "filing" for m in result.metadata)


def test_transcript_chunking():
    """Transcripts should prefer Q&A boundaries."""
    content = (
        "Opening remarks by CEO.\n\n"
        "Q: What is your outlook for next quarter?\n"
        "A: We expect strong growth driven by new product launches. " * 20 + "\n\n"
        "Q: How about margins?\n"
        "A: Margins should improve due to operational efficiency. " * 20
    )
    result = chunk_document(content, "transcript")
    assert len(result.chunks) >= 1
    assert all(m["doc_type"] == "transcript" for m in result.metadata)


def test_table_not_chunked():
    """Tables should never be split."""
    content = (
        "| Metric | Q1 | Q2 | Q3 |\n"
        "|--------|-----|-----|-----|\n"
        "| Revenue | $10B | $11B | $12B |\n"
        "| EPS | $1.50 | $1.60 | $1.70 |\n"
    )
    result = chunk_document(content, "table")
    assert len(result.chunks) == 1
    assert result.metadata[0]["doc_type"] == "table"


def test_empty_content():
    """Empty content returns empty result."""
    result = chunk_document("", "news")
    assert result.chunks == []
    assert result.metadata == []


def test_chunk_metadata_structure():
    """Each chunk has complete metadata."""
    content = "Short news article about Tesla stock price."
    result = chunk_document(content, "news", title="Tesla News")
    assert len(result.metadata) == 1
    meta = result.metadata[0]
    assert meta["title"] == "Tesla News"
    assert meta["chunk_index"] == 0
    assert meta["total_chunks"] == 1
    assert meta["chunk_length"] == len(content)
    assert meta["doc_type"] == "news"


def test_custom_chunk_size():
    """Override default chunk parameters."""
    paragraph = "Word " * 300  # ~1500 chars
    content = "\n\n".join([paragraph] * 4)
    result = chunk_document(content, "research", max_chunk_size=500, overlap=50)
    assert len(result.chunks) > 4  # should be split into more pieces


def test_auto_detect_table():
    """Markdown tables are auto-detected even if doc_type is web_page."""
    content = (
        "| Col A | Col B |\n"
        "|-------|-------|\n"
        "| 1 | 2 |\n"
        "| 3 | 4 |\n"
        "| 5 | 6 |\n"
    )
    result = chunk_document(content, "web_page")
    assert len(result.chunks) == 1
    assert result.metadata[0]["doc_type"] == "table"
