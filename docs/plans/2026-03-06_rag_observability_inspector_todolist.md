# DeepSearch / RAG 可观测性治理开发依据

更新时间：2026-03-06  
状态：开发中（P1-P4 首版已落地）  
适用范围：FinSight DeepSearch、RAG、检索诊断、运行态观测

---

## 1. 冻结决策

- [x] 观测数据统一落到同一个 `PostgreSQL`
- [x] 对所有登录用户开放全局只读能力
- [x] 默认保留 `30 天`
- [x] 删除策略采用“软删除 + 定时物理清理”
- [x] `RAG Inspector` 首页优先展示“最近查询回放”
- [x] 不引入新的独立向量数据库或独立 observability 数据库

---

## 2. 当前问题与根因

### 2.1 当前现象

- 看不到 DeepSearch 到底搜了什么
- 看不到向量库里到底存了什么
- 看不到怎么切片、切成了多少段、每段多长
- 看不到 dense / sparse / RRF / rerank 的排序变化
- 看不到什么时候从 `postgres` 降级成了 `memory`
- 本地即使没装 PostgreSQL 客户端，也没有浏览器内的可视化替代入口

### 2.2 已确认的代码事实

- 当前 RAG 主存储实现是 `PostgreSQL + pgvector`，表为 `rag_documents_v2`
- `/health` 只能看到 `backend`、`embedding_model`、`vector_dim`、`doc_count`
- DeepSearch 生产链路当前没有把 `chunk_document()` 真正接到主写库路径
- 当前查询过程里的 `rag_trace`、`rag_context` 只在运行时内存中短暂停留，没有形成可查询的持久化 trace

### 2.3 根因结论

问题不在“缺一个 Navicat”，而在“系统没有把检索过程建模成可持久化、可回放、可解释的数据对象”。

---

## 3. 目标架构

### 3.1 总体目标

建立一条完整的可观测链路：

`query -> evidence -> source_doc -> chunk -> vector_store -> retrieval_hits -> rerank_hits -> final_context -> replay_ui`

### 3.2 架构原则

- 只读可观测优先，不改写业务语义
- 用结构约束复杂度，而不是靠日志猜现场
- 同一个 `PostgreSQL` 承载业务 RAG 与观测 RAG，但表职责清晰分离
- 软删除保留审计面，物理清理由异步任务统一处理
- 前端先解决“能看懂”，再解决“更漂亮”

### 3.3 不变边界

- `rag_documents_v2` 继续承担向量检索主表职责
- 新增 observability 表，不直接替换 `rag_documents_v2`
- 所有新能力默认只读，不提供在线编辑向量库内容的 UI

---

## 4. PostgreSQL 表结构 SQL 草案

说明：以下为开发草案，主键统一使用应用层生成的 `TEXT` ID，避免额外依赖 `uuid-ossp` / `pgcrypto` 扩展。  
说明：所有观测表默认带软删除字段。  
说明：实际建表逻辑建议放入 `backend/rag/observability_store.py` 的 `ensure_schema()` 中，与现有 `rag_documents_v2` 自动建表风格保持一致。

### 4.1 查询主表 `rag_query_runs`

