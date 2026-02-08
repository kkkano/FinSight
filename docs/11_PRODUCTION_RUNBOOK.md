# FinSight 生产部署 Runbook（LangGraph/LangChain）

> 最后更新：2026-02-06  
> 适用范围：当前 `main` 上的 LangGraph 单入口架构  
> SSOT：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`

## 1. 目标与边界

本 Runbook 只覆盖当前生产主链路：

- API 单入口：`POST /chat/supervisor`、`POST /chat/supervisor/stream`
- 编排内核：LangGraph（PolicyGate → Planner → ExecutePlan → Synthesize → Render）
- 会话与记忆：`session_id(thread_id)` + LangGraph checkpointer
- 前端入口：`/chat`、`/dashboard/:symbol`

不再把 legacy router/supervisor 作为生产主链路。

---

## 2. 发布门禁（必须全部通过）

在发布前，必须完成以下三项：

```bash
pytest -q backend/tests
npm run build --prefix frontend
npm run test:e2e --prefix frontend
```

失败即停止发布，不允许“带病上线”。

### 2.1 上线前 24h 检查（Freeze）

- 冻结 schema 变更，仅允许 hotfix（必须绑定 issue + reviewer + 回滚说明）。
- 冻结发布窗口内新增依赖/基础设施变更。
- 锁定发布目标 commit，并记录 Go/No-Go owner。

执行记录建议落盘到：

- `docs/release_evidence/<date>_go_live_drill/`

### 2.2 上线前 2h 检查（预发布冒烟 + DB 快照）

必须完成：

1) 全链路冒烟（`chat/report/workbench/dashboard`）
2) 数据库快照（checkpointer + report index）

快照建议动作：

- 生成快照文件（可落到非仓库追踪路径）
- 记录 `source/snapshot/size/sha256`
- 将清单写入 `db_snapshot_manifest.json`

### 2.3 灰度发布节奏与观察指标

发布节奏：

- T0：10% 灰度（观察 15 分钟）
- T+15：50% 灰度（观察 30 分钟）
- T+45：100% 全量

每阶段必须记录：

- 成功率
- 5xx 比例
- P95 延迟
- Citation Coverage（可引用 `retrieval_eval` gate 结果）

### 2.4 回滚触发阈值（固化）

- 5xx > 2% 且持续 5 分钟
- P95 延迟相对灰度基线翻倍且持续 10 分钟
- Citation Coverage < 0.95

满足任一条件即触发回滚。

### 2.5 回滚步骤（实操）

1. 应用回滚到上一稳定版本
2. 配置回滚（env/feature flags）
3. 数据回滚（必要时，基于快照）
4. 重新执行 Smoke 与指标校验

演练完成后必须保留：

- 触发条件
- 操作时间线
- 恢复耗时
- 验证结果

### 2.6 多 Endpoint 故障演练

至少覆盖以下场景：

- 主节点故障 -> 备节点接管
- 主节点冷却后恢复可选
- 失败与恢复均有可解释日志（不含明文 key）

### 2.7 会话隔离与安全终验

终验必须包含：

- API 鉴权校验（401/503 分支）
- 限流校验（429 + Retry-After）
- 会话隔离（跨会话不可引用）
- 脱敏校验（authorization/token/api_key/cookie）

### 2.8 可解释 Trace 人工抽样

抽样不少于 20 条真实请求，逐条检查：

- 在做什么（stage）
- 为什么做（message/reason）
- 下一步/结果（事件链可理解）

抽样覆盖率必须达到 100%。

---

## 3. 生产环境变量基线

### 3.1 核心运行变量

```env
# LangGraph 运行模式（生产建议）
LANGGRAPH_PLANNER_MODE=llm
LANGGRAPH_SYNTHESIZE_MODE=llm
LANGGRAPH_PLANNER_AB_ENABLED=false
LANGGRAPH_PLANNER_AB_SPLIT=50
LANGGRAPH_PLANNER_AB_SALT=planner-ab-v1
LANGGRAPH_EXECUTE_LIVE_TOOLS=true
LANGGRAPH_SHOW_EVIDENCE=false

