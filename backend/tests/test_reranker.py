# -*- coding: utf-8 -*-
"""Tests for backend.rag.reranker — RerankerService with fallback."""
from __future__ import annotations

from backend.rag.reranker import RerankerService


def test_reranker_disabled_returns_original_order():
    """When reranker is disabled, documents are returned in original order."""
    svc = RerankerService(force_backend="none")
    assert not svc.is_enabled

    docs = [
        {"content": "Apple revenue guidance", "source_id": "a"},
        {"content": "Microsoft Azure growth", "source_id": "b"},
        {"content": "Tesla delivery numbers", "source_id": "c"},
    ]
    result = svc.rerank("Apple earnings", docs, top_n=2)
    assert len(result) == 2
    assert result[0]["source_id"] == "a"
    assert result[1]["source_id"] == "b"


def test_reranker_disabled_empty_query():
    svc = RerankerService(force_backend="none")
    docs = [{"content": "test", "source_id": "x"}]
    result = svc.rerank("", docs, top_n=5)
    assert len(result) == 1


def test_reranker_disabled_empty_docs():
    svc = RerankerService(force_backend="none")
    result = svc.rerank("test query", [], top_n=5)
    assert result == []


def test_reranker_top_n_clipping():
    """Top-N should limit the output."""
    svc = RerankerService(force_backend="none")
    docs = [{"content": f"doc {i}", "source_id": str(i)} for i in range(10)]
    result = svc.rerank("query", docs, top_n=3)
    assert len(result) == 3