```sql
CREATE TABLE IF NOT EXISTS rag_query_runs (
    id                    TEXT PRIMARY KEY,
    user_id               TEXT NOT NULL,
    session_id            TEXT NOT NULL,
    thread_id             TEXT NULL,
    query_text            TEXT NOT NULL,
    query_text_redacted   TEXT NULL,
    query_hash            TEXT NOT NULL,
    route_name            TEXT NULL,
    router_decision       TEXT NULL,
    backend_requested     TEXT NOT NULL,
    backend_actual        TEXT NOT NULL,
    collection            TEXT NULL,
    retrieval_k           INTEGER NOT NULL DEFAULT 0,
    rerank_top_n          INTEGER NOT NULL DEFAULT 0,
    source_doc_count      INTEGER NOT NULL DEFAULT 0,
    chunk_count           INTEGER NOT NULL DEFAULT 0,
    retrieval_hit_count   INTEGER NOT NULL DEFAULT 0,
    rerank_hit_count      INTEGER NOT NULL DEFAULT 0,
    fallback_reason       TEXT NULL,
    status                TEXT NOT NULL DEFAULT 'running',
    error_message         TEXT NULL,
    started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at           TIMESTAMPTZ NULL,
    latency_ms            DOUBLE PRECISION NULL,
    deleted_at            TIMESTAMPTZ NULL,
    deleted_by            TEXT NULL,
    delete_reason         TEXT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('running', 'success', 'partial', 'failed', 'deleted')),
    CHECK (backend_requested IN ('postgres', 'memory', 'auto')),
    CHECK (backend_actual IN ('postgres', 'memory'))
);

CREATE INDEX IF NOT EXISTS idx_rag_query_runs_started_at
    ON rag_query_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_rag_query_runs_user_id
    ON rag_query_runs(user_id);

CREATE INDEX IF NOT EXISTS idx_rag_query_runs_session_id
    ON rag_query_runs(session_id);

CREATE INDEX IF NOT EXISTS idx_rag_query_runs_status
    ON rag_query_runs(status);

CREATE INDEX IF NOT EXISTS idx_rag_query_runs_query_hash
    ON rag_query_runs(query_hash);

CREATE INDEX IF NOT EXISTS idx_rag_query_runs_deleted_at
    ON rag_query_runs(deleted_at);
```

### 4.2 查询事件流 `rag_query_events`

```sql
CREATE TABLE IF NOT EXISTS rag_query_events (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
    seq_no                INTEGER NOT NULL,
    event_type            TEXT NOT NULL,
    stage                 TEXT NOT NULL,
    payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at            TIMESTAMPTZ NULL,
    deleted_by            TEXT NULL,
    delete_reason         TEXT NULL,
    UNIQUE (run_id, seq_no)
);

CREATE INDEX IF NOT EXISTS idx_rag_query_events_run_id_seq
    ON rag_query_events(run_id, seq_no);

CREATE INDEX IF NOT EXISTS idx_rag_query_events_event_type
    ON rag_query_events(event_type);
```

建议事件类型：

- `query_received`
- `router_decided`
- `evidence_selected`
- `source_doc_created`
- `chunk_created`
- `retrieval_done`
- `rerank_done`
- `response_synthesized`
- `fallback_triggered`
- `run_completed`

### 4.3 原始文档表 `rag_source_docs`

```sql
CREATE TABLE IF NOT EXISTS rag_source_docs (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
    source_id             TEXT NOT NULL,
    source_type           TEXT NOT NULL,
    source_name           TEXT NULL,
    url                   TEXT NULL,
    title                 TEXT NULL,
    published_at          TIMESTAMPTZ NULL,
    content_raw           TEXT NOT NULL,
    content_preview       TEXT NULL,
    content_length        INTEGER NOT NULL DEFAULT 0,
    metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at            TIMESTAMPTZ NULL,
    deleted_by            TEXT NULL,
    delete_reason         TEXT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_rag_source_docs_run_id
    ON rag_source_docs(run_id);

CREATE INDEX IF NOT EXISTS idx_rag_source_docs_source_type
    ON rag_source_docs(source_type);

CREATE INDEX IF NOT EXISTS idx_rag_source_docs_deleted_at
    ON rag_source_docs(deleted_at);
```

### 4.4 切片表 `rag_chunks`

```sql
CREATE TABLE IF NOT EXISTS rag_chunks (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
    source_doc_id         TEXT NOT NULL REFERENCES rag_source_docs(id) ON DELETE CASCADE,
    chunk_index           INTEGER NOT NULL,
    total_chunks          INTEGER NOT NULL,
    chunk_text            TEXT NOT NULL,
    chunk_length          INTEGER NOT NULL,
    doc_type              TEXT NOT NULL,
    chunk_strategy        TEXT NOT NULL,
    chunk_size            INTEGER NOT NULL,
    chunk_overlap         INTEGER NOT NULL,
    char_start            INTEGER NULL,
    char_end              INTEGER NULL,
    metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at            TIMESTAMPTZ NULL,
    deleted_by            TEXT NULL,
    delete_reason         TEXT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_doc_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_run_id
    ON rag_chunks(run_id);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_doc_id
    ON rag_chunks(source_doc_id);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_type
    ON rag_chunks(doc_type);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_deleted_at
    ON rag_chunks(deleted_at);
```

