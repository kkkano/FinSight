"""私网推理 worker；不加载业务 API、数据库或供应商密钥。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.rag.embedder import _BGEM3Wrapper
from backend.rag.reranker import _CrossEncoderWrapper


_model = _BGEM3Wrapper()
_reranker = _CrossEncoderWrapper()
_inference_lock = Lock()
_state = {"status": "starting", "model_name": "bge-m3", "model_version": "unknown", "inference_verified": False,
          "reranker": "disabled" if os.getenv("RAG_RERANKER", "none") == "none" else "unverified"}


def _memory_available_mb() -> float | None:
    if not Path('/proc/meminfo').exists():
        return None
    fields = {line.partition(':')[0]: line.partition(':')[2].strip().split()[0]
              for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line}
    available = int(fields.get('MemAvailable', '0')) / 1024
    limit_path, used_path = Path('/sys/fs/cgroup/memory.max'), Path('/sys/fs/cgroup/memory.current')
    if limit_path.exists() and used_path.exists() and limit_path.read_text().strip().isdigit():
        available = min(available, (int(limit_path.read_text()) - int(used_path.read_text())) / 1024 ** 2)
    return available


def _encode(texts: list[str]) -> dict:
    with _inference_lock:
        available = _memory_available_mb()
        needed = max(512, int(os.getenv('RAG_WORKER_MIN_AVAILABLE_MB', '2400')))
        if _model._model is None and available is not None and available < needed:
            _state.update(status='resource_limited', inference_verified=False)
            raise HTTPException(status_code=503, detail='embedding_memory_unavailable')
        try:
            result = _model.encode(texts)
            wrapped = _model._model
            configs = [getattr(getattr(wrapped, "model", None), "config", None),
                       getattr(getattr(getattr(wrapped, "model", None), "model", None), "config", None)]
            revision = next((str(config._commit_hash) for config in configs if getattr(config, "_commit_hash", None)), None)
            if not revision:
                raise ValueError("embedding_revision_unavailable")
            precision = "float32" if _model._device == "cpu" else "float16"
            version = f"{revision}:max{_model._max_length}:{precision}:v1"
            _state.update(status="ok", model_version=version, inference_verified=True)
            return {"dense": result.dense, "model_name": "bge-m3", "dim": result.dim, "model_version": version}
        except Exception as exc:
            _state.update(status="error", inference_verified=False)
            raise HTTPException(status_code=503, detail="embedding_inference_unavailable") from exc


async def _warmup():
    try:
        await asyncio.to_thread(_encode, ["FinSight embedding readiness"])
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_warmup())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def authenticate(request: Request):
    token = os.getenv("RAG_WORKER_TOKEN", "")
    supplied = request.headers.get("Authorization", "")
    if not token or not hmac.compare_digest(supplied, "Bearer " + token):
        raise HTTPException(status_code=401, detail="unauthorized")


class EncodeRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=8)

    @field_validator("texts")
    @classmethod
    def bounded_text(cls, texts):
        if any(len(text) > 32000 for text in texts) or sum(len(text) for text in texts) > 64000:
            raise ValueError("embedding_batch_too_large")
        return texts


@app.get("/health")
def health():
    return dict(_state)


@app.post("/encode", dependencies=[Depends(authenticate)])
def encode(request: EncodeRequest):
    return _encode(request.texts)


class RerankRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    documents: list[str] = Field(min_length=1, max_length=32)


@app.post("/rerank", dependencies=[Depends(authenticate)])
def rerank(request: RerankRequest):
    if _state["reranker"] == "disabled":
        raise HTTPException(status_code=503, detail="reranker_disabled")
    if sum(map(len, request.documents)) > 128000:
        raise HTTPException(status_code=413, detail="reranker_batch_too_large")
    with _inference_lock:
        try:
            scores = _reranker.predict([(request.query, text) for text in request.documents])
            _state["reranker"] = "ok"
            return {"scores": scores}
        except Exception as exc:
            _state["reranker"] = "degraded"
            raise HTTPException(status_code=503, detail="reranker_unavailable") from exc