# Checkpointer（生产必须持久化）
LANGGRAPH_CHECKPOINTER_BACKEND=sqlite
LANGGRAPH_CHECKPOINT_SQLITE_PATH=data/langgraph/checkpoints.sqlite
LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK=false

# 如果使用 Postgres checkpointer：
# LANGGRAPH_CHECKPOINTER_BACKEND=postgres
# LANGGRAPH_CHECKPOINT_POSTGRES_DSN=postgresql://user:pass@host:5432/db
# LANGGRAPH_CHECKPOINT_POSTGRES_PIPELINE=false
```

### 3.2 安全与限流

```env
API_AUTH_ENABLED=true
API_AUTH_KEYS=key1,key2

# CORS（生产禁止 * + credentials 组合）
CORS_ALLOW_ORIGINS=https://app.finsight.example.com
CORS_ALLOW_CREDENTIALS=false

# 鉴权开启时的公共路径白名单（默认不放行 /api/dashboard）
API_PUBLIC_PATHS=/health,/docs,/openapi.json,/redoc

RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=120
RATE_LIMIT_WINDOW_SECONDS=60

# 会话上下文回收（TTL + LRU）
SESSION_CONTEXT_TTL_MINUTES=240
SESSION_CONTEXT_MAX_THREADS=1000
```

### 3.3 运维可观测/调度

```env
LOG_LEVEL=INFO
ENABLE_LANGSMITH=false

PRICE_ALERT_SCHEDULER_ENABLED=false
NEWS_ALERT_SCHEDULER_ENABLED=false
```

按需开启调度，默认建议先关闭，待核心链路稳定后再开启。

---

## 4. 部署步骤

### 4.1 后端部署

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
```

准备 `.env`（或由外部 Secret 管理注入），然后启动：

```bash
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

生产禁止使用 `--reload`。

### 4.2 前端部署

```bash
npm ci --prefix frontend
npm run build --prefix frontend
```

前端运行时后端地址统一使用 `VITE_API_BASE_URL`（例如 `https://api.finsight.example.com`），避免源码硬编码。

将 `frontend/dist` 交给静态资源服务（Nginx/对象存储/CDN）。

---

## 5. 部署后验收（Smoke）

### 5.1 健康检查

```bash
curl http://localhost:8000/health
```

检查重点：

- `status` 为 `healthy` 或可接受的 `degraded`
- `components.langgraph_runner.status=ok`
- `components.checkpointer.backend` 非 `unknown`
- `components.checkpointer.persistent=true`（生产要求）

### 5.2 主链路 API

```bash
curl -X POST http://localhost:8000/chat/supervisor \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"分析苹果公司\",\"session_id\":\"smoke-session-1\"}"
```

验收点：

- 返回 `schema_version`、`contracts`
- 返回 `session_id`
- `classification.method=langgraph`

### 5.3 SSE 流式链路

```bash
curl -N -X POST http://localhost:8000/chat/supervisor/stream \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"生成投资报告\",\"session_id\":\"smoke-stream-1\",\"options\":{\"output_mode\":\"investment_report\"}}"
```

验收点：

- 持续收到 `data:` 事件
- 末尾出现 `type=done` 事件
- 包含 `contracts`、`session_id`、`graph.trace`

---

## 6. 可观测接口

- `GET /health`：组件状态与 checkpointer 元数据
- `GET /metrics`：Prometheus 指标（启用 metrics 时）
- `GET /diagnostics/orchestrator`：orchestrator 统计
- `GET /diagnostics/planner-ab`（别名：`/diagnostics/planner_ab`）：Planner A/B 请求量、fallback 率、平均 steps、重试统计

---

## 7. 回滚策略

### 7.1 快速回滚

1. 回滚到上一个已验证版本（代码与镜像一起回滚）  
2. 重启后端实例  
3. 立即执行第 5 节 Smoke

