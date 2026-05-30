# FinSight 贡献指南

感谢你对 FinSight 项目的关注。本文档描述了参与开发所需的环境配置、工作流规范与代码风格要求。

更新时间：2026-05-25

---

## 目录

- [快速开始](#快速开始)
- [开发工作流](#开发工作流)
- [代码风格](#代码风格)
- [测试要求](#测试要求)
- [Pull Request 流程](#pull-request-流程)
- [项目结构](#项目结构)
- [设计令牌](#设计令牌)

---

## 快速开始

### 环境要求

| 工具 | 版本 |
|------|------|
| Python | 3.11+ |
| Node.js | 18+ |
| pnpm | 9+ |
| Git | 2.40+ |
| Docker & Docker Compose | 推荐（一键部署） |

### 克隆仓库

```bash
git clone https://github.com/kkkano/FinSight.git
cd FinSight
```

### Docker 一键启动（推荐）

```bash
cp .env.server.example .env.server
# 编辑 .env.server，至少填入 OPENAI_COMPATIBLE_API_KEY
docker compose --env-file .env.server up -d --build
# 前端: http://localhost:5173
# 后端: http://localhost:8000
# PostgreSQL: localhost:5432
```

### 手动启动

#### 后端

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.server.example .env.server
# 编辑 .env.server，填入 API Key（至少需要 OPENAI_COMPATIBLE_API_KEY）

python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 前端

```bash
cd frontend
pnpm install
pnpm dev
# 打开 http://localhost:5173
```

### 环境变量

| 变量 | 是否必填 | 说明 |
|------|---------|------|
| `OPENAI_COMPATIBLE_API_KEY` | **必填** | 默认 LLM 端点 |
| `OPENAI_COMPATIBLE_API_BASE` | 推荐 | OpenAI-compatible base URL |
| `OPENAI_COMPATIBLE_MODEL` | 推荐 | 默认模型 ID |
| `FMP_API_KEY` | 推荐 | 财务数据（回退到 yfinance） |
| `FINNHUB_API_KEY` | 选填 | 实时行情、新闻 |
| `TAVILY_API_KEY` | 选填 | 网页搜索（回退到 DDG） |
| `FRED_API_KEY` | 选填 | 宏观经济数据 |

完整配置说明见 `.env.server.example`。

---

## 开发工作流

### 分支命名

基于主分支 `main` 创建特性分支，命名规范如下：

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feat/` | 新功能 | `feat/streaming-progress-bar` |
| `fix/` | 缺陷修复 | `fix/dark-mode-hover` |
| `docs/` | 文档更新 | `docs/agent-guide` |
| `refactor/` | 代码重构 | `refactor/split-report-view` |
| `test/` | 测试补充 | `test/planner-node-coverage` |
| `chore/` | 构建/工具链 | `chore/update-deps` |
| `release/` | 发版分支 | `release/v1.2.0` |

### 提交信息格式

遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>(<scope>): <description>

<optional body>
```

**type** 取值：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`perf`、`ci`、`style`

示例：

```
feat(intent-contract): add evidence-first facet decomposition
fix(policy-gate): keep SEC tools in valuation_compare_light floor
docs(readme): update architecture diagrams for request-frame model
```

### 开发循环

1. 从 `main` 拉取最新代码并创建分支
2. 编写/修改代码，保持小步提交
3. 本地运行测试并确认通过
4. 推送分支并创建 Pull Request

---

## 代码风格

### TypeScript（前端）

- 启用 `strict` 模式，ESLint 配置继承 `typescript-eslint` 推荐规则
- 使用**不可变模式**：始终创建新对象，禁止直接修改（mutation）
- 状态管理使用 Zustand，遵循 immutable update 模式
- 组件文件建议不超过 400 行；超出时拆分为子组件
- 函数体建议不超过 50 行
- 禁止提交 `console.log` 语句
- 禁止硬编码配置值，统一走环境变量或配置文件

```typescript
// 正确：不可变更新
function updateUser(user: User, name: string): User {
  return { ...user, name }
}

// 错误：直接修改
function updateUser(user: User, name: string): User {
  user.name = name  // 禁止
  return user
}
```

**Lint 检查：**

```bash
cd frontend
pnpm lint
```

### Python（后端）

- 使用 **ruff** 进行代码检查和格式化（兼容 black 风格）
- 类型注解：所有公开函数必须添加参数和返回值类型注解
- 数据模型统一使用 Pydantic v2
- 错误处理：所有外部调用（LLM、API、数据库）必须包含 try/except 和有意义的错误信息
- 输入校验：API 端点使用 Pydantic Schema 校验请求体
- 文件长度建议不超过 800 行

```python
# 正确：带类型注解和错误处理
async def fetch_price(ticker: str, source: str = "yfinance") -> PriceResult:
    try:
        result = await price_client.get(ticker, source=source)
        return PriceResult(ticker=ticker, price=result.close)
    except ExternalAPIError as e:
        logger.error("Price fetch failed: ticker=%s source=%s err=%s", ticker, source, e)
        raise PriceFetchError(f"Failed to fetch price for {ticker}") from e
```

---

## 测试要求

### 覆盖率要求

所有 PR 必须维持 **80% 以上**的测试覆盖率。新增功能必须附带相应测试。

### 后端测试（pytest）

```bash
# 核心管线测试
pytest -q backend/tests/test_understand_request.py backend/tests/test_langgraph_skeleton.py backend/tests/test_policy_gate.py

# 回复契约与证据隔离
pytest -q backend/tests/test_reply_contract_lanes.py backend/tests/test_evidence_diagnostics_gate.py

# 全量后端测试
python -m pytest backend/tests tests -q

# 带覆盖率
python -m pytest --cov=backend --cov-report=term-missing
```

### 聊天 UX 路由评估（100 条）

```bash
python scripts/chat_ux_router_eval.py --dataset tests/eval/chat_router_100.json --run-id local100
```

当前验收：100/100 PASS，覆盖 18 类场景。

### 端到端测试（Playwright）

```bash
cd frontend
pnpm exec playwright install   # 首次运行需安装浏览器
pnpm test:e2e
```

### 提交前检查清单

```bash
# 后端核心测试
pytest -q backend/tests/test_understand_request.py backend/tests/test_policy_gate.py backend/tests/test_reply_contract_lanes.py

# 前端构建
cd frontend && pnpm build

# 端到端
cd frontend && pnpm test:e2e
```

---

## Pull Request 流程

1. **创建 PR**：标题遵循 Conventional Commits 格式，描述中说明变更动机与影响范围
2. **自查清单**：
   - [ ] 本地测试全部通过
   - [ ] 无 `console.log` / `print` 调试语句残留
   - [ ] 无硬编码密钥或敏感信息
   - [ ] 新增公开函数有类型注解
   - [ ] 新增功能附带测试
   - [ ] 文档已同步更新（如涉及 API 变更或架构调整）
3. **代码评审**：至少一位成员 Approve 后方可合并
4. **合并策略**：优先使用 Squash Merge，保持主分支提交历史整洁

---

## 项目结构

```
FinSight/
├── backend/
│   ├── api/                    # FastAPI 路由（28 个路由模块）
│   │   ├── main.py             # 应用入口 + CORS + 生命周期
│   │   ├── chat_router.py      # POST /api/chat（SSE 流式）
│   │   ├── agent_router.py     # Agent 偏好设置 API
│   │   ├── dashboard_router.py # GET /api/dashboard + /insights
│   │   ├── conversation_router.py # 会话生命周期 API
│   │   ├── execution_router.py # POST /api/execute（工作台）
│   │   ├── research_router.py  # 研究模式 API
│   │   ├── alerts_router.py    # 预警推送
│   │   ├── portfolio_router.py # 持仓管理
│   │   ├── rebalance_router.py # 再平衡
│   │   ├── report_router.py    # 报告管理
│   │   ├── backtest_router.py  # 策略回测
│   │   ├── screener_router.py  # 智能选股
│   │   ├── cn_market_router.py # A 股/港股市场
│   │   ├── tools_router.py     # 工具清单
│   │   └── ...                 # system/user/market/config 等
│   ├── graph/                  # LangGraph 管线核心
│   │   ├── runner.py           # 图构建与 GraphRunner 入口
│   │   ├── state.py            # GraphState 定义
│   │   ├── intent_contract.py  # Evidence-first 意图合同
│   │   ├── request_frame.py    # 请求帧模型
│   │   ├── request_task_contract.py # 任务契约
│   │   ├── memory_scope.py     # 作用域化记忆
│   │   ├── capability_registry.py # 能力注册
│   │   ├── coverage_validator.py  # 覆盖率验证
│   │   ├── executor.py         # 计划执行器
│   │   ├── report_builder.py   # ReportIR 结构构建
│   │   ├── plan_ir.py          # 计划中间表示
│   │   ├── cancellation.py     # 取消令牌
│   │   ├── preference_timeouts.py # 用户超时偏好
│   │   ├── event_bus.py        # 事件总线
│   │   ├── trace.py            # 执行追踪
│   │   └── nodes/              # 27 个管线节点
│   │       ├── understand_request.py # 请求理解主节点（LLM router）
│   │       ├── chat_respond.py      # 纯社交快速通道
│   │       ├── conversation_router.py # 上下文路由
│   │       ├── policy_gate.py       # 策略门控 + 证据最低依赖
│   │       ├── planner_stub.py      # 契约驱动规划回退
│   │       ├── chat_renderer.py     # 对话/对比渲染
│   │       ├── synthesize.py        # 合成 + 冲突检测 + 幻觉洗涤
│   │       ├── compare_gate.py      # 对比证据门控
│   │       ├── execute_plan_stub.py # 计划执行
│   │       ├── build_initial_state.py
│   │       ├── reset_turn_state.py
│   │       ├── prepare_context.py
│   │       ├── alert_extractor.py / alert_action.py
│   │       ├── confirmation_gate.py
│   │       ├── planner.py          # LLM 规划器
│   │       └── ...                 # resolve_subject/clarify 等兼容节点
│   ├── agents/                 # 7 个研究智能体 + 基类
│   │   ├── base_agent.py       # BaseFinancialAgent（反思循环 + configure_research）
│   │   ├── price_agent.py      # 11 源价格级联
│   │   ├── news_agent.py       # 新闻 + 情绪 + 信源评分
│   │   ├── fundamental_agent.py # 财报 + 估值
│   │   ├── technical_agent.py  # 技术指标计算
│   │   ├── macro_agent.py      # FRED + 宏观情绪
│   │   ├── risk_agent.py       # 风险评估
│   │   └── deep_search_agent.py # Self-RAG 多引擎搜索
│   ├── tools/                  # 26 个工具模块
│   │   ├── manifest.py         # 工具清单（含 market 标注）
│   │   ├── price.py            # 价格（11 源级联）
│   │   ├── financial.py        # 财务报表
│   │   ├── technical.py        # 技术指标
│   │   ├── news.py             # 新闻获取
│   │   ├── macro.py / macro_official.py # 宏观经济
│   │   ├── search.py           # 多引擎搜索
│   │   ├── sec.py / sec_holdings.py # SEC EDGAR + 持仓
│   │   ├── earnings_transcripts.py  # 财报电话会
│   │   ├── local_disclosure.py      # 非美市场公告
│   │   ├── authoritative_feeds.py   # 权威信息源
│   │   ├── cn_market_flow.py / cn_market_board.py / concept_map.py # A 股工具
│   │   ├── screener.py         # 选股工具
│   │   ├── fmp.py              # FMP API
│   │   ├── web.py / http.py / jina_reader.py / wayback.py # 网页工具
│   │   └── env.py / utils.py   # 环境与工具
│   ├── dashboard/              # 仪表盘数据 & AI 洞察
│   │   ├── data_service.py     # yfinance/FMP 数据获取
│   │   ├── cache.py            # DashboardCache（16 类 TTL）
│   │   ├── insights_engine.py  # 5 个洞察评分器编排
│   │   ├── insights_scorer.py  # 确定性评分回退
│   │   └── schemas.py          # Pydantic Schema
│   ├── rag/                    # 混合 RAG 引擎
│   │   ├── hybrid_service.py   # 内存 + Postgres 后端
│   │   ├── embedder.py         # bge-m3 嵌入服务
│   │   ├── reranker.py         # bge-reranker-v2-m3
│   │   ├── rag_router.py       # 查询路由
│   │   └── chunker.py          # 文档切片策略
│   ├── config/                 # Ticker 映射、市场配置
│   ├── conversation/           # 会话管理层
│   ├── orchestration/          # 编排层（预算、追踪）
│   ├── report/                 # 报告 IR、校验、引用
│   ├── research/               # 研究流程
│   ├── security/               # SSRF 防护
│   ├── services/               # 后台服务（预警调度、订阅、记忆）
│   ├── protocols/              # 协议定义
│   ├── prompts/                # 系统提示词
│   ├── utils/                  # 通用工具
│   └── tests/                  # 后端测试
├── frontend/
│   ├── src/
│   │   ├── api/client.ts       # API 客户端 + SSE parseSSEStream
│   │   ├── store/              # Zustand 状态管理
│   │   │   ├── useStore.ts     # 全局 Store（会话、认证）
│   │   │   ├── dashboardStore.ts  # 仪表盘状态
│   │   │   └── executionStore.ts  # 工作台执行状态
│   │   ├── components/
│   │   │   ├── dashboard/      # 仪表盘（6 标签页）
│   │   │   ├── settings/       # 设置面板（AgentControlPanel）
│   │   │   ├── SmartChart.tsx   # LLM 双模式智能图表
│   │   │   ├── ChatList.tsx     # 对话 + 内联图表
│   │   │   └── workbench/       # 工作台组件
│   │   ├── hooks/              # 自定义 React Hooks
│   │   └── types/              # TypeScript 类型定义
│   └── vite.config.ts
├── data/                       # 运行时数据存储
├── docs/                       # 技术文档（见 docs/DOCS_INDEX.md）
├── images/                     # 截图
├── scripts/                    # 运维与评估脚本
├── tests/                      # 回归测试与评估器
├── docker-compose.yml          # Docker 编排
├── Dockerfile                  # 后端镜像
├── requirements.txt            # Python 依赖
└── .env.server.example         # 环境变量模板
```

---

## 设计令牌

前端使用 `fin-*` 命名空间的 CSS 自定义属性作为设计令牌，定义于 `frontend/src/index.css`。所有组件必须使用这些令牌，禁止硬编码颜色值。

### 基础色板

| 令牌 | 浅色模式 | 深色模式 | 用途 |
|------|---------|---------|------|
| `--fin-bg` | `#f8fafc` | `#0f172a` | 页面背景 |
| `--fin-bg-secondary` | `#f1f5f9` | `#1e293b` | 次级背景 |
| `--fin-card` | `#ffffff` | `#1e293b` | 卡片背景 |
| `--fin-panel` | `#ffffff` | `#1e293b` | 面板背景 |
| `--fin-border` | `#e2e8f0` | `#334155` | 边框 |
| `--fin-hover` | `#eff6ff` | `#283548` | 悬停态 |

### 文本色

| 令牌 | 浅色模式 | 深色模式 | 用途 |
|------|---------|---------|------|
| `--fin-text` | `#1e293b` | `#f8fafc` | 主要文本 |
| `--fin-text-secondary` | `#64748b` | `#cbd5e1` | 次要文本 |
| `--fin-muted` | `#94a3b8` | `#64748b` | 弱化文本 |

### 语义色

| 令牌 | 值 | 用途 |
|------|-----|------|
| `--fin-primary` | `37 99 235` / `59 130 246` | 主色调 |
| `--fin-success` | `#10b981` | 涨幅/成功 |
| `--fin-danger` | `#ef4444` | 跌幅/错误 |
| `--fin-warning` | `#f59e0b` | 警告 |
| `--fin-predict` | `#8b5cf6` / `#a78bfa` | 预测/AI 相关 |

### 使用方式

```html
<div class="bg-fin-card border border-fin-border text-fin-text">
  <span class="text-fin-text-secondary">次要信息</span>
</div>
```

---

## 相关文档

- [README（EN）](README.md) / [README（中文）](README_CN.md)
- [文档索引](docs/DOCS_INDEX.md)
- [LangGraph 管线深度拆解](docs/LANGGRAPH_PIPELINE_DEEP_DIVE.md)
- [Agent 指南](docs/AGENTS_GUIDE.md)
- [生产运维手册](docs/11_PRODUCTION_RUNBOOK.md)
- [Dashboard 开发指南](docs/DASHBOARD_DEVELOPMENT_GUIDE.md)
- [幻觉抑制](docs/HALLUCINATION_MITIGATION.md)
