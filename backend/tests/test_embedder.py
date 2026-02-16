# -*- coding: utf-8 -*-
"""Tests for backend.rag.embedder — EmbeddingService with hash fallback."""
from __future__ import annotations

from backend.rag.embedder import (
    EmbeddingResult,
    EmbeddingService,
    SparseVector,
    _hash_embedding,
    _hash_sparse,
)


def test_hash_embedding_produces_correct_dim():
    vec = _hash_embedding("hello world", dim=96)
    assert len(vec) == 96
    # Should be normalised (unit vector)
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_hash_embedding_empty_text():
    vec = _hash_embedding("", dim=64)
    assert len(vec) == 64
    assert all(v == 0.0 for v in vec)


def test_hash_sparse_non_empty():
    sv = _hash_sparse("apple revenue apple growth")
    assert isinstance(sv, SparseVector)
    assert "apple" in sv.weights
    # "apple" appears twice → highest weight (1.0 after normalisation)
    assert sv.weights["apple"] == 1.0


def test_hash_sparse_empty():
    sv = _hash_sparse("")
    assert sv.weights == {}


def test_embedding_service_hash_backend():
    svc = EmbeddingService(force_backend="hash")
    assert svc.model_name == "hash"
    assert svc.dim == 96  # default hash dim

    result = svc.encode(["hello world", "test sentence"])
    assert isinstance(result, EmbeddingResult)
    assert len(result.dense) == 2
    assert len(result.sparse) == 2
    assert len(result.dense[0]) == 96
    assert result.model_name == "hash"


def test_embedding_service_encode_single():
    svc = EmbeddingService(force_backend="hash")
    dense, sparse = svc.encode_single("apple revenue growth")
    assert len(dense) == 96
    assert isinstance(sparse, SparseVector)
    assert len(sparse.weights) > 0


def test_embedding_service_empty_batch():
    svc = EmbeddingService(force_backend="hash")
    result = svc.encode([])
    assert result.dense == []
    assert result.sparse == []


def test_hash_embedding_deterministic():
    """Same text should always produce the same vector."""
    v1 = _hash_embedding("deterministic test", dim=64)
    v2 = _hash_embedding("deterministic test", dim=64)
    assert v1 == v2


def test_different_texts_produce_different_embeddings():
    v1 = _hash_embedding("apple iphone revenue", dim=64)
    v2 = _hash_embedding("microsoft azure cloud", dim=64)
    assert v1 != v2
