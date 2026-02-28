from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any


def _first_json_block(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        return text
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1].strip()
    return None


@dataclass
class OpenAIChatClientV2:
    api_key: str
    base_url: str
    default_model: str
    timeout: int = 120
    max_retries: int = 2
    retry_backoff_seconds: int = 4

    def __post_init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("缺少 openai 依赖，请先安装 requirements.txt") from exc
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.0,
    ) -> str:
        use_model = model or self.default_model
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=use_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:  # pragma: no cover - network dependent
                last_err = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * (attempt + 1))
        raise RuntimeError(f"Chat completion 失败: {last_err}")

    def complete_json(
        self,
        *,
        schema_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        raw = self.complete_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        payload = _first_json_block(raw)
        if not payload:
            raise RuntimeError(f"{schema_name}: 未解析到 JSON 响应")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{schema_name}: JSON 解析失败: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"{schema_name}: JSON 顶层必须是对象")
        return data


@dataclass
class OpenAIEmbeddingClientV2:
    api_key: str
    base_url: str
    default_model: str
    timeout: int = 120
    max_retries: int = 2
    retry_backoff_seconds: int = 4

    def __post_init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("缺少 openai 依赖，请先安装 requirements.txt") from exc
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    def embed_texts(self, texts: list[str], *, model: str | None = None, batch_size: int = 32) -> list[list[float]]:
        use_model = model or self.default_model
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            last_err: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    resp = self._client.embeddings.create(model=use_model, input=batch)
                    chunk = [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
                    vectors.extend(chunk)
                    last_err = None
                    break
                except Exception as exc:  # pragma: no cover - network dependent
                    last_err = exc
                    if attempt >= self.max_retries:
                        break
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
            if last_err is not None:
                raise RuntimeError(f"Embedding 调用失败: {last_err}")
        return vectors


def _env(name: str, fallback: str | None = None) -> str:
    val = os.getenv(name, "").strip()
    if val:
        return val
    if fallback is not None:
        return fallback
    raise RuntimeError(f"缺少环境变量: {name}")


def create_chat_client_from_env() -> OpenAIChatClientV2:
    api_key = _env("RQV2_CHAT_API_KEY", os.getenv("LLM_API_KEY", "").strip())
    base_url = _env("RQV2_CHAT_BASE_URL", "https://grok.jiuuij.de5.net/v1")
    model = _env("RQV2_CHAT_MODEL", "grok-4.1-fast")
    if not api_key:
        raise RuntimeError("缺少 RQV2_CHAT_API_KEY（或 LLM_API_KEY）")
    return OpenAIChatClientV2(api_key=api_key, base_url=base_url, default_model=model)


def create_embedding_client_from_env() -> OpenAIEmbeddingClientV2:
    api_key = _env("RQV2_EMBED_API_KEY", os.getenv("LLM_API_KEY", "").strip())
    base_url = _env("RQV2_EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
    model = _env("RQV2_EMBED_MODEL", "BAAI/bge-m3")
    if not api_key:
        raise RuntimeError("缺少 RQV2_EMBED_API_KEY（或 LLM_API_KEY）")
    return OpenAIEmbeddingClientV2(api_key=api_key, base_url=base_url, default_model=model)

