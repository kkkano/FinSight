"""托管向量/重排接口；有界 HTTP 调用，不导入本地推理依赖。"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx


class ProviderUnavailable(RuntimeError):
    """仅包含安全错误码，不能把供应商正文或密钥带入日志。"""


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ProviderUnavailable("embedding_api_url_invalid") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or port not in (None, 443)):
        raise ProviderUnavailable("embedding_api_url_invalid")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal")):
        raise ProviderUnavailable("embedding_api_url_invalid")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (not address.is_global or address.is_multicast):
        raise ProviderUnavailable("embedding_api_url_invalid")
    return value


def _request(url: str, body: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
    from backend.services.run_context import current_run_context

    context = current_run_context()
    if context is not None:
        timeout = context.timeout(timeout)
    # URL由服务端配置提供，禁止重定向把Authorization转发给另一端点。
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            with client.stream("POST", url, json=body, headers={"Authorization": "Bearer " + key}) as response:
                response.raise_for_status()
                data = bytearray()
                for part in response.iter_bytes():
                    if context is not None:
                        context.guard()
                    data.extend(part)
                    if len(data) > 8 * 1024 * 1024:
                        raise ProviderUnavailable("embedding_api_response_too_large")
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ProviderUnavailable("embedding_api_response_invalid")
        return payload
    except ProviderUnavailable:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise ProviderUnavailable("embedding_api_request_failed") from None


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProviderUnavailable("embedding_api_vector_invalid")
    return float(value)


@dataclass(frozen=True)
class HTTPEmbeddingProvider:
    url: str
    model: str
    key: str = field(repr=False)
    dimension: int = 1024
    model_version: str = "configured-v1"
    batch_size: int = 8
    timeout: float = 20.0

    @classmethod
    def from_env(cls) -> "HTTPEmbeddingProvider":
        model = os.getenv("RAG_EMBEDDING_MODEL", "").strip()
        key = os.getenv("RAG_EMBEDDING_API_KEY", "").strip()
        if not model or not key:
            raise ProviderUnavailable("embedding_api_not_configured")
        return cls(
            url=_url(os.getenv("RAG_EMBEDDING_API_URL", "")), model=model, key=key,
            dimension=_integer("RAG_EMBEDDING_DIM", 1024, 16, 8192),
            model_version=os.getenv("RAG_EMBEDDING_MODEL_VERSION", "configured-v1").strip() or "configured-v1",
            batch_size=_integer("RAG_EMBEDDING_BATCH_SIZE", 8, 1, 32),
            timeout=float(_integer("RAG_EMBEDDING_TIMEOUT_SECONDS", 20, 1, 60)),
        )

    def encode(self, texts: list[str]) -> tuple[list[list[float]], str, str]:
        if any(not isinstance(text, str) or len(text) > 32000 for text in texts):
            raise ProviderUnavailable("embedding_api_input_too_large")
        vectors: list[list[float]] = []
        version: str | None = None
        for offset in range(0, len(texts), self.batch_size):
            batch = texts[offset:offset + self.batch_size]
            payload = _request(self.url, {"model": self.model, "input": batch,
                               "encoding_format": "float"}, self.key, self.timeout)
            actual_model = payload.get("model")
            if actual_model is not None and actual_model != self.model:
                raise ProviderUnavailable("embedding_api_model_changed")
            items = payload.get("data")
            if not isinstance(items, list) or len(items) != len(batch):
                raise ProviderUnavailable("embedding_api_response_invalid")
            indexed: dict[int, list[float]] = {}
            for item in items:
                if not isinstance(item, dict):
                    raise ProviderUnavailable("embedding_api_response_invalid")
                index = item.get("index")
                row = item.get("embedding")
                if (isinstance(index, bool) or not isinstance(index, int)
                        or not 0 <= index < len(batch) or index in indexed
                        or not isinstance(row, list) or len(row) != self.dimension):
                    raise ProviderUnavailable("embedding_api_vector_invalid")
                vector = [_number(value) for value in row]
                if not any(vector):
                    raise ProviderUnavailable("embedding_api_vector_invalid")
                indexed[index] = vector
            reported = str(payload.get("model_version") or payload.get("revision") or self.model_version)
            if version is not None and version != reported:
                raise ProviderUnavailable("embedding_api_revision_changed")
            version = reported
            vectors.extend(indexed[index] for index in range(len(batch)))
        # 同名模型在不同服务、预处理配置或显式代次中不能混用向量空间。
        identity = hashlib.sha256(json.dumps({
            "endpoint": self.url, "model": self.model, "revision": version or self.model_version,
            "generation": self.model_version, "encoding": "float", "truncation": "none",
        }, sort_keys=True).encode()).hexdigest()[:24]
        return vectors, self.model, "api-v1:" + identity


@dataclass(frozen=True)
class HTTPRerankProvider:
    url: str
    model: str
    key: str = field(repr=False)
    timeout: float = 15.0

    @classmethod
    def from_env(cls) -> "HTTPRerankProvider":
        model = os.getenv("RAG_RERANK_MODEL", "").strip()
        key = os.getenv("RAG_RERANK_API_KEY", "").strip()
        if not model or not key:
            raise ProviderUnavailable("rerank_api_not_configured")
        return cls(_url(os.getenv("RAG_RERANK_API_URL", "")), model, key,
                   float(_integer("RAG_RERANK_TIMEOUT_SECONDS", 15, 1, 60)))

    def rank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        if len(query) > 8000 or len(documents) > 32 or sum(map(len, documents)) > 128000:
            raise ProviderUnavailable("rerank_api_input_too_large")
        payload = _request(self.url, {"model": self.model, "query": query, "documents": documents,
                           "top_n": min(top_n, len(documents)), "return_documents": False},
                           self.key, self.timeout)
        items = payload.get("results")
        if not isinstance(items, list) or not items:
            raise ProviderUnavailable("rerank_api_response_invalid")
        seen: set[int] = set()
        ranked: list[tuple[int, float]] = []
        for item in items:
            if not isinstance(item, dict):
                raise ProviderUnavailable("rerank_api_response_invalid")
            index = item.get("index")
            if (isinstance(index, bool) or not isinstance(index, int)
                    or not 0 <= index < len(documents) or index in seen):
                raise ProviderUnavailable("rerank_api_response_invalid")
            seen.add(index)
            ranked.append((index, _number(item.get("relevance_score"))))
        return sorted(ranked, key=lambda pair: pair[1], reverse=True)[:top_n]

