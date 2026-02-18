# -*- coding: utf-8 -*-
"""Embedding service: bge-m3 with hash-based fallback.

Provides dense (1024-dim) + sparse (lexical weights) embeddings via
``BAAI/bge-m3`` when *FlagEmbedding* is installed. Falls back to the
legacy SHA-1 hash embedding for CI / lightweight dev environments.

Environment variables
---------------------
RAG_EMBEDDING
    ``bge-m3`` (default) or ``hash`` to force the hash fallback.
BGE_M3_DEVICE
    ``cpu`` (default), ``cuda``, ``mps``, etc.
BGE_M3_MAX_LENGTH
    Maximum token length for bge-m3 encoding. Default ``512``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from math import sqrt
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")

_BGE_M3_DIM = 1024
_HASH_DIM_DEFAULT = 96


def _is_production_env() -> bool:
    values = [
        os.getenv("APP_ENV", ""),
        os.getenv("ENV", ""),
        os.getenv("NODE_ENV", ""),
        os.getenv("FASTAPI_ENV", ""),
    ]
    return any(str(v).strip().lower() in {"prod", "production"} for v in values)


def _log_hash_fallback(*, reason: str, detail: str | None = None, requested_backend: str | None = None) -> None:
    payload: dict[str, Any] = {
        "event": "rag_embedding_fallback",
        "backend": "hash",
        "reason": reason,
        "requested_backend": requested_backend or os.getenv("RAG_EMBEDDING", "bge-m3"),
    }
    if detail:
        payload["detail"] = detail
    log_fn = logger.warning if _is_production_env() else logger.info
    log_fn("rag_embedding_fallback %s", payload)


def _tokenize(text: str) -> list[str]:
    """Simple regex tokeniser shared by hash-embedding and sparse helpers."""
    if not text:
        return []
    return [token.lower() for token in _TOKEN_RE.findall(text)]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SparseVector:
    """Sparse representation: ``{token_id_or_string: weight}``."""

    weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingResult:
    """Result of encoding a batch of texts."""

    dense: list[list[float]]  # (N, dim)
    sparse: list[SparseVector]  # N sparse vectors
    model_name: str = "hash"
    dim: int = _HASH_DIM_DEFAULT


# ---------------------------------------------------------------------------
# Hash-based fallback (legacy, for CI / dev without GPU)
# ---------------------------------------------------------------------------

def _hash_embedding(text: str, dim: int = _HASH_DIM_DEFAULT) -> list[float]:
    """Deterministic hash-based pseudo-embedding."""
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _hash_sparse(text: str) -> SparseVector:
    """Token-frequency based sparse vector (fallback)."""
    tokens = _tokenize(text)
    if not tokens:
        return SparseVector()
    freq: dict[str, float] = {}
    for token in tokens:
        freq[token] = freq.get(token, 0.0) + 1.0
    max_freq = max(freq.values()) if freq else 1.0
    return SparseVector(weights={key: value / max_freq for key, value in freq.items()})


def _hash_encode_batch(texts: list[str], dim: int) -> EmbeddingResult:
    dense = [_hash_embedding(text, dim) for text in texts]
    sparse = [_hash_sparse(text) for text in texts]
    return EmbeddingResult(dense=dense, sparse=sparse, model_name="hash", dim=dim)


# ---------------------------------------------------------------------------
# bge-m3 real embedding
# ---------------------------------------------------------------------------

class _BGEM3Wrapper:
    """Lazy-loaded bge-m3 model wrapper (thread-safe singleton)."""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = threading.Lock()
        self._device = os.getenv("BGE_M3_DEVICE", "cpu").strip()
        self._max_length = int(os.getenv("BGE_M3_MAX_LENGTH", "512"))

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-untyped]

            use_fp16 = self._device != "cpu"
            logger.info(
                "Loading bge-m3 (device=%s, fp16=%s, max_length=%d) ...",
                self._device,
                use_fp16,
                self._max_length,
            )
            self._model = BGEM3FlagModel(
                "BAAI/bge-m3",
                use_fp16=use_fp16,
                device=self._device,
            )
            logger.info("bge-m3 loaded successfully.")
            return self._model

    def encode(self, texts: list[str]) -> EmbeddingResult:
        model = self._load()
        output = model.encode(
            texts,
            max_length=self._max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

        dense_vecs: list[list[float]] = []
        sparse_vecs: list[SparseVector] = []

        raw_dense = output.get("dense_vecs") if isinstance(output, dict) else getattr(output, "dense_vecs", None)
        raw_sparse = output.get("lexical_weights") if isinstance(output, dict) else getattr(output, "lexical_weights", None)

        for idx, text in enumerate(texts):
            if raw_dense is not None:
                dense_vecs.append([float(value) for value in raw_dense[idx]])
            else:
                dense_vecs.append(_hash_embedding(text, _BGE_M3_DIM))

            if raw_sparse is not None:
                row = raw_sparse[idx]
                weights = {str(key): float(value) for key, value in row.items()} if isinstance(row, dict) else {}
                sparse_vecs.append(SparseVector(weights=weights))
            else:
                sparse_vecs.append(_hash_sparse(text))

        return EmbeddingResult(
            dense=dense_vecs,
            sparse=sparse_vecs,
            model_name="bge-m3",
            dim=_BGE_M3_DIM,
        )


_bge_m3: _BGEM3Wrapper | None = None
_bge_m3_lock = threading.Lock()


def _get_bge_m3() -> _BGEM3Wrapper:
    global _bge_m3
    if _bge_m3 is not None:
        return _bge_m3
    with _bge_m3_lock:
        if _bge_m3 is None:
            _bge_m3 = _BGEM3Wrapper()
    return _bge_m3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class EmbeddingService:
    """Unified embedding interface with automatic fallback."""

    def __init__(self, *, force_backend: str | None = None) -> None:
        backend = (force_backend or os.getenv("RAG_EMBEDDING", "bge-m3")).strip().lower()
        self._requested_backend = backend
        self._use_bge = backend != "hash"
        self._bge_available: bool | None = None
        self._hash_dim = int(os.getenv("RAG_HASH_DIM", str(_HASH_DIM_DEFAULT)))
        if not self._use_bge:
            _log_hash_fallback(reason="configured_hash_backend", requested_backend=backend)

    @property
    def model_name(self) -> str:
        if self._use_bge and self._check_bge():
            return "bge-m3"
        return "hash"

    @property
    def dim(self) -> int:
        if self._use_bge and self._check_bge():
            return _BGE_M3_DIM
        return self._hash_dim

    def _check_bge(self) -> bool:
        """Lazy check whether FlagEmbedding is importable."""
        if self._bge_available is not None:
            return self._bge_available
        try:
            import FlagEmbedding  # noqa: F401

            self._bge_available = True
        except ImportError as exc:
            _log_hash_fallback(
                reason="flagembedding_unavailable",
                detail=str(exc),
                requested_backend=self._requested_backend,
            )
            self._bge_available = False
        return self._bge_available

    def encode(self, texts: Sequence[str]) -> EmbeddingResult:
        """Encode a batch of texts into dense + sparse vectors."""
        text_list = list(texts)
        if not text_list:
            return EmbeddingResult(dense=[], sparse=[], model_name=self.model_name, dim=self.dim)

        if self._use_bge and self._check_bge():
            try:
                return _get_bge_m3().encode(text_list)
            except Exception as exc:
                _log_hash_fallback(
                    reason="bge_encode_error",
                    detail=str(exc),
                    requested_backend=self._requested_backend,
                )

        return _hash_encode_batch(text_list, self._hash_dim)

    def encode_single(self, text: str) -> tuple[list[float], SparseVector]:
        """Convenience: encode one text, return (dense_vec, sparse_vec)."""
        result = self.encode([text])
        return result.dense[0], result.sparse[0]


_embedding_service: EmbeddingService | None = None
_embedding_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    """Return the module-level EmbeddingService singleton."""
    global _embedding_service
    if _embedding_service is not None:
        return _embedding_service
    with _embedding_lock:
        if _embedding_service is None:
            _embedding_service = EmbeddingService()
    return _embedding_service


def reset_embedding_service() -> None:
    """Reset singleton (for testing)."""
    global _embedding_service
    with _embedding_lock:
        _embedding_service = None


__all__ = [
    "EmbeddingResult",
    "EmbeddingService",
    "SparseVector",
    "get_embedding_service",
    "reset_embedding_service",
]
