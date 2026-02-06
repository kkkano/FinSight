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

---

## 3. 生产环境变量基线

### 3.1 核心运行变量

```env
# LangGraph 运行模式（生产建议）
LANGGRAPH_PLANNER_MODE=llm
LANGGRAPH_SYNTHESIZE_MODE=llm
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

RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=120
RATE_LIMIT_WINDOW_SECONDS=60
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
