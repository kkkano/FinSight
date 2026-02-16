# -*- coding: utf-8 -*-
"""Unified document chunking strategies.

Dispatches to the appropriate splitter based on document type:

- **filing**: SEC filings / earnings reports → RecursiveCharacterTextSplitter (1000/200)
- **transcript**: Earnings call transcripts → Custom Q&A-aware splitting (800/100)
- **news**: Short news articles ≤ 2000 chars → No splitting (preserve integrity)
- **research**: Research documents → RecursiveCharacterTextSplitter (1200/200)
- **web_page**: Web-scraped content → RecursiveCharacterTextSplitter (1200/200)
- **table**: Markdown tables → No splitting (tables lose meaning when split)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

DocType = Literal["filing", "transcript", "news", "research", "web_page", "table"]

_SHORT_DOC_THRESHOLD = 2000  # docs shorter than this are not chunked


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChunkResult:
    """Output of ``chunk_document``."""
    chunks: list[str]
    metadata: list[dict[str, str | int | None]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Splitter helpers
# ---------------------------------------------------------------------------

def _get_recursive_splitter(
    *,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    separators: list[str] | None = None,
) -> "RecursiveCharacterTextSplitter":  # type: ignore[name-defined]
    """Lazily import and return a LangChain RecursiveCharacterTextSplitter."""
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        raise ImportError(
            "langchain-text-splitters is required for chunking. "
            "Install with: pip install langchain-text-splitters"
        )
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators or ["\n\n", "\n", ". ", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )


def _chunk_filing(content: str, *, max_chunk_size: int, overlap: int) -> list[str]:
    """Split SEC-style filings respecting paragraph boundaries."""
    splitter = _get_recursive_splitter(
        chunk_size=max_chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(content)


def _chunk_transcript(content: str, *, max_chunk_size: int, overlap: int) -> list[str]:
    """Split earnings call transcripts by Q&A turns first, then fallback."""
    splitter = _get_recursive_splitter(
        chunk_size=max_chunk_size,
        chunk_overlap=overlap,
        # Prefer splitting at Q&A boundaries
        separators=["\nQ:", "\nA:", "\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(content)


def _chunk_long_text(content: str, *, max_chunk_size: int, overlap: int) -> list[str]:
    """Generic splitting for research docs / web pages."""
    splitter = _get_recursive_splitter(
        chunk_size=max_chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(content)


# ---------------------------------------------------------------------------
# Table detection
# ---------------------------------------------------------------------------

_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def _is_likely_table(content: str) -> bool:
    """Heuristic: if >30% of lines look like markdown table rows."""
    lines = content.strip().splitlines()
    if not lines:
        return False
    table_lines = sum(1 for line in lines if _TABLE_RE.match(line))
    return table_lines / len(lines) > 0.3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Default chunk parameters per doc type
_DEFAULTS: dict[DocType, dict[str, int]] = {
    "filing":     {"max_chunk_size": 1000, "overlap": 200},
    "transcript": {"max_chunk_size": 800,  "overlap": 100},
    "news":       {"max_chunk_size": 2000, "overlap": 0},
    "research":   {"max_chunk_size": 1200, "overlap": 200},
    "web_page":   {"max_chunk_size": 1200, "overlap": 200},
    "table":      {"max_chunk_size": 8000, "overlap": 0},
}


def chunk_document(
    content: str,
    doc_type: DocType = "web_page",
    *,
    title: str | None = None,
    max_chunk_size: int | None = None,
    overlap: int | None = None,
) -> ChunkResult:
    """Split *content* according to *doc_type* strategy.

    Parameters
    ----------
    content : str
        Raw document text.
    doc_type : DocType
        One of ``filing``, ``transcript``, ``news``, ``research``,
        ``web_page``, ``table``.
    title : str | None
        Optional document title (stored in chunk metadata).
    max_chunk_size : int | None
        Override default chunk size.
    overlap : int | None
        Override default overlap.

    Returns
    -------
    ChunkResult
        ``chunks`` list of text segments, ``metadata`` list of dicts.
    """
    text = (content or "").strip()
    if not text:
        return ChunkResult(chunks=[], metadata=[])

    defaults = _DEFAULTS.get(doc_type, _DEFAULTS["web_page"])
    chunk_sz = max_chunk_size or defaults["max_chunk_size"]
    chunk_ov = overlap if overlap is not None else defaults["overlap"]

    # ---- No-split paths ----
    # Tables: never split (check first — tables are always kept intact)
    if doc_type == "table" or _is_likely_table(text):
        return _build_result([text], doc_type="table", title=title)

    # Short documents: preserve as-is
    if len(text) <= _SHORT_DOC_THRESHOLD and doc_type in ("news", "web_page"):
        return _build_result([text], doc_type=doc_type, title=title)

    # ---- Splitting paths ----
    try:
        if doc_type == "filing":
            chunks = _chunk_filing(text, max_chunk_size=chunk_sz, overlap=chunk_ov)
        elif doc_type == "transcript":
            chunks = _chunk_transcript(text, max_chunk_size=chunk_sz, overlap=chunk_ov)
        else:
            chunks = _chunk_long_text(text, max_chunk_size=chunk_sz, overlap=chunk_ov)
    except Exception as exc:
        logger.error("Chunking failed for doc_type=%s, falling back to whole doc: %s", doc_type, exc)
        chunks = [text]

    # Filter out empty chunks
    chunks = [c.strip() for c in chunks if c.strip()]
    if not chunks:
        chunks = [text]

    return _build_result(chunks, doc_type=doc_type, title=title)


def _build_result(
    chunks: list[str],
    *,
    doc_type: str,
    title: str | None,
) -> ChunkResult:
    """Build ChunkResult with per-chunk metadata."""
    metadata_list: list[dict[str, str | int | None]] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        metadata_list.append({
            "doc_type": doc_type,
            "title": title,
            "chunk_index": i,
            "total_chunks": total,
            "chunk_length": len(chunk),
        })
    return ChunkResult(chunks=chunks, metadata=metadata_list)


__all__ = [
    "ChunkResult",
    "DocType",
    "chunk_document",
]
