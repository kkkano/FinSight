# -*- coding: utf-8 -*-
"""Cross-Encoder reranking service.

Uses ``BAAI/bge-reranker-v2-m3`` for production reranking.
Falls back gracefully when the model is unavailable (CI / lightweight envs).

Environment variables
---------------------
RAG_RERANKER
    ``bge-reranker`` (default) or ``none`` to disable reranking.
RAG_RERANKER_MAX_LENGTH
    Maximum token length for reranker input. Default ``512``.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Sequence

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N = 8


def _is_production_env() -> bool:
    values = [
        os.getenv("APP_ENV", ""),
        os.getenv("ENV", ""),
        os.getenv("NODE_ENV", ""),
        os.getenv("FASTAPI_ENV", ""),
    ]
    return any(str(v).strip().lower() in {"prod", "production"} for v in values)


def _log_reranker_degraded(*, reason: str, detail: str | None = None, requested_backend: str | None = None) -> None:
    payload: dict[str, Any] = {
        "event": "rag_reranker_degraded",
        "reason": reason,
        "requested_backend": requested_backend or os.getenv("RAG_RERANKER", "bge-reranker"),
    }
    if detail:
        payload["detail"] = detail
    log_fn = logger.warning if _is_production_env() else logger.info
    log_fn("rag_reranker_degraded %s", payload)


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
        return [float(score) for score in scores]


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


class RerankerService:
    """Cross-Encoder reranking service with graceful fallback."""

    def __init__(self, *, force_backend: str | None = None) -> None:
        backend = (force_backend or os.getenv("RAG_RERANKER", "bge-reranker")).strip().lower()
        self._requested_backend = backend
        self._enabled = backend != "none"
        self._available: bool | None = None
        if not self._enabled:
            _log_reranker_degraded(
                reason="configured_none_backend",
                requested_backend=backend,
            )

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
        except ImportError as exc:
            _log_reranker_degraded(
                reason="sentence_transformers_unavailable",
                detail=str(exc),
                requested_backend=self._requested_backend,
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
        """Rerank *documents* by relevance to *query*."""
        doc_list = list(documents)
        if not doc_list or not query.strip():
            return doc_list[:top_n]

        if not self._enabled or not self._check_available():
            return doc_list[:top_n]

        try:
            pairs = [(query, str(doc.get(content_key) or "")) for doc in doc_list]
            scores = _get_reranker().predict(pairs)
            ranked = sorted(zip(doc_list, scores), key=lambda item: item[1], reverse=True)
            return [{**doc, "rerank_score": score} for doc, score in ranked[:top_n]]
        except Exception as exc:
            _log_reranker_degraded(
                reason="rerank_inference_error",
                detail=str(exc),
                requested_backend=self._requested_backend,
            )
            return doc_list[:top_n]


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
