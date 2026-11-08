"""无公开端口的计算作业 HTTP 协议。"""
from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from .dispatcher import Dispatcher, Settings, available_memory_mb
from .protocol import AnalysisError, JobRequest, MAX_REQUEST_BYTES


async def run_connected(request: Request, dispatcher: Dispatcher, job: JobRequest) -> dict:
    async def disconnected():
        while not await request.is_disconnected():
            await asyncio.sleep(0.1)

    task = asyncio.create_task(dispatcher.run(job))
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return await task
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return {"status": "error", "error": "analysis_cancelled"}
    finally:
        watcher.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


def create_app(settings: Settings | None = None, dispatcher: Dispatcher | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    dispatcher = dispatcher or Dispatcher(settings)

    @asynccontextmanager
    async def lifespan(_app):
        await dispatcher.initialize()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.dispatcher = dispatcher

    @app.get("/health")
    async def health():
        capacity = {}
        try:
            available = available_memory_mb()
            memory = dispatcher.job_memory_mb(available)
            capacity = {"available_memory_mb": available, "job_memory_mb": memory, "can_accept_job": bool(memory and not dispatcher.active),
                        "min_job_memory_mb": settings.min_memory_mb, "max_job_memory_mb": settings.memory_mb,
                        "memory_reserve_mb": settings.reserve_memory_mb, "adaptive_memory": settings.adaptive_memory}
        except AnalysisError:
            capacity = {"can_accept_job": False}
        return JSONResponse({"ready": dispatcher.ready, "error": dispatcher.error or None, **capacity},
                            status_code=200 if dispatcher.ready else 503)

    @app.post("/jobs")
    async def jobs(request: Request):
        if not settings.configured():
            return JSONResponse({"status": "error", "error": "analysis_worker_unconfigured"}, status_code=503)
        expected = ("Bearer " + settings.token).encode()
        if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), expected):
            return JSONResponse({"status": "error", "error": "analysis_unauthorized"}, status_code=401)
        if not dispatcher.ready:
            return JSONResponse({"status": "error", "error": dispatcher.error}, status_code=503)
        if dispatcher.active:
            return JSONResponse({"status": "error", "error": "analysis_worker_busy"}, status_code=429)
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            return JSONResponse({"status": "error", "error": "analysis_request_invalid"}, status_code=415)
        try:
            raw = bytearray()
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > MAX_REQUEST_BYTES:
                        raise AnalysisError("analysis_request_too_large")
                    raw.extend(chunk)
            job = JobRequest.from_bytes(bytes(raw))
        except AnalysisError as exc:
            return JSONResponse({"status": "error", "error": exc.code},
                                status_code=413 if exc.code == "analysis_request_too_large" else 422)
        except (ClientDisconnect, TimeoutError):
            return JSONResponse({"status": "error", "error": "analysis_cancelled"}, status_code=408)
        result = await run_connected(request, dispatcher, job)
        return JSONResponse(result, status_code=429 if result.get("error") == "analysis_worker_busy" else 200)

    return app


app = create_app()
