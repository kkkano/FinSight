# FinSight 贡献指南

更新时间：2026-07-16

本文说明当前收敛架构下的开发、测试和文档要求。运行时事实优先级为代码与测试，其次是 `README_CN.md`、`docs/01_ARCHITECTURE.md` 和对应专项文档。

## 1. 环境要求

| 工具 | 版本/要求 |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| pnpm | 9+ |
| PostgreSQL | Compose 提供或兼容的外部实例 |
| Docker Compose | 推荐用于完整本地环境 |

不要把真实 key、token、密码或生产连接串写入仓库。以 `.env.server.example` 为服务端配置模板，以 `.env.example` 为开发参考；真实值只放在未跟踪的环境文件或 Secret Manager。

## 2. 快速开始

### Docker Compose

```bash
cp .env.server.example .env.server
# 编辑未跟踪的 .env.server
docker compose --env-file .env.server config
docker compose --env-file .env.server up -d --build
```

默认入口：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

PostgreSQL 默认只暴露在 Compose 网络。应用不会在启动时创建核心表，必须先完成 Alembic migration。

### 手动启动后端

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 手动启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

### 关键配置类别

| 类别 | 代表变量 | 说明 |
|---|---|---|
| PostgreSQL | `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`FINSIGHT_POSTGRES_DSN` | 核心业务、checkpoint 与 RAG |
| LLM | `OPENAI_COMPATIBLE_API_KEY`、`OPENAI_COMPATIBLE_API_BASE`、`OPENAI_COMPATIBLE_MODEL` | ResearchAnalyst 与 PredictionAnalyst |
| 认证 | `SUPABASE_URL`、`SUPABASE_ANON_KEY`、`SUPABASE_AUTH_REQUIRED` | 生产必须启用强认证 |
| 行情/财务 | `FINNHUB_API_KEY`、`FMP_API_KEY`、`FRED_API_KEY` | 由统一 market data gateway 使用 |
| 搜索 | `TAVILY_API_KEY` | 带来源的研究证据 |
| Prediction | `PREDICTION_GENERATION_ENABLED`、`PREDICTION_RUN_TIMEOUT_SECONDS` | 显式异步 Prediction 闭环 |
| Monitor | `MONITOR_REALTIME_ENABLED` | 页面 lease 驱动的窄化实时动态 |

完整变量及默认值以 `.env.server.example` 和 `backend/config/settings.py` 为准。

## 3. 当前产品与架构边界

前端用户路径只保留：Welcome、Dashboard、Chat、History 和共享报告。Dashboard 提供真实行情、确定性指标、显式 AI Prediction 和页面 lease 动态；Chat 负责证据化问答/报告；History 汇总会话、报告与 Prediction/Outcome。

FastAPI 公共产品面固定为 9 个 Router：system、user、watchlist、conversation、market、execution、predictions、monitor、report。新增 Router 或 endpoint 前必须证明不能扩展现有领域，并继续满足 Router 不超过 9、公开 endpoint 不超过 35 的产品门禁。

LangGraph 主图固定为：

```text
prepare_context
  -> route_request
  -> collect_evidence
  -> analyze
  -> validate
  -> render
```

边界规则：

- `backend/graph/planning/` 负责确定性计划、依赖和工具选择。
- `backend/graph/policy/` 负责执行前的能力、证据和安全约束。
- `backend/graph/execution/` 负责 DAG 执行、collector 调用和证据采集。
- `backend/graph/synthesis/` 与 `backend/graph/renderers/` 只消费已采集证据。
- `backend/agents/` 中的 Price、News、Fundamental、Technical、Macro、Risk、Deep Search 是无 LLM 的内部 collector。
- 业务 LLM 角色只有 `ResearchAnalyst` 和 `PredictionAnalyst`。
- 核心持久化只写 PostgreSQL；同一 thread 记忆随 LangGraph checkpoint 保存。

禁止恢复旧产品页面、Agent 偏好、reflection/debate、第二套执行器、JSON/SQLite 核心写路径、运行时建表或 synthetic/mock OHLC。

## 4. 代码风格

### Python

- 公开函数应提供参数和返回值类型。
- API 输入使用 Pydantic v2 Schema；数据库结构使用 Alembic migration。
- 外部 I/O 必须有超时、稳定错误码和可观测字段。
- diagnostics 与 evidence 分离；失败文本不得进入事实证据池。
- 面向人的注释、日志和文档使用中文；标识符使用英文。
- 不在请求路径新增隐式全局状态或第二套配置源。

### TypeScript/React

- 保持 TypeScript strict 与不可变状态更新。
- 后端合同变化后重新生成 OpenAPI snapshot/schema，并同步消费测试。
- 使用现有 `fin-*` 设计令牌和 lucide 图标；不硬编码与主题冲突的颜色。
- 所有异步状态必须有成功、空、认证失败、可重试失败和终止状态，不能无限 spinner。
- 页面和控制在桌面与移动 viewport 都不得重叠或溢出。

## 5. 测试与验证

使用项目虚拟环境运行 Python 测试；全局 Python 可能缺少 Alembic 等依赖。

### 后端定向测试

```powershell
.venv\Scripts\python.exe -m pytest `
  backend/tests/test_wp6_graph_contract.py `
  backend/tests/test_policy_gate.py `
  backend/tests/test_memory_snapshot.py `
  backend/tests/test_market_data_gateway.py `
  backend/tests/test_prediction_service.py `
  backend/tests/test_monitor_realtime_cycle.py -q