### 7.2 降级运行（临时止血）

如果上游 LLM/工具不稳定，可临时切换：

```env
LANGGRAPH_PLANNER_MODE=stub
LANGGRAPH_SYNTHESIZE_MODE=stub
LANGGRAPH_EXECUTE_LIVE_TOOLS=false
```

说明：这是功能降级，不是长期配置。

---

## 8. 常见故障处理

### 8.1 `ValueError: no active connection`

场景：多 event loop / reload / 测试环境切换导致 AsyncSqliteSaver 连接失效。  
处理：

- 使用当前版本（已实现 loop-scoped checkpointer/runner 重建）
- 生产环境禁用 `--reload`
- 若已出现，重启进程并复验 `/health`

### 8.2 `API auth enabled but no keys configured`

场景：`API_AUTH_ENABLED=true` 但未配置 `API_AUTH_KEYS`。  
处理：补齐 key 或临时关闭 `API_AUTH_ENABLED`。

### 8.3 `429 Rate limit exceeded`

场景：请求超出限流窗口。  
处理：调整 `RATE_LIMIT_PER_MINUTE` 或客户端限流重试策略。

---

## 9. 变更纪律

- 任何生产发布都必须附带：测试证据 + 本 Runbook 验收记录
- API/State/Trace 契约变更必须同步 `backend/contracts.py`
- 新增配置项必须补充到本 Runbook 与 `readme.md`/`readme_cn.md`

## 10. Checkpointer Cutover Drill (Postgres)

生产发布前必须执行一次 checkpointer 切换演练（sqlite -> postgres -> sqlite rollback）。

### 10.1 Drill Command

```bash
python scripts/checkpointer_switch_drill.py \
  --sqlite-path data/langgraph/checkpoints.sqlite \
  --postgres-dsn postgresql://<user>:<pass>@<host>:5432/<db> \
  --evidence-path docs/release_evidence/<date>_go_live_drill/checkpointer_switch_drill.json \
  --manifest-path docs/release_evidence/<date>_go_live_drill/db_snapshot_manifest.json
```

### 10.2 Pass Criteria

- `sqlite_precheck.status=pass`
- `postgres_cutover.status=pass`
- `sqlite_rollback.status=pass`
- `ok=true`

### 10.3 Evidence Binding

- 必须产出 `checkpointer_switch_drill.json`
- 必须在 `db_snapshot_manifest.json` 中追加 `type=checkpointer_cutover_drill` 条目
- Postgres DSN 仅允许脱敏后落盘（`postgresql://***@host:port/db`）

## 11. Retrieval Gate Evidence Binding

发布门禁必须使用 CI 生成的固定证据文件：

- `tests/retrieval_eval/reports/gate_summary.json`

要求：

- `gate.passed=true`
- `overall_metrics.citation_coverage >= 0.95`
- `overall_metrics.latency_p95_ms <= gate.thresholds.latency_p95_ms_max`

该文件由 `python tests/retrieval_eval/run_retrieval_eval.py --gate --report-prefix ci` 自动生成，并通过 CI artifacts 归档。


## 12. T4 Stability & Security Closure Automation

Use the integrated closure script to execute and archive T4 drills in one shot:

```bash
python scripts/t4_stability_security_closure.py
```

Optional:

```bash
python scripts/t4_stability_security_closure.py   --evidence-dir docs/release_evidence/<date>_go_live_drill   --gate-summary tests/retrieval_eval/reports/gate_summary.json
```

Script outputs:
- `gray_rollout_drill.json`
- `rollback_rehearsal.json`
- `llm_failover_drill.json`
- `security_final_checks.json`
- `t4_closure_summary.json`

Pass criteria (all must be true):
- rollout threshold gate pass (5xx <= 2%, P95 <= 2x baseline, citation coverage >= 0.95)
- rollback rehearsal pass (data restored + schema rollback verified)
- failover drill pass (backup takeover + primary recovery)
- security final checks pass (`pytest` bundle exit code 0)