### 4.5 召回明细表 `rag_retrieval_hits`

```sql
CREATE TABLE IF NOT EXISTS rag_retrieval_hits (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
    chunk_id              TEXT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
    collection            TEXT NULL,
    source_id             TEXT NULL,
    source_doc_id         TEXT NULL,
    scope                 TEXT NULL,
    dense_rank            INTEGER NULL,
    dense_score           DOUBLE PRECISION NULL,
    sparse_rank           INTEGER NULL,
    sparse_score          DOUBLE PRECISION NULL,
    rrf_score             DOUBLE PRECISION NULL,
    selected_for_rerank   BOOLEAN NOT NULL DEFAULT false,
    metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at            TIMESTAMPTZ NULL,
    deleted_by            TEXT NULL,
    delete_reason         TEXT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_retrieval_hits_run_id
    ON rag_retrieval_hits(run_id);

CREATE INDEX IF NOT EXISTS idx_rag_retrieval_hits_rrf_score
    ON rag_retrieval_hits(run_id, rrf_score DESC);

CREATE INDEX IF NOT EXISTS idx_rag_retrieval_hits_chunk_id
    ON rag_retrieval_hits(chunk_id);
```

### 4.6 重排明细表 `rag_rerank_hits`

```sql
CREATE TABLE IF NOT EXISTS rag_rerank_hits (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
    chunk_id              TEXT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
    input_rank            INTEGER NOT NULL,
    output_rank           INTEGER NOT NULL,
    rerank_score          DOUBLE PRECISION NULL,
    selected_for_answer   BOOLEAN NOT NULL DEFAULT false,
    metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at            TIMESTAMPTZ NULL,
    deleted_by            TEXT NULL,
    delete_reason         TEXT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, input_rank),
    UNIQUE (run_id, output_rank)
);

CREATE INDEX IF NOT EXISTS idx_rag_rerank_hits_run_id
    ON rag_rerank_hits(run_id);

CREATE INDEX IF NOT EXISTS idx_rag_rerank_hits_output_rank
    ON rag_rerank_hits(run_id, output_rank);
```

### 4.7 回退事件表 `rag_fallback_events`

```sql
CREATE TABLE IF NOT EXISTS rag_fallback_events (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
    reason_code           TEXT NOT NULL,
    reason_text           TEXT NULL,
    backend_before        TEXT NULL,
    backend_after         TEXT NOT NULL,
    payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at            TIMESTAMPTZ NULL,
    deleted_by            TEXT NULL,
    delete_reason         TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_fallback_events_created_at
    ON rag_fallback_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rag_fallback_events_run_id
    ON rag_fallback_events(run_id);
```

### 4.8 访问审计表 `rag_access_audit_logs`

```sql
CREATE TABLE IF NOT EXISTS rag_access_audit_logs (
    id                    TEXT PRIMARY KEY,
    viewer_user_id        TEXT NOT NULL,
    resource_type         TEXT NOT NULL,
    resource_id           TEXT NOT NULL,
    action                TEXT NOT NULL,
    payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_access_audit_logs_viewer
    ON rag_access_audit_logs(viewer_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rag_access_audit_logs_resource
    ON rag_access_audit_logs(resource_type, resource_id, created_at DESC);
```

### 4.9 与 `rag_documents_v2` 的回链约定

不改表结构的最小实现方案：

- 在 `rag_documents_v2.metadata` 中补充以下字段：
  - `run_id`
  - `source_doc_id`
  - `chunk_id`
  - `doc_type`
  - `chunk_index`
  - `total_chunks`
  - `chunk_strategy`

这样 Inspector 可以从向量库记录直接回跳到观测明细，不必第一版就给 `rag_documents_v2` 加新列。

### 4.10 留存与清理 SQL 草案

