"""真实托管向量、混合检索和重排评测；语料为合成金融案例，不代表真实公司数据。

默认只连接本机隔离 Postgres 测试库，需预先执行仓库迁移；不会创建或删除数据库。
密钥从指定 env 文件读取，报告不记录密钥、DSN 或完整向量。
示例：python scripts/live_vector_eval.py --backend memory --env-file .env.runtime.local
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.rag.api_provider import HTTPEmbeddingProvider, HTTPRerankProvider
from backend.rag.embedder import EmbeddingService
from backend.rag.hybrid_service import HybridRAGService, RAGDocument
from backend.rag.layering import build_stock_kb_collection, build_thread_working_set_collection
from backend.rag.tools import KnowledgeTools
from backend.rag.chunker import INDEX_CHUNK_MAX_BYTES


CORPUS = [
    ("cashflow_en", "Collections and cash flow", "Operating cash flow increased because customers settled overdue receivables. Faster collections released working capital and lifted free cash flow despite unchanged accounting revenue."),
    ("cashflow_zh", "现金创造与营运资本", "企业通过缩短应收账款回收天数释放营运资本，经营现金流和自由现金流改善。收入确认与现金到账存在时间差，利润增长不一定带来现金增长。"),
    ("debt_en", "Debt maturity ladder", "A large bond principal matures next year. Refinancing at higher yields raises interest expense. Limited unrestricted cash and weak interest coverage increase near-term liquidity risk."),
    ("debt_zh", "短期偿债压力", "一年内到期债务集中、可用现金不足，企业面临再融资压力。借新还旧的成本上升会侵蚀利息保障倍数，应检查现金余额与债务期限表。"),
    ("fx_zh", "汇率与海外收入", "美元走强时，海外收入换算为美元后的金额减少，拖累报表收入和利润。这是外币折算风险，不代表当地销量下降；远期外汇合约可以对冲部分现金流敞口。"),
    ("fx_en", "Currency hedging", "Foreign-exchange forwards can reduce forecast overseas cash-flow exposure. Translation losses from a stronger reporting currency can occur even if local-currency sales stay flat."),
    ("ai_en", "AI accelerator supply", "Demand for AI training accelerators exceeds available advanced packaging capacity. High-bandwidth memory supply and CoWoS packaging are bottlenecks, limiting shipments despite a strong order backlog."),
    ("ai_zh", "算力供应瓶颈", "人工智能加速卡订单充足，但先进封装与高带宽内存供应有限，短期出货受产能约束。若封装扩产到位，交付能力才可能改善。"),
    ("options_zh", "期权隐含波动率", "财报前期权隐含波动率上升会推高权利金，财报落地后可能出现波动率回落。即使股票方向判断正确，买入期权仍可能因隐含波动率骤降而亏损。"),
    ("inventory_en", "Inventory obsolescence", "Finished-goods inventory grew faster than sales. Older products require discounting, and potential write-downs can reduce gross margin. Rising inventory days are an early warning of weak demand."),
    ("buyback_zh", "回购与每股收益", "公司回购并注销股份后，流通股数下降。在净利润不变时，每股收益仍会上升，因此应区分经营利润增长与股本缩减带来的每股收益增长。"),
    ("oil_en", "Oil storage", "Crude oil inventories increased after temporary refinery maintenance reduced feedstock demand. Shipping delays also shifted weekly stock levels."),
    ("bank_zh", "银行净息差", "银行存款成本上升快于贷款收益率时，净息差收窄。资产质量恶化还可能增加信用减值损失，压低净利润。"),
]

CASES = [
    ("zh_cashflow", "回收逾期应收款为什么能改善企业现金创造能力？", {"cashflow_en": 3, "cashflow_zh": 3}),
    ("en_cashflow", "Why can faster collection of trade receivables improve free cash flow without revenue growth?", {"cashflow_en": 3, "cashflow_zh": 3}),
    ("zh_refinancing", "债务集中到期而手头现金有限，会产生哪些再融资与利息风险？", {"debt_en": 3, "debt_zh": 3}),
    ("en_currency", "How can a stronger dollar hurt reported overseas revenue even when local sales do not decline?", {"fx_zh": 3, "fx_en": 2}),
    ("zh_accelerators", "AI加速卡订单很多，为什么仍可能无法及时交付？请解释HBM和封装限制。", {"ai_en": 3, "ai_zh": 3}),
    ("en_options", "Why can a long option lose money after earnings even if the stock moves in the expected direction?", {"options_zh": 3}),
    ("zh_inventory", "存货增速持续超过销售，旧产品积压会如何影响毛利率？", {"inventory_en": 3}),
    ("en_buyback", "Can earnings per share rise with flat net income after a share repurchase?", {"buyback_zh": 3}),
]


class ObservedEmbedding(EmbeddingService):
    """只记录真实调用的数量和耗时，不替换模型或响应。"""

    def __init__(self):
        super().__init__(force_backend="remote_api")
        self.calls: list[dict[str, Any]] = []

    def encode(self, texts):
        batch = list(texts)
        started = time.perf_counter()
        record = {"texts": len(batch), "characters": sum(map(len, batch))}
        try:
            result = super().encode(batch)
            record.update(status="ok", model=result.model_name, dimensions=result.dim)
            return result
        except Exception as exc:
            record.update(status="failed", error_type=type(exc).__name__)
            raise
        finally:
            record["elapsed_seconds"] = round(time.perf_counter() - started, 4)
            self.calls.append(record)


class ObservedRAG(HybridRAGService):
    def hybrid_search_many(self, query, *, collections, top_k=6):
        started = time.perf_counter()
        self.last_candidates = super().hybrid_search_many(query, collections=collections, top_k=top_k)
        self.last_retrieval_seconds = time.perf_counter() - started
        return self.last_candidates


def metrics(source_ids, relevance, k=3):
    ids = source_ids[:k]
    recall = len(set(ids) & set(relevance)) / len(relevance)
    dcg = sum((2 ** relevance.get(sid, 0) - 1) / math.log2(rank + 2) for rank, sid in enumerate(ids))
    ideal = sum((2 ** grade - 1) / math.log2(rank + 2)
                for rank, grade in enumerate(sorted(relevance.values(), reverse=True)[:k]))
    return {"recall_at_3": round(recall, 4), "ndcg_at_3": round(dcg / ideal, 4)}


def load_settings(path, dsn_env):
    for key, value in dotenv_values(path).items():
        if value is not None and (key.startswith(("RAG_EMBEDDING_", "RAG_RERANK_")) or key == dsn_env):
            os.environ[key] = value
    os.environ["RAG_EMBEDDING"] = "remote_api"
    os.environ["RAG_RERANKER"] = "remote_api"


def local_test_dsn(name):
    dsn = os.getenv(name, "")
    url = make_url(dsn)
    if url.host not in {"localhost", "127.0.0.1", "::1"} or not any(
            part in (url.database or "").lower() for part in ("test", "eval", "live_vector")):
        raise ValueError("live_eval_requires_local_isolated_test_database")
    return dsn


def evaluate_long_document(service, embedder, owner, session, run_id):
    """在独立 collection 验证存量准备和新摄取，两条路径都调用真实托管向量。"""
    started = time.perf_counter()
    ticker = "LG" + run_id.upper()
    collection = build_stock_kb_collection(ticker)
    content = ("档案说明：本段完整保留中文、English、🙂和空白。\n" * 1300
               + "全文最后证据：ZEPHYR 2041 balloon maturity covenant 允许特殊分期偿债。")
    source_id = "eval:" + run_id + ":long-source"
    doc = RAGDocument(collection=collection, scope="persistent", source_id=source_id, content=content,
                      source="eval-filing", url="https://example.invalid/eval/long-source",
                      metadata={"owner": owner, "as_of": "2026-10-01", "synthetic_eval": True})
    # 模拟迁移前无分块原文；不请求整篇向量，准备操作必须显式完成。
    service._store.ingest_documents([doc], embed=False)
    original = service.read_document(collection=collection, source_id=source_id)
    before_calls = len(embedder.calls)
    prepared = service.prepare_long_documents(collection=collection)
    preparation_without_inference = before_calls == len(embedder.calls)
    updated = 0
    while True:
        batch = service.reindex_pending(collection=collection, batch_size=8)
        updated += batch["updated"]
        if batch["updated"] == 0:
            break
    parent = service.read_document(collection=collection, source_id=source_id)
    chunks = [service.read_document(collection=collection, source_id=row["source_id"])
              for row in prepared["chunk_inserts"]]
    allowed = {"index_state", "source_content_sha256", "chunk_strategy_version", "chunk_count"}
    knowledge = KnowledgeTools(owner, session, service=service)
    result = knowledge.search_knowledge("ZEPHYR 2041 balloon maturity covenant 特殊分期偿债", entity=ticker, limit=3)
    hit = next(row for row in result["hits"] if row["source_id"] == source_id)
    parts, offset = [], 0
    while True:
        read = knowledge.read_document(hit["document_id"], offset=offset, max_chars=12000)["document"]
        parts.append(read["content"])
        if not read["has_more"]:
            break
        offset = read["next_offset"]
    auto_content = "新摄取路径保留全文和中文🙂。\n" * 350
    service.ingest_documents([RAGDocument(collection=collection, scope="persistent",
        source_id=source_id + ":auto", content=auto_content, metadata={"owner": owner})])
    with service._store._engine.connect() as connection:
        evidence = dict(connection.execute(text("""
            SELECT count(*) FILTER (WHERE metadata->>'index_state'='source_document') AS sources,
                count(*) FILTER (WHERE metadata->>'index_state'='source_document' AND embedding IS NULL) AS source_null_vectors,
                count(*) FILTER (WHERE metadata->>'index_state' IS DISTINCT FROM 'source_document') AS indexable,
                count(*) FILTER (WHERE metadata->>'index_state' IS DISTINCT FROM 'source_document'
                    AND embedding IS NOT NULL AND vector_dims(embedding)=1024) AS real_vectors,
                max(octet_length(content)) FILTER (WHERE metadata->>'index_state' IS DISTINCT FROM 'source_document') AS max_chunk_bytes
            FROM rag_documents_v2 WHERE collection=:collection
        """), {"collection": collection}).mappings().one())
    checks = {"original_over_32000_chars": len(content) > 32000,
              "source_content_unchanged": parent["content"] == original["content"] == content,
              "source_metadata_whitelist_only": {k: v for k, v in parent["metadata"].items() if k not in allowed}
                  == {k: v for k, v in original["metadata"].items() if k not in allowed},
              "lossless_chunk_reconstruction": "".join(row["content"] for row in chunks) == content,
              "bounded_utf8_chunks": all(len(row["content"].encode("utf-8")) <= INDEX_CHUNK_MAX_BYTES for row in chunks),
              "prepare_without_inference": preparation_without_inference,
              "all_prepared_chunks_indexed": updated == prepared["created_chunks"],
              "parent_full_ticket_readback": "".join(parts) == content,
              "real_hybrid_and_rerank": hit["retrieval_method"] == "hybrid" and hit["rerank_used"],
              "sources_have_no_vectors": evidence["sources"] == evidence["source_null_vectors"] == 2,
              "all_index_units_real_1024": evidence["indexable"] == evidence["real_vectors"],
              "auto_ingestion_preserves_source": service.read_document(collection=collection, source_id=source_id + ":auto")["content"] == auto_content,
              "preparation_idempotent": service.prepare_long_documents(collection=collection)["prepared_sources"] == 0}
    return {"checks": checks, "characters": len(content), "utf8_bytes": len(content.encode("utf-8")),
            "prepared_chunks": prepared["created_chunks"], "postgres_evidence": evidence,
            "index_status": service.index_status(embedder.last_identity),
            "elapsed_seconds": round(time.perf_counter() - started, 4)}


def evaluate(args, report):
    load_settings(args.env_file, args.dsn_env)
    if args.db_env_file:
        database_dsn = dotenv_values(args.db_env_file).get(args.dsn_env)
        if not database_dsn:
            raise ValueError("live_eval_test_database_not_configured")
        os.environ[args.dsn_env] = database_dsn
    provider = HTTPEmbeddingProvider.from_env()
    reranker = HTTPRerankProvider.from_env()
    report.update(embedding_model=provider.model, dimension=provider.dimension, rerank_model=reranker.model)
    if provider.dimension != 1024:
        raise ValueError("live_eval_requires_1024_dimensions")
    embedder = ObservedEmbedding()
    dsn = local_test_dsn(args.dsn_env) if args.backend == "postgres" else None
    service = ObservedRAG(backend=args.backend, vector_dim=1024, rrf_k=60,
                          postgres_dsn=dsn, allow_memory_fallback=False, embedder=embedder)
    report["storage_backend"] = service.backend_name
    run_id = uuid.uuid4().hex[:10]
    ticker, owner, session = "EV" + run_id.upper(), "eval-alice-" + run_id, "eval-session-" + run_id
    collection = build_stock_kb_collection(ticker)
    working = build_thread_working_set_collection(session)
    source_prefix = "eval:" + run_id + ":"
    report["test_scope"] = {"run_id": run_id, "entity": ticker, "collections": [collection, working],
                            "source_prefix": source_prefix}

    def make_doc(sid, content, **changes):
        values = dict(collection=collection, scope="persistent", source_id=source_prefix + sid,
                      content=content, title=sid, url="https://example.invalid/eval/" + sid,
                      source="eval-filing", metadata={"visibility": "public", "as_of": "2026-10-01",
                                                      "synthetic_eval": True})
        values.update(changes)
        return RAGDocument(**values)

    documents = [make_doc(sid, content, title=title) for sid, title, content in CORPUS]
    documents.append(make_doc("current_ws", "Current user meeting note: review these synthetic materials.",
                              collection=working, scope="ephemeral", metadata={"owner": owner, "as_of": "2026-10-01"}))
    canary = "应收账款回收改善现金流。Faster receivable collection improves cash flow. "
    documents.extend([
        make_doc("denied_owner", canary + "private owner canary", metadata={"owner": "eval-bob", "visibility": "public", "as_of": "2026-10-01"}),
        make_doc("denied_expired", canary + "expired canary", expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
        make_doc("denied_unclassified", canary + "unclassified canary", metadata={"as_of": "2026-10-01"}),
        make_doc("denied_source", canary + "wrong source canary", source="eval-social"),
        make_doc("denied_date", canary + "old date canary", metadata={"visibility": "public", "as_of": "2020-01-01"}),
        make_doc("denied_entity", canary + "other entity canary", collection=build_stock_kb_collection("OTHER" + run_id.upper())),
        make_doc("denied_session", canary + "other session canary", collection=build_thread_working_set_collection("other-" + session)),
    ])
    started = time.perf_counter()
    report["ingestion"] = {**service.ingest_documents(documents), "elapsed_seconds": round(time.perf_counter() - started, 4)}
    report["embedding_identity"] = embedder.last_identity
    report["index_status"] = service.index_status(embedder.last_identity)
    report["checks"] = {"no_hash_fallback": not embedder.is_hash_fallback and embedder.model_name == provider.model,
                         "semantic_index_complete": report["index_status"]["pending"] == 0}
    if dsn:
        # 通过独立连接确认提交后的真实向量，不依赖检索对象内的统计缓存。
        engine = create_engine(dsn, future=True)
        try:
            with engine.connect() as connection:
                version = connection.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
                persisted = connection.execute(text("""
                    SELECT count(*) AS documents, count(embedding) AS vectors,
                           array_agg(DISTINCT vector_dims(embedding)) AS dimensions,
                           array_agg(DISTINCT metadata->>'embedding_identity') AS identities
                    FROM rag_documents_v2 WHERE source_id LIKE :prefix
                """), {"prefix": source_prefix + "%"}).mappings().one()
                report["postgres_evidence"] = {"pgvector_version": version, **dict(persisted)}
                report["checks"]["pgvector_committed_vectors"] = (
                    bool(version) and persisted["documents"] == len(documents)
                    and persisted["vectors"] == len(documents)
                    and persisted["dimensions"] == [1024]
                    and persisted["identities"] == [embedder.last_identity])
        finally:
            engine.dispose()
    knowledge = KnowledgeTools(owner, session, service=service)
    allowed_ids = {source_prefix + sid for sid, _, _ in CORPUS} | {source_prefix + "current_ws"}
    report["queries"] = []
    for case_id, query, labels in CASES:
        started = time.perf_counter()
        result = knowledge.search_knowledge(query, entity=ticker, limit=3,
                                            sources=["eval-filing"],
                                            time_range={"start": "2026-01-01", "end": "2026-12-31"})
        elapsed = time.perf_counter() - started
        rows = result["hits"]
        relevance = {source_prefix + sid: grade for sid, grade in labels.items()}
        raw = service.last_candidates
        baseline = [row["source_id"] for row in raw if row["source_id"] in allowed_ids]
        read_checks = []
        for row in rows:
            read = knowledge.read_document(row["document_id"], max_chars=12000)
            original = next((doc for doc in documents if doc.source_id == row["source_id"]), None)
            read_checks.append(read["status"] == "ok" and original is not None
                               and read["document"]["source_id"] == original.source_id
                               and read["document"]["content"] == original.content
                               and read["document"]["url"] == original.url)
        entry = {"id": case_id, "query": query, "labels": labels, "status": result["status"],
                 "hybrid": metrics(baseline, relevance), "reranked": metrics([row["source_id"] for row in rows], relevance),
                 "hybrid_top3": [sid.removeprefix(source_prefix) for sid in baseline[:3]],
                 "reranked_top3": [{"id": row["source_id"].removeprefix(source_prefix), "score": row["rerank_score"]} for row in rows],
                 "elapsed_seconds": round(elapsed, 4), "retrieval_seconds": round(service.last_retrieval_seconds, 4),
                 "post_retrieval_seconds": round(elapsed - service.last_retrieval_seconds, 4),
                 "candidate_count": len(raw), "dense_candidate_count": sum(row.get("dense_rank") is not None for row in raw),
                 "lexical_candidate_count": sum(row.get("sparse_rank") is not None for row in raw),
                 "checks": {"semantic_used": bool(rows) and all(row["retrieval_method"] == "hybrid" for row in rows),
                            "rerank_used": result["quality"]["rerank_used"],
                            "scope_source_date_filters": all(row["source_id"] in allowed_ids for row in rows),
                            "source_ticket_readback": bool(rows) and all(read_checks)},
                 "limitations": result["quality"]["limitations"]}
        report["queries"].append(entry)
    ticket = knowledge.search_knowledge("meeting note", limit=1)["hits"][0]["document_id"]
    report["checks"]["cross_owner_ticket_denied"] = KnowledgeTools("eval-bob", "other", service=service).read_document(ticket)["status"] == "unavailable"
    report["checks"]["cross_session_ticket_denied"] = KnowledgeTools(owner, "other", service=service).read_document(ticket)["status"] == "unavailable"
    report["checks"]["current_working_set_readable"] = knowledge.read_document(ticket)["status"] == "ok"
    report["embedding_calls"] = embedder.calls
    report["checks"]["all_embedding_calls_real_and_successful"] = all(call["status"] == "ok" for call in embedder.calls)
    report["checks"]["no_local_ml_loaded"] = not any(name in sys.modules for name in ("torch", "FlagEmbedding", "sentence_transformers"))
    report["aggregate"] = {stage: {metric: round(mean(item[stage][metric] for item in report["queries"]), 4)
                                  for metric in ("recall_at_3", "ndcg_at_3")} for stage in ("hybrid", "reranked")}
    report["aggregate"]["mean_query_seconds"] = round(mean(item["elapsed_seconds"] for item in report["queries"]), 4)
    report["passed"] = all(report["checks"].values()) and all(all(item["checks"].values()) for item in report["queries"])
    report["passed"] = report["passed"] and report["aggregate"]["reranked"]["recall_at_3"] >= 0.875
    if args.include_long_document:
        report["long_document"] = evaluate_long_document(service, embedder, owner, session, run_id)
        report["passed"] = report["passed"] and all(report["long_document"]["checks"].values())
    report["limitations"] = ["小型合成金融语料，只验证链路与这些标注查询，不代表生产规模质量、性能或全部金融任务。",
                             "远程服务可能计费、限流或变更可用性；本报告不假定免费或无限额度。"]
    if args.backend == "memory":
        report["limitations"].append("本次使用内存存储，未覆盖真实 Postgres/pgvector。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("memory", "postgres"), default="postgres")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.runtime.local")
    parser.add_argument("--db-env-file", type=Path, help="单独保存测试数据库 DSN 的 env 文件")
    parser.add_argument("--dsn-env", default="FINSIGHT_LIVE_VECTOR_POSTGRES_DSN")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-long-document", action="store_true", help="额外验证真实 Postgres 长文准备、分块和原文回读")
    args = parser.parse_args()
    output = args.output or ROOT / ".omx/live-vector" / (args.backend + "-eval.json")
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "backend_requested": args.backend,
              "mode": "real_remote_embedding_hybrid_rerank", "passed": False}
    started = time.perf_counter()
    try:
        evaluate(args, report)
    except Exception as exc:
        # 异常正文可能含连接字符串或第三方响应，报告只记录类型。
        report["failure"] = {"error_type": type(exc).__name__, "phase": "live_eval"}
        report["passed"] = False
    report["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output), "passed": report["passed"],
                      "storage_backend": report.get("storage_backend"), "aggregate": report.get("aggregate"),
                      "failure": report.get("failure"), "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
