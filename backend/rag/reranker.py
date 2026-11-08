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
import hashlib
import os
import threading
from typing import Any, Sequence

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N = 8
_REMOTE_MAX_DOCUMENTS = 32
_REMOTE_MAX_CHARACTERS = 120000


def _remote_candidates(query: str, documents: list[dict[str, Any]], content_key: str) -> list[dict[str, Any]]:
    """按原检索顺序选择预算内的整条候选，查询也占用字符预算，不截断正文。"""
    selected = []
    used = len(query)
    for document in documents:
        length = len(str(document.get(content_key) or ""))
        if used + length > _REMOTE_MAX_CHARACTERS:
            continue
        selected.append(document)
        used += length
        if len(selected) == _REMOTE_MAX_DOCUMENTS:
            break
    return selected


def _is_production_env() -> bool:
    values = [
        os.getenv("FINSIGHT_RUNTIME_PROFILE", ""),
        os.getenv("APP_MODE", ""),
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
        backend = (force_backend or os.getenv("RAG_RERANKER", "none")).strip().lower()
        if backend not in {"none", "remote_api", "bge-reranker"}:
            raise ValueError("unsupported RAG_RERANKER provider")
        self._requested_backend = backend
        self._enabled = backend != "none"
        self._available: bool | None = None
        self._last_status = "unverified"
        self._worker_url = str(os.getenv("RAG_WORKER_URL") or "").strip().rstrip("/")
        if not self._enabled:
            _log_reranker_degraded(
                reason="configured_none_backend",
                requested_backend=backend,
            )

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._check_available()

    def health(self) -> dict[str, str]:
        """只读最后调用状态，不为健康检查额外调用模型。"""
        return {"status": self._last_status if self._enabled else "disabled", "provider": self._requested_backend}

    def _check_available(self) -> bool:
        """Lazy check whether sentence_transformers CrossEncoder is importable."""
        if self._requested_backend == "remote_api":
            return True
        if self._worker_url:
            return self._enabled
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
            if self._requested_backend == "remote_api":
                from backend.rag.api_provider import HTTPRerankProvider
                candidates = _remote_candidates(query, doc_list, content_key)
                if not candidates:
                    raise ValueError("rerank_candidate_budget_exceeded")
                ranked = HTTPRerankProvider.from_env().rank(
                    query, [str(doc.get(content_key) or "") for doc in candidates], top_n)
                self._last_status = "ok"
                return [{**candidates[index], "rerank_score": score} for index, score in ranked]
            pairs = [(query, str(doc.get(content_key) or "")) for doc in doc_list]
            if self._worker_url:
                import httpx
                with httpx.Client(timeout=float(os.getenv("RAG_WORKER_TIMEOUT_SECONDS", "60")), trust_env=False) as client:
                    response = client.post(self._worker_url + "/rerank", json={"query": query,
                        "documents": [pair[1] for pair in pairs]},
                        headers={"Authorization": "Bearer " + os.getenv("RAG_WORKER_TOKEN", "")})
                    response.raise_for_status()
                    scores = response.json()["scores"]
                    if len(scores) != len(doc_list):
                        raise ValueError("reranker_invalid_response")
            else:
                scores = _get_reranker().predict(pairs)
            ranked = sorted(zip(doc_list, scores), key=lambda item: item[1], reverse=True)
            self._last_status = "ok"
            return [{**doc, "rerank_score": score} for doc, score in ranked[:top_n]]
        except Exception as exc:
            self._last_status = "degraded"
            _log_reranker_degraded(
                reason="rerank_inference_error",
                detail=type(exc).__name__,
                requested_backend=self._requested_backend,
            )
            return doc_list[:top_n]


_reranker_service: RerankerService | None = None
_reranker_service_config: str | None = None
_reranker_svc_lock = threading.Lock()


def _configured_service_key() -> str:
    backend = os.getenv("RAG_RERANKER", "none").strip().lower()
    names = (("RAG_RERANK_API_URL", "RAG_RERANK_MODEL", "RAG_RERANK_API_KEY", "RAG_RERANK_TIMEOUT_SECONDS")
             if backend == "remote_api" else
             ("RAG_WORKER_URL", "RAG_WORKER_TOKEN", "RAG_WORKER_TIMEOUT_SECONDS", "RAG_RERANKER_MAX_LENGTH")
             if backend == "bge-reranker" else ())
    # 配置变化后不能沿用旧模型的成功状态；签名不保留或输出密钥原文。
    return hashlib.sha256("\0".join([backend, *(os.getenv(name, "") for name in names)]).encode()).hexdigest()


def get_reranker_service() -> RerankerService:
    """Return the module-level RerankerService singleton."""
    global _reranker_service, _reranker_service_config
    config = _configured_service_key()
    if _reranker_service is not None and _reranker_service_config == config:
        return _reranker_service
    with _reranker_svc_lock:
        if _reranker_service is None or _reranker_service_config != config:
            _reranker_service = RerankerService()
            _reranker_service_config = config
    return _reranker_service


def reset_reranker_service() -> None:
    """Reset singleton (for testing)."""
    global _reranker_service, _reranker_service_config
    with _reranker_svc_lock:
        _reranker_service = None
        _reranker_service_config = None


__all__ = [
    "RerankerService",
    "get_reranker_service",
    "reset_reranker_service",
]