```sql
-- A. 超过 30 天的已完成 run，先软删除
UPDATE rag_query_runs
SET deleted_at = now(),
    delete_reason = 'retention_expired',
    status = CASE WHEN status = 'deleted' THEN status ELSE 'deleted' END,
    updated_at = now()
WHERE finished_at IS NOT NULL
  AND finished_at < now() - interval '30 days'
  AND deleted_at IS NULL;

-- B. 级联软删除关联表
UPDATE rag_source_docs
SET deleted_at = now(),
    delete_reason = COALESCE(delete_reason, 'parent_run_deleted'),
    updated_at = now()
WHERE run_id IN (
    SELECT id FROM rag_query_runs WHERE deleted_at IS NOT NULL
)
  AND deleted_at IS NULL;

UPDATE rag_chunks
SET deleted_at = now(),
    delete_reason = COALESCE(delete_reason, 'parent_run_deleted'),
    updated_at = now()
WHERE run_id IN (
    SELECT id FROM rag_query_runs WHERE deleted_at IS NOT NULL
)
  AND deleted_at IS NULL;

UPDATE rag_retrieval_hits
SET deleted_at = now(),
    delete_reason = COALESCE(delete_reason, 'parent_run_deleted')
WHERE run_id IN (
    SELECT id FROM rag_query_runs WHERE deleted_at IS NOT NULL
)
  AND deleted_at IS NULL;

UPDATE rag_rerank_hits
SET deleted_at = now(),
    delete_reason = COALESCE(delete_reason, 'parent_run_deleted')
WHERE run_id IN (
    SELECT id FROM rag_query_runs WHERE deleted_at IS NOT NULL
)
  AND deleted_at IS NULL;

UPDATE rag_query_events
SET deleted_at = now(),
    delete_reason = COALESCE(delete_reason, 'parent_run_deleted')
WHERE run_id IN (
    SELECT id FROM rag_query_runs WHERE deleted_at IS NOT NULL
)
  AND deleted_at IS NULL;

-- C. 已软删除 30 天以上的物理清理
DELETE FROM rag_query_runs
WHERE deleted_at IS NOT NULL
  AND deleted_at < now() - interval '30 days';
```

---

## 5. 后端接口草案

说明：以下接口全部为“登录后可访问、全局只读”。  
说明：首版不做行级过滤。  
说明：默认所有列表接口都支持 `limit`、`cursor`、`from`、`to`、`include_deleted`。

### 5.1 状态总览

- [ ] `GET /diagnostics/rag/status`
  - 用途：查看当前 RAG 后端状态与最近观测状态
  - 返回：
    - `backend_requested`
    - `backend_actual`
    - `doc_count`
    - `vector_dim`
    - `recent_run_count_24h`
    - `recent_fallback_count_24h`
    - `recent_empty_hits_rate_24h`
    - `last_run_at`
    - `last_fallback_at`

### 5.2 最近查询回放

- [ ] `GET /diagnostics/rag/runs`
  - 用途：首页最近查询回放列表
  - 查询参数：`q`、`status`、`backend`、`fallback_only`、`high_latency_only`

- [ ] `GET /diagnostics/rag/runs/{run_id}`
  - 用途：单次查询总览详情

- [ ] `GET /diagnostics/rag/runs/{run_id}/events`
  - 用途：时间线回放

- [ ] `GET /diagnostics/rag/runs/{run_id}/documents`
  - 用途：查看本次查询用到了哪些原始文档

- [ ] `GET /diagnostics/rag/runs/{run_id}/chunks`
  - 用途：查看切片明细
  - 查询参数：`source_doc_id`、`doc_type`

- [ ] `GET /diagnostics/rag/runs/{run_id}/hits`
  - 用途：查看 dense / sparse / RRF / rerank 明细

### 5.3 Collection 浏览

- [ ] `GET /diagnostics/rag/collections`
  - 用途：浏览当前向量库中的 collection 概览

- [ ] `GET /diagnostics/rag/collections/{collection}/documents`
  - 用途：查看 collection 内文档列表

- [ ] `GET /diagnostics/rag/collections/{collection}/chunks`
  - 用途：查看 collection 内 chunk 列表

### 5.4 调试预览

- [ ] `POST /diagnostics/rag/search-preview`
  - 用途：输入 query + collection，预览召回与分数，不写入正式运行记录
  - 返回：dense / sparse / RRF / rerank 对比结果

