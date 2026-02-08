# FinSight 贡献指南

感谢你对 FinSight 项目的关注。本文档描述了参与开发所需的环境配置、工作流规范与代码风格要求。

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
| Node.js | 20+ |
| pnpm | 9+ |
| Git | 2.40+ |

### 克隆仓库

```bash
git clone https://github.com/<org>/FinSight.git
cd FinSight
```

### 后端配置

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 前端配置

```bash
cd frontend
pnpm install
```

### 环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入必要的 API Key（至少需要 `GEMINI_PROXY_API_KEY` 和 `GEMINI_PROXY_API_BASE`）。详细配置项参见 `.env.example` 中的注释。

### 启动开发服务

```bash
# 后端（项目根目录）
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload

# 前端（frontend 目录）
cd frontend
pnpm dev
```

前端默认运行于 `http://localhost:5173`，后端默认运行于 `http://localhost:8000`。

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
| `release/` | 发版分支 | `release/v0.8.0-langgraph-prod` |

### 提交信息格式

遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>(<scope>): <description>

<optional body>
```

**type** 取值：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`perf`、`ci`、`style`

示例：

```
feat(planner): add A/B experiment bucketing for planner prompts
fix(chat-input): resolve encoding corruption on non-ASCII input
docs(runbook): update checkpointer failover procedure
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
- 使用 **不可变模式**：始终创建新对象，禁止直接修改（mutation）
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
# 运行全部后端测试
python -m pytest backend/tests tests -q

# 运行单个测试文件
python -m pytest backend/tests/test_planner_node.py -v

# 带覆盖率
python -m pytest --cov=backend --cov-report=term-missing
```

测试目录：
- `backend/tests/` -- 后端单元测试与集成测试
- `tests/` -- 回归测试与评估器

### 端到端测试（Playwright）

```bash
cd frontend
pnpm exec playwright install   # 首次运行需安装浏览器
pnpm test:e2e
```

### 检索评估

```bash
python tests/retrieval_eval/run_retrieval_eval.py --gate --report-prefix local
```

### 提交前检查清单

```bash
# 后端
python -m pytest backend/tests tests -q

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
├── backend/                    # Python 后端
│   ├── api/                    # FastAPI 路由与 Schema
│   ├── agents/                 # 6 个金融子 Agent（price/news/technical/...）
│   ├── graph/                  # LangGraph 11 节点管线
│   ├── orchestration/          # 编排层（Supervisor、缓存、预算、追踪）
│   ├── conversation/           # 对话层（上下文、路由、Schema 路由）
│   ├── handlers/               # 请求处理器
│   ├── services/               # 业务服务（PDF、邮件、熔断、限流）
│   ├── tools/                  # 金融工具实现（搜索、行情、新闻...）
│   ├── report/                 # 报告 IR、校验、引用策略
│   ├── knowledge/              # RAG 引擎与向量存储
│   ├── security/               # SSRF 防护
│   ├── config/                 # Ticker 映射等配置
│   ├── prompts/                # 系统提示词
│   └── tests/                  # 后端测试
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── api/                # Axios API 客户端
│   │   ├── components/         # UI 组件
│   │   │   ├── ui/             # 共享基础组件（Button/Card/Badge/Input）
│   │   │   ├── dashboard/      # 仪表盘组件
│   │   │   ├── layout/         # 布局组件
│   │   │   └── right-panel/    # 右侧面板
│   │   ├── hooks/              # 自定义 Hooks
│   │   ├── pages/              # 页面组件（Dashboard/Workbench）
│   │   ├── store/              # Zustand 全局状态
│   │   ├── types/              # TypeScript 类型定义
│   │   └── config/             # 前端运行时配置
│   └── e2e/                    # Playwright E2E 测试
├── docs/                       # 技术文档
├── tests/                      # 回归测试与评估器
├── scripts/                    # 运维脚本
├── requirements.txt            # Python 依赖
└── .env.example                # 环境变量模板
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
| `--fin-primary` | `37 99 235` / `59 130 246` | 主色调（RGB 通道值，用于 alpha 组合） |
| `--fin-success` | `#10b981` | 涨幅/成功 |
| `--fin-danger` | `#ef4444` | 跌幅/错误 |
| `--fin-warning` | `#f59e0b` | 警告 |
| `--fin-predict` | `#8b5cf6` / `#a78bfa` | 预测/AI 相关 |

### 使用方式

在 Tailwind 中通过自定义工具类使用：

```html
<div class="bg-fin-card border border-fin-border text-fin-text">
  <span class="text-fin-text-secondary">次要信息</span>
</div>
```

---

## 相关文档

- [架构概览](docs/01_ARCHITECTURE.md)
- [LangGraph 重构指南](docs/06_LANGGRAPH_REFACTOR_GUIDE.md)
- [生产运维手册](docs/11_PRODUCTION_RUNBOOK.md)
- [Agent 指南](docs/AGENTS_GUIDE.md)
- [LangGraph 流程](docs/LANGGRAPH_FLOW.md)
- [文档索引](docs/DOCS_INDEX.md)
