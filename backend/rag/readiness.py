"""显式启动验收：一次真实API小请求，不写测试资料，不在health轮询中调用。"""
from __future__ import annotations

import os


def verify_hosted_retrieval_startup() -> dict:
    if os.getenv("RAG_EMBEDDING", "lexical").strip().lower() != "remote_api":
        return {"status": "skipped"}
    from backend.rag.hybrid_service import get_rag_service
    from backend.rag.reranker import get_reranker_service
    service = get_rag_service()
    result = service._embedder.encode(["FinSight retrieval readiness"])
    reranker = get_reranker_service()
    if reranker.is_enabled:
        rows = reranker.rerank("cash flow", [{"content": "Operating cash flow"}, {"content": "Weather forecast"}], top_n=1)
        if not rows or "rerank_score" not in rows[0]:
            raise RuntimeError("reranker_startup_verification_failed")
    return {"status": "ok", "dimension": result.dim, "reranker": reranker.health()["status"]}