### 5.5 软删除

- [ ] `DELETE /diagnostics/rag/runs/{run_id}`
  - 用途：软删除单次运行记录

- [ ] `DELETE /diagnostics/rag/source-docs/{source_doc_id}`
  - 用途：软删除原始文档记录

---

## 6. 后端文件清单

### 6.1 需要新增的后端文件

- [x] `backend/rag/observability_models.py`
  - 职责：定义 `QueryRun`、`QueryEvent`、`SourceDoc`、`ChunkRecord`、`RetrievalHit`、`RerankHit`、`FallbackEvent` 数据结构

- [x] `backend/rag/observability_store.py`
  - 职责：建表、写入、查询、软删除、30 天清理

- [x] `backend/rag/observability_runtime.py`
  - 职责：提供 observability 运行时 store 基类、基础 SQL 读写方法与读侧查询能力

- [ ] `backend/tests/test_rag_observability_schema.py`
  - 职责：验证表结构与索引初始化

- [ ] `backend/tests/test_rag_chunk_pipeline.py`
  - 职责：验证真实生产链路已接入 `chunk_document()`

- [x] `backend/tests/test_rag_observability_system_router.py`
  - 职责：验证 `/diagnostics/rag/*` 读侧路由的基础返回形状

- [ ] `backend/tests/test_rag_retention_cleanup.py`
  - 职责：验证软删除与 30 天物理清理

- [x] `backend/tests/test_rag_observability_auth.py`
  - 职责：验证登录态访问、只读边界与内部 key 的 mutation 边界

### 6.2 需要修改的后端文件

- [x] `backend/api/main.py`
  - 修改点：在启动阶段初始化 observability schema，并补 `Bearer` 登录态校验、只读收口与 retention 调度

- [x] `backend/api/system_router.py`
  - 修改点：补充 `/health` 中最近一次 RAG run / fallback 的观测字段

- [ ] `backend/rag/hybrid_service.py`
  - 修改点：
    - 为 `rag_documents_v2.metadata` 补 `run_id` / `source_doc_id` / `chunk_id`
    - 在检索结果中保留回链标识，便于 Inspector 跳转

- [ ] `backend/rag/chunker.py`
  - 修改点：补充 `chunk_strategy` / `char_start` / `char_end` 支撑信息

- [x] `backend/graph/nodes/execute_plan_stub.py`
  - 修改点：
    - 生成 `run_id`
    - 持久化 `query_run`
    - 持久化 `source_docs`
    - 真正调用 `chunk_document()`
    - 持久化 `chunks`
    - 持久化 `retrieval_hits` / `rerank_hits`
    - 持久化 `query_events`

### 6.3 可选新增文件

- [ ] `backend/services/rag_retention.py`
  - 职责：封装定时软删除与物理清理逻辑

- [ ] `backend/api/rag_diagnostics_schemas.py`
  - 职责：集中定义 Pydantic 响应模型，避免 router 过胖

---

## 7. 前端页面文件清单

### 7.1 需要新增的前端文件

- [x] `frontend/src/pages/RagInspectorPage.tsx`
  - 职责：RAG Inspector 主页面，首页默认展示最近查询回放

- [ ] `frontend/src/components/rag-inspector/RecentRunsPanel.tsx`
  - 职责：左侧最近查询列表

- [ ] `frontend/src/components/rag-inspector/RunReplayTimeline.tsx`
  - 职责：查询过程事件时间线

- [ ] `frontend/src/components/rag-inspector/RunSummaryCard.tsx`
  - 职责：展示 query、backend、collection、耗时、命中数

- [ ] `frontend/src/components/rag-inspector/HitScoreTable.tsx`
  - 职责：展示 dense / sparse / RRF / rerank 分数表

- [ ] `frontend/src/components/rag-inspector/DocumentChunkExplorer.tsx`
  - 职责：查看 source doc 与 chunk 明细

- [ ] `frontend/src/components/rag-inspector/CollectionBrowser.tsx`
  - 职责：按 collection 浏览当前向量库内容

- [ ] `frontend/src/components/rag-inspector/FallbackBanner.tsx`
  - 职责：高亮显示 `postgres -> memory` 降级

