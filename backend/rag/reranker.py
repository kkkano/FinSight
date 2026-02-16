# -*- coding: utf-8 -*-
"""Cross-Encoder reranking service.

Uses ``BAAI/bge-reranker-v2-m3`` for production reranking.
Falls back gracefully when the model is unavailable (CI / lightweight envs).

Environment variables
---------------------
RAG_RERANKER
    ``bge-reranker`` (default) or ``none`` to disable reranking.
RAG_RERANKER_MAX_LENGTH
    Maximum token length for reranker input.  Default ``512``.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Sequence

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N = 8


# ---------------------------------------------------------------------------
# Reranker wrapper
# ---------------------------------------------------------------------------

class _CrossEncoderWrapper:
    """Lazy-loaded bge-reranker-v2-m3 wrapper (thread-safe singleton)."""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = threading.Lock()
        self._max_length = int(os.getenv("RAG_RERANKER_MAX_LENGTH", "512"))

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]
            logger.info("Loading bge-reranker-v2-m3 (max_length=%d) ...", self._max_length)
            self._model = CrossEncoder(
                "BAAI/bge-reranker-v2-m3",
                max_length=self._max_length,
            )
            logger.info("bge-reranker-v2-m3 loaded successfully.")
            return self._model

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        model = self._load()
        scores = model.predict(pairs)
        return [float(s) for s in scores]


# Module-level lazy singleton
_reranker: _CrossEncoderWrapper | None = None
_reranker_lock = threading.Lock()


def _get_reranker() -> _CrossEncoderWrapper:
    global _reranker
    if _reranker is not None:
        return _reranker
    with _reranker_lock:
        if _reranker is None:
            _reranker = _CrossEncoderWrapper()
    return _reranker


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class RerankerService:
    """Cross-Encoder reranking service with graceful fallback.

    Usage::

        svc = RerankerService()
        ranked = svc.rerank("query text", documents, top_n=5)
    """

    def __init__(self, *, force_backend: str | None = None) -> None:
        backend = (force_backend or os.getenv("RAG_RERANKER", "bge-reranker")).strip().lower()
        self._enabled = backend != "none"
        self._available: bool | None = None  # lazy check

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._check_available()

    def _check_available(self) -> bool:
        """Lazy check whether sentence_transformers CrossEncoder is importable."""
        if self._available is not None:
            return self._available
        if not self._enabled:
            self._available = False
            return False
        try:
            from sentence_transformers import CrossEncoder  # noqa: F401
            self._available = True
        except ImportError:
            logger.warning(
                "sentence-transformers not installed — reranking disabled. "
                "Install with: pip install sentence-transformers"
            )
            self._available = False
        return self._available

    def rerank(
        self,
        query: str,
        documents: Sequence[dict[str, Any]],
        *,
        top_n: int = _DEFAULT_TOP_N,
        content_key: str = "content",
    ) -> list[dict[str, Any]]:
        """Rerank *documents* by relevance to *query*.

        Parameters
        ----------
        query : str
            The search query.
        documents : Sequence[dict]
            List of document dicts (must have *content_key* field).
        top_n : int
            Number of top results to return.
        content_key : str
            Key to extract document text from each dict.

        Returns
        -------
        list[dict]
            Top-N documents with ``rerank_score`` field added.
        """
        doc_list = list(documents)
        if not doc_list or not query.strip():
            return doc_list[:top_n]

        if not self._enabled or not self._check_available():
            # Fallback: return as-is (already sorted by RRF)
            return doc_list[:top_n]

        try:
            pairs = [
                (query, str(doc.get(content_key) or ""))
                for doc in doc_list
            ]
            scores = _get_reranker().predict(pairs)

            ranked = sorted(
                zip(doc_list, scores),
                key=lambda x: x[1],
                reverse=True,
            )
            return [
                {**doc, "rerank_score": score}
                for doc, score in ranked[:top_n]
            ]
        except Exception as exc:
            logger.error("Reranking failed, returning original order: %s", exc)
            return doc_list[:top_n]


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_reranker_service: RerankerService | None = None
_reranker_svc_lock = threading.Lock()


def get_reranker_service() -> RerankerService:
    """Return the module-level RerankerService singleton."""
    global _reranker_service
    if _reranker_service is not None:
        return _reranker_service
    with _reranker_svc_lock:
        if _reranker_service is None:
            _reranker_service = RerankerService()
    return _reranker_service


def reset_reranker_service() -> None:
    """Reset singleton (for testing)."""
    global _reranker_service
    with _reranker_svc_lock:
        _reranker_service = None


__all__ = [
    "RerankerService",
    "get_reranker_service",
    "reset_reranker_service",
]