```

根据改动边界增减文件，不要用无关全量测试代替定向定位。

### 后端全量与 golden

```powershell
.venv\Scripts\python.exe -m pytest backend/tests tests -q
.venv\Scripts\python.exe -m pytest tests/golden -q
```

只有确认合同变化符合规格时才重录 golden；不能为了变绿直接覆盖 snapshot。

### 前端

```bash
cd frontend
pnpm test:unit
pnpm lint
pnpm build
pnpm test:e2e
```

涉及交互时先运行相关 unit test，再用 Playwright 验证关键桌面/移动路径。

### API 与容器

```bash
docker compose --env-file .env.server config
docker compose --env-file .env.server build
```

OpenAPI 变化必须同步：

- `frontend/src/api/openapi.snapshot.json`
- `frontend/src/api/schema.d.ts`
- 对应 API client/contract 测试

## 6. 项目结构

```text
FinSight/
├── backend/
│   ├── api/                  # 9 个领域 Router 与应用装配
│   ├── graph/
│   │   ├── runner.py         # 六节点唯一主图
│   │   ├── nodes/            # 节点边界适配
│   │   ├── planning/         # 确定性计划与依赖
│   │   ├── policy/           # 能力、证据与安全约束
│   │   ├── execution/        # DAG、工具与 evidence pipeline
│   │   ├── synthesis/        # Claim/Task/报告合成
│   │   └── renderers/        # 最终回答形态
│   ├── agents/               # 无 LLM 的 evidence collectors
│   ├── dashboard/            # Dashboard snapshot 与 schema
│   ├── services/             # Prediction、Outcome、Monitor、Stores
│   ├── rag/                  # 当前 thread memory、working set、KB
│   ├── tools/                # 行情、财务、新闻、宏观、搜索工具
│   └── tests/                # 后端单元/集成测试
├── frontend/
│   ├── src/pages/            # Dashboard、History、Shared Report
│   ├── src/components/       # Chat、Dashboard、Report、Execution UI
│   ├── src/api/              # API client、SSE、OpenAPI schema
│   ├── src/hooks/            # Prediction、Chat、Monitor hooks
│   └── e2e/                  # Playwright 场景
├── migrations/               # Alembic revisions
├── scripts/                  # 基线、迁移、运维与评估脚本
├── tests/golden/             # 管线 golden contracts
├── docs/                     # 当前事实文档；历史位于 docs/archive
├── docker-compose.yml
├── Dockerfile
└── .env.server.example
```

## 7. 提交与 Pull Request

提交信息采用 Conventional Commits，例如：

```text
fix(prediction): preserve provider provenance in outcome runs
refactor(graph): remove legacy collector reflection path
docs(architecture): align six-node runtime contract
```

提交前确认：

- [ ] 保留了用户已有改动，没有无关格式化或重命名；
- [ ] 定向测试通过，必要的跨层/全量门禁通过；
- [ ] OpenAPI、前端类型与文档已同步；
- [ ] 没有 synthetic 行情、静默错误吞噬或运行时 DDL；
- [ ] 没有真实密钥、token、Cookie、生产地址或个人凭据；
- [ ] 未恢复被删除产品、旧节点、旧存储或重复 LLM 路径。

未经明确授权，不执行 Git commit、push、reset，也不变更生产环境。生产发布还必须遵守 [`docs/11_PRODUCTION_RUNBOOK.md`](docs/11_PRODUCTION_RUNBOOK.md) 的备份、迁移、canary、回滚和观察门禁。

## 8. 相关文档

- [`README_CN.md`](README_CN.md)
- [`docs/DOCS_INDEX.md`](docs/DOCS_INDEX.md)
- [`docs/01_ARCHITECTURE.md`](docs/01_ARCHITECTURE.md)
- [`docs/LANGGRAPH_FLOW.md`](docs/LANGGRAPH_FLOW.md)
- [`docs/06a_LANGGRAPH_DESIGN_SPEC.md`](docs/06a_LANGGRAPH_DESIGN_SPEC.md)
- [`docs/AGENTS_GUIDE.md`](docs/AGENTS_GUIDE.md)
- [`docs/11_PRODUCTION_RUNBOOK.md`](docs/11_PRODUCTION_RUNBOOK.md)