- [ ] `frontend/src/components/rag-inspector/RagStatusStrip.tsx`
  - 职责：顶部展示 doc_count、vector_dim、最近 fallback、最近 run 状态

- [ ] `frontend/src/components/rag-inspector/RagFiltersBar.tsx`
  - 职责：提供时间范围、状态、fallback only 等过滤器

- [ ] `frontend/src/hooks/useRagDiagnostics.ts`
  - 职责：统一封装诊断接口调用与缓存

- [ ] `frontend/src/types/ragDiagnostics.ts`
  - 职责：统一定义前端类型

### 7.2 需要修改的前端文件

- [x] `frontend/src/App.tsx`
  - 修改点：新增 `/rag-inspector` 路由，并接入 `AuthenticatedGuard`

- [x] `frontend/src/api/client.ts`
  - 修改点：新增 `diagnosticsRagStatus()`、`diagnosticsRagRuns()`、`diagnosticsRagRunDetail()` 等接口方法，并透传 Supabase `Authorization` 头

- [x] `frontend/src/components/Sidebar.tsx`
  - 修改点：增加 `RAG 观测` 入口

### 7.3 首页信息架构

- [ ] 默认 Tab：`最近查询回放`
- [ ] 第二 Tab：`命中明细`
- [ ] 第三 Tab：`文档与切片`
- [ ] 第四 Tab：`Collection 浏览`
- [ ] 第五 Tab：`评测与漂移`

---

## 8. 分阶段开发 TODO

### P0：基线对齐

- [ ] 明确 `run_id` / `source_doc_id` / `chunk_id` 的 ID 生成规则
- [ ] 明确 `query_text` 脱敏策略与 `query_text_redacted` 的生成规则
- [x] 明确 `RAG Inspector` 只读权限接入点

### P1：数据库与持久化层

- [x] 新建 observability store 与建表逻辑
- [x] 在应用启动时自动初始化 observability schema
- [x] 加入软删除与保留期清理能力（已接入清理基础能力与生命周期定时调度）

### P2：DeepSearch 主链路接通

- [x] 在 `execute_plan_stub.py` 中生成 `run_id`
- [x] 持久化 `rag_query_runs`
- [x] 持久化 `rag_source_docs`
- [x] 用 `chunk_document()` 产出真实 `rag_chunks`
- [ ] 将 chunk 与 `rag_documents_v2` 回链
- [x] 持久化 `rag_retrieval_hits`
- [ ] 持久化 `rag_rerank_hits`
- [x] 持久化 `rag_query_events`

### P3：后端诊断 API

- [x] 实现 `status`
- [x] 实现 `runs`
- [x] 实现 `run detail`
- [x] 实现 `events`
- [x] 实现 `documents`
- [x] 实现 `chunks`
- [x] 实现 `hits`
- [x] 实现 `collections`
- [x] 实现 `search-preview`
- [x] 实现软删除接口

### P4：前端 RAG Inspector

- [x] 新增 `/rag-inspector` 路由
- [x] 新增左侧最近查询回放列表
- [x] 新增时间线回放
- [x] 新增分数表
- [x] 新增文档与切片浏览器
- [x] 新增 collection 浏览器
- [ ] 新增 fallback 横幅与状态条（当前已有 fallback 状态卡与提示，专用横幅待补）

### P5：指标、评测、告警

- [ ] 接入 retrieval eval 结果展示
- [ ] 增加 RAG 观测相关 metrics
- [ ] 为 fallback / 空召回 / 高延迟建立告警阈值

### P6：测试与验收

- [x] 单元测试通过
- [ ] 集成测试通过
- [x] 登录态访问控制验证通过
- [ ] 30 天软删除 + 物理清理演练通过
- [ ] 首页能直接回放最近查询
- [ ] 不装 PostgreSQL 客户端也能完成日常排障

---

## 9. 验收标准（DoD）

- [ ] 用户打开 `/rag-inspector` 就能看到最近 DeepSearch 查询列表
- [ ] 点开任意一次查询，能看到：
  - [ ] 原始 query
  - [ ] router 决策
  - [ ] backend 实际值
  - [ ] source docs
  - [ ] chunk 明细
  - [ ] dense / sparse / RRF / rerank 分数变化
  - [ ] 最终写入答案上下文的结果
- [ ] 用户无需安装 PostgreSQL 客户端也能完成排障
- [ ] `postgres -> memory` fallback 能被直接看见
- [ ] 30 天内记录可回放，30 天后自动清理

---

## 10. 代码落点速查表

### 10.1 后端

| 类型 | 文件 | 角色 |
|---|---|---|
| 现有 | `backend/api/main.py` | 注册新 router、启动时建表 |
| 现有 | `backend/api/system_router.py` | 补 `/health` 观测摘要 |
| 现有 | `backend/rag/hybrid_service.py` | 向量库回链、结果携带关联 ID |
| 现有 | `backend/rag/chunker.py` | 真实切片元数据补齐 |
| 现有 | `backend/graph/nodes/execute_plan_stub.py` | 查询 run / doc / chunk / hit 持久化主入口 |
| 新增 | `backend/rag/observability_models.py` | 观测实体模型 |
| 新增 | `backend/rag/observability_store.py` | 建表、读写、清理 |
| 新增 | `backend/rag/observability_runtime.py` | 观测运行态基础 store 与读侧查询支撑 |

### 10.2 前端

| 类型 | 文件 | 角色 |
|---|---|---|
| 现有 | `frontend/src/App.tsx` | 注册 `/rag-inspector` |
| 现有 | `frontend/src/api/client.ts` | 新增 RAG diagnostics 请求方法 |
| 现有 | `frontend/src/components/Sidebar.tsx` | 新增导航入口 |
| 新增 | `frontend/src/pages/RagInspectorPage.tsx` | 主页面 |
| 新增 | `frontend/src/components/rag-inspector/RecentRunsPanel.tsx` | 最近查询列表 |
| 新增 | `frontend/src/components/rag-inspector/RunReplayTimeline.tsx` | 时间线回放 |
| 新增 | `frontend/src/components/rag-inspector/HitScoreTable.tsx` | 分数对比 |
| 新增 | `frontend/src/components/rag-inspector/DocumentChunkExplorer.tsx` | 文档 / chunk 浏览 |
| 新增 | `frontend/src/components/rag-inspector/CollectionBrowser.tsx` | collection 浏览 |

---

## 11. 实施原则

- [ ] 先把“看得见”做对，再谈“看起来舒服”
- [ ] 先做只读观测，不做在线修改
- [ ] 优先消灭“切片不可见”这种结构性盲区
- [ ] 一切可回放的数据对象都必须有稳定 ID
- [ ] 每做完一个阶段，就在本文档中手动打勾更新

---

## 12. 文档维护约定

- [ ] 本文档是后续开发依据，开发过程中按阶段勾选
- [ ] 若 SQL 草案、接口路径、文件清单发生变化，优先更新本文档
- [ ] 每完成一个大阶段，在文末补一段简短变更记录

### 变更记录

- 2026-03-06：创建初版开发依据，冻结 PostgreSQL / 全局只读 / 30 天 / 软删除 / 最近查询回放 五项核心决策。
- 2026-03-06：落地首版 observability：完成 store/schema 初始化、`execute_plan_stub.py` 写侧持久化、`/diagnostics/rag/*` 读侧接口、`/rag-inspector` 页面与基础测试。
- 2026-03-06：补齐 retention lifecycle 调度，应用启动后会按间隔自动执行 observability 30 天清理任务。
- 2026-03-06：补齐后端登录鉴权收口：`/diagnostics/rag/*` 读接口要求登录态，soft-delete mutation 仅允许内部 API key，并补只读权限回归测试。
- 2026-03-07：补齐 `docker-compose.yml` / `.env.server.example` 的 Supabase 后端配置说明，新增 `scripts/verify_rag_observability_auth.ps1`，并用本地最小鉴权服务完成 curl 验证（401/200/403/200）。
- 2026-03-07：补齐本地联调方案：新增 RAG Inspector 开发态 bearer token 配置与前端“开发模式进入 RAG Inspector”，同时明确匿名入口不会访问受保护的 `/rag-inspector`。
