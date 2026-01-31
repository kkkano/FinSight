# FinSight 项目结构说明（最新）

> **更新日期**: 2026-01-31
> 本文件同步了当前重构后的实际目录结构，方便你和后续合作者快速理解：
> 哪些代码在"用"、哪些已经归档，以及前后端分别放在哪里。

---

## 📁 根目录概览

项目根目录下的关键内容：

- `backend/`：后端代码（FastAPI + ConversationAgent + Supervisor-Forum 编排 + 工具层）。
- `frontend/`：前端代码（React + TypeScript + Vite + Tailwind）。
- `docs/`：文档与蓝图（架构说明、数据源说明、开发日志等）。
- `tests/`：**新测试目录**（回归测试 `regression/` + 单元测试 `unit/`）。
- `test/`：旧版高层测试（逐步迁移到 `tests/` 中）。
- `archive/`：老版本 Agent / 工具 / 测试的归档区。
- `backend/langchain_tools.py`：当前使用的 LangChain 工具注册表，供 Supervisor Agent 绑定。
- `backend/legacy/streaming_support.py`: legacy streaming helper (tests-only, not used in production).
- `.env`：环境变量配置（LLM、数据源 API key 等，不会提交到仓库）。
- `requirements.txt`：**当前主用的 Python 依赖列表（LangChain 1.1 + Supervisor-Forum 架构）。**
- `readme.md` / `readme_cn.md`：中英文项目总览说明。

---

## 🧱 后端结构（`backend/`）

> 后端是整个系统的「大脑」和「数据中枢」，负责对话编排、调用工具以及对外提供 API。

### 1. 顶层文件

- `backend/langchain_agent.py`
  - 已废弃（归档）。当前架构使用 `backend/orchestration/supervisor_agent.py`（SupervisorAgent + ForumHost）进行多 Agent 协调与报告生成。

- `backend/langchain_tools.py`
  - LangChain 工具注册表，供 Supervisor Agent 和 Worker Agent 调用。

- `backend/tools/`
  - **核心金融工具实现**（模块化拆分）：
    - `search.py`：统一搜索接口（Exa → Tavily → DuckDuckGo 回退）
    - `news.py`：新闻聚合（Reuters/Bloomberg RSS + Finnhub）
    - `price.py`：行情数据（yfinance → Finnhub → Alpha Vantage 多源回退）
    - `financial.py`：财务报表与指标
    - `macro.py`：宏观数据（FRED API）
    - `web.py`：网页抓取与情绪指数
    - `utils.py` / `http.py` / `env.py`：通用工具函数

- `backend/cli_app.py`
  - 命令行入口（本地调试时可以直接通过 CLI 调用 Agent / 工具）。

- `backend/config.py`
  - 后端配置与 LLM / API key 相关的读取逻辑（例如从 `.env` 中加载）。

- `backend/llm_config.py`
  - **LLM 配置工厂函数**：统一 user_config.json > .env 优先级。

- `backend/llm_service.py`
  - LLM 服务的封装（兼容 LiteLLM / OpenAI 兼容接口等），供部分模块复用。

- `backend/langsmith_integration.py`
  - 与 LangSmith 的集成代码，用于调用链路与性能的可观测性。

- `backend/metrics.py`
  - Prometheus 指标导出（可观测性入口）。

### 2. API 层（`backend/api/`）

- `backend/api/main.py`
  - FastAPI 应用入口：
    - `/`：健康检查。
    - `/chat`：主对话接口（使用 `ConversationAgent`）。
    - `/chat/supervisor`：Supervisor 路径入口。
    - `/chat/supervisor/stream`：流式 SSE 响应。
    - `/api/config`：前端设置读取与保存（LLM 配置、界面布局偏好等）。
    - `/api/export/pdf`：将对话导出为 PDF。
    - `/health`、`/metrics`、`/diagnostics/orchestrator`：可观测性接口。

- `backend/api/chart_detector.py`
  - 对回答中的内容进行分析，帮助判断应该渲染什么类型的图表。

- `backend/api/schemas.py`
  - Pydantic 请求/响应 Schema 定义。

- `backend/api/streaming.py`
  - SSE 流式响应辅助模块。

> 启动后端通常使用：`python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload`

### 3. 对话层（`backend/conversation/`）🆕

- `backend/conversation/agent.py`
  - **ConversationAgent**：对话统一入口，负责：
    - 维护会话上下文（调用 `ContextManager`）。
    - 调用 `ConversationRouter` 判断意图。
    - 调用 `SchemaToolRouter` 进行 Schema 驱动的工具选择。
    - 评估 **Need-Agent Gate** 决定是否升级到 Supervisor。
    - 将请求分发给不同的 Handler（Chat / Report / Followup）。
    - 在 REPORT 场景中通过 `SupervisorAgent` 协调多 Worker Agent 并行分析。

- `backend/conversation/context.py`
  - **ContextManager**：管理历史对话轮次，处理"这只股票""上一个问题"之类的引用。

- `backend/conversation/router.py`
  - 意图识别与分发逻辑，定义了 `Intent` 枚举和路由策略。

- `backend/conversation/schema_router.py` 🆕
  - **SchemaToolRouter**：Schema 驱动的工具路由
    - **一次 LLM 调用**选择工具 + 返回 `{tool_name, args, confidence}`
    - **Pydantic 校验**：10 个 Tool Schema（AnalyzeStock、GetPrice、CompareStocks、GetNews 等）
    - **SlotCompletenessGate 业务规则**：
      - `company_name_only`：检测纯公司名/ticker 查询（≤15字符 + 无动作词 + 有实体），触发追问
      - `get_market_sentiment` 守卫：防止误判为情绪查询
      - 缺失 ticker 校验：强制补槽
    - **ClarifyTool 模板化追问**：根据 missing fields 生成友好问题
    - **多轮补槽**：pending_tool_call 状态记忆缺失参数

### 4. 处理器层（`backend/handlers/`）

- `chat_handler.py`：聊天/轻量分析场景。
- `report_handler.py`：已废弃，报告生成统一走 Supervisor → Forum 流程。
- `followup_handler.py`：追问与上下文相关补充。

### 5. 编排层（`backend/orchestration/`）

- `supervisor_agent.py`
  - **SupervisorAgent**：多 Agent 协调者
    - 意图路由表：GREETING/PRICE/NEWS/TECHNICAL/FUNDAMENTAL/MACRO/REPORT/COMPARISON/SEARCH
    - **6 个 Worker Agent**：PriceAgent、NewsAgent、TechnicalAgent、FundamentalAgent、MacroAgent、DeepSearchAgent
    - **ForumHost 集成**：多 Agent 结果综合与冲突消解
    - **BudgetManager**：工具调用/轮次/耗时预算限制
    - **PlanBuilder/PlanExecutor**：计划驱动的报告执行
    - **DataContextCollector**：统一 as_of/currency/adjustment 追踪

- `intent_classifier.py`
  - **IntentClassifier**：三层混合意图分类（规则 → Embedding → LLM）

- `forum.py`
  - **ForumHost**：首席投资官角色，负责 Agent 结果综合与冲突消解。

- `orchestrator.py`
  - **ToolOrchestrator**：统一管理工具调用顺序、缓存和重试策略。

- `tools_bridge.py`
  - 将 `backend.tools` 注册进 Orchestrator，并与 LangChain 工具层打通。

- `cache.py`
  - KV 缓存（支持抖动 + 负缓存）。

- `validator.py`
  - 数据校验相关模块。

- `budget.py`
  - **BudgetManager**：预算管理（max_tool_calls/max_rounds/max_seconds）。

- `data_context.py`
  - **DataContextCollector**：数据上下文一致性追踪。

- `trace.py` / `trace_schema.py`
  - **TraceEvent Schema v1**：统一事件格式（event_type/duration/metadata）。

### 6. Agent 层（`backend/agents/`）

- `base_agent.py`：Agent 基类，定义统一接口。
- `price_agent.py`：行情专家（实时报价 + 多源熔断）。
- `news_agent.py`：舆情专家（RSS + 反思循环 + 结构化输出）。
- `technical_agent.py`：技术分析师（MACD/RSI/布林带）。
- `fundamental_agent.py`：基本面研究员（财报解读 + 估值）。
- `macro_agent.py`：宏观分析师（FRED API）。
- `deep_search_agent.py`：深度研报（多轮搜索 + SSRF 防护）。
- `search_convergence.py`：搜索收敛模块（信息增益评分 + 去重 + 停止条件）。

### 7. 报告层（`backend/report/`）🆕

- `ir.py`
  - **ReportIR**：报告中间表示（sections/citations/agent_status）。

- `validator.py`
  - **ReportValidator**：ReportIR Schema 校验（引用 confidence/freshness）。

- `evidence_policy.py`
  - **EvidencePolicy**：引用校验 + 覆盖率阈值约束。

- `disclaimer.py`
  - 免责声明模板。

### 8. 知识层（`backend/knowledge/`）🆕

- `rag_engine.py`
  - **RAGEngine**：文档切片（句子边界检测）+ 向量化入库 + 相似度检索。

- `vector_store.py`
  - **VectorStore**：ChromaDB 封装，支持持久化和临时集合。

### 9. 安全层（`backend/security/`）🆕

- `ssrf.py`
  - **SSRF 防护**：URL 校验 + 私有 IP 检测 + 重定向限制。

### 10. 配置层（`backend/config/`）🆕

- `ticker_mapping.py`
  - **股票代码映射**：中文公司名 → Ticker（苹果 → AAPL）+ 提取函数。

### 11. 服务层（`backend/services/`）

- `pdf_export.py`：PDF 导出服务。
- `subscription_service.py`：邮件订阅/Alert 服务。
- `email_service.py`：邮件发送服务。
- `memory.py`：用户记忆存储。
- `circuit_breaker.py`：熔断器（支持分源阈值）。
- `rate_limiter.py`：限流器。
- `health_probe.py`：健康探针。
- `scheduler_runner.py`：APScheduler 调度器。

### 12. Prompts 层（`backend/prompts/`）

- `system_prompts.py`：系统提示词模板。  

---

## 💻 前端结构（`frontend/`）

> 前端提供类 ChatGPT 的对话体验，并加入重金融风格的品牌化设计。

### 1. 入口与布局

- `frontend/src/main.tsx`  
  - React 应用入口，挂载到 DOM。  

- `frontend/src/App.tsx`  
  - 顶层布局组件，负责：  
    - 顶部品牌条（Logo、标题、副标题）。  
    - 主题切换（深色 / 浅色）。  
    - 导出 PDF 按钮。  
    - 设置按钮（打开 `SettingsModal`）。  
    - 左侧对话面板与右侧图表面板（可折叠）。  
    - 布局模式：居中布局 / 铺满宽度（从 `useStore.layoutMode` 读取）。  

### 2. 组件与状态

- `frontend/src/components/`  
  - `ChatList.tsx`：对话消息列表，负责局部滚动到底部，避免整个页面上移。  
  - `ChatInput.tsx`：输入框与发送按钮，调用 `/chat` 或 `/chat/stream`。  
  - `StockChart.tsx`：右侧图表区域，渲染价格走势等可视化。  
  - `InlineChart.tsx`：在聊天气泡中嵌入的小图表组件。  
  - `SettingsModal.tsx`：设置弹窗（主题、布局模式、LLM 配置等）。  
  - `ThinkingProcess.tsx`：显示 AI 的推理步骤与耗时信息。  

- `frontend/src/store/useStore.ts`  
  - 使用 **Zustand** 管理全局状态：  
    - `messages`：对话消息列表。  
    - `currentTicker`：当前关注的标的，推动右侧图表自动展示。  
    - `theme`：主题模式（`dark` / `light`），持久化到 `localStorage`。  
    - `layoutMode`：布局模式（`centered` / `full`），同样持久化到 `localStorage`。  

- `frontend/src/api/client.ts`  
  - 基于 Axios 的 API 封装：调用 `/chat`、`/api/config`、`/api/export/pdf` 等后端接口。  

---

## 📚 文档目录（`docs/`）

> 文档区不仅包含旧的 LangChain 迁移报告，也新增了本次对话 Agent / 升级蓝图相关的说明。

重要文档示例：

- `CONVERSATIONAL_AGENT_BLUEPRINT_V3.md`  
  - 对话式股票分析 Agent 的整体方案与架构蓝图（V3.0）。  

- `Future_Blueprint_CN.md`  
  - **FinSight AI 升级蓝图（Sub‑Agent & 深度研究方向）**：描述从单 Agent 到多 Agent、Alert、DeepSearch 的长期规划。  

- `plans/Future_Blueprint_Execution_Plan_CN.md`  
  - 本次新增：针对上述蓝图的 **落地执行计划与优先级**（P0–P4 分阶段）。  

- `DATA_SOURCES_ADDED.md` / `DATA_SOURCE_FIXES.md`  
  - 数据源引入和修复记录。  

- `API_KEYS_CONFIGURED.md`  
  - API Key 配置说明与注意事项。  

- `DEVELOPMENT_LOG.md` / `TESTING_GUIDE.md` / `TASK_PROGRESS.md` 等  
  - 开发过程、测试说明、任务进度记录。  

旧的 LangChain 迁移相关文档（如 `migration_*.md`、`LangChain迁移报告.md` 等）已被保留在 docs 中，作为历史背景与设计参考，但并不再描述当前架构。

---

## 🧪 测试结构（`tests/` + `backend/tests/` + `test/`）

测试目录采用三层结构，`pytest` 默认收集 `backend/tests/` 和 `tests/`（legacy `test/` 逐步迁移中）。

### 1. 新测试目录（`tests/`）🆕

- `tests/regression/`
  - **回归测试套件**：确保架构重构不引入回归。
    - `test_regression_suite.py`：主回归测试入口。
    - `test_architecture_refactor.py`：Phase 5.3 架构重构验证（Clarify 路径、Supervisor 路径、FastPath）。
    - `run_regression.py`：批量运行回归测试脚本。
    - `conftest.py`：pytest 配置与 fixture。
  - `baselines/`：基线数据（baseline_cases.json）。
  - `mocks/`：测试 Mock 类。
    - `mock_tools.py`：工具层 Mock。
    - `mock_llm.py`：LLM 层 Mock（返回可控 JSON）。
  - `evaluators/`：回归评估器。
    - `base.py`：评估器基类。
    - `intent_evaluator.py`：意图分类评估。
    - `structure_evaluator.py`：报告结构评估。
    - `citation_evaluator.py`：引用校验评估。

- `tests/unit/`
  - **单元测试**：模块级精细测试。
    - `test_schema_router.py`：SchemaToolRouter + SlotCompletenessGate 单元测试。

### 2. 后端内部测试（`backend/tests/`）

- 侧重后端内部模块的单元测试与阶段性集成测试：
  - `test_cache.py`、`test_validator.py`：基础设施层。
  - `test_orchestrator.py`、`test_phase*_integration.py`：工具编排与分阶段集成。
  - `test_conversation_experience.py`：对话体验与路由逻辑。
  - `test_chat_supervisor_sync.py` / `test_chat_async_supervisor.py`：Supervisor 同步/异步测试。
  - `test_streaming_reference_resolution.py`：流式引用解析测试。
  - `test_context_injection.py`：上下文注入测试。
  - `test_deep_research.py`：深度研究功能测试。
  - `conftest.py`：pytest 配置与共享 fixture。

### 3. 旧版测试（`test/`）

- 逐步迁移到 `tests/` 中，暂保留：
  - `test_financial_graph_agent.py`：Agent 行为验证。
  - `test_tools_fix.py`、`test_tools_fixes.py`：工具修复测试。
  - `test_api_keys.py`、`test_index_recognition.py` 等：特定功能检查。
  - `test_streaming.py`、`test_langsmith_integration_legacy.py`：旧版流式/LangSmith 测试。

> 默认测试入口：`python -m pytest`（自动收集 `backend/tests/` + `tests/`）。

---

## 🗃 归档区（`archive/`）

> 归档目录用于收纳旧版本的实现和测试文件，方便回溯，但默认不再修改。

- `archive/legacy/`  
  - `agent.py`：最早的 ReAct Agent 实现（已被当前 ConversationAgent + Supervisor-Forum 架构取代）。
  - `newtools`：历史工具实现脚本。  

- `archive/old_langchain_versions/`  
  - 旧版本的 LangChain Agent / 工具实现及相关辅助脚本（迁移前的形态）。  

- `archive/test_files/`  
  - 旧测试脚本与诊断工具，如 `test_migration_complete.py`、`diagnostic.py` 等。  

- `archive/readme*_old_backup.md`  
  - 旧版 README 备份，保留作为历史记录。  

> 新开发尽量不要再往 `archive/` 里加逻辑代码，除非是明确的“废弃但需要留档”的内容。

---

## ⚙️ 配置与依赖

- `.env`  
  - 存放 LLM、数据源 API key 以及观察性（LangSmith）相关环境变量。  

- `requirements.txt`  
  - **当前标准依赖文件**，已经更新到：  
    - `langchain==1.1.0`  
    - `langgraph==1.0.4`  
    - `fastapi==0.122.0`  
    - `uvicorn[standard]==0.38.0`  
    - 以及 Tavily、yfinance、finnhub、reportlab 等。  

- `requirements_langchain.txt`  
  - 主要保留为历史参考（旧的依赖列表），一般情况下不再使用它来安装环境。  

---

## 🚀 推荐使用方式（开发视角）

### 启动后端

```bash
python -m venv .venv
.\.venv\Scripts\activate  # Windows
pip install -r requirements.txt

python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 启动前端

```bash
cd frontend
npm install
npm run dev
```

### 运行测试

```bash
python -m pytest
```

---

## 📌 版本说明

- 当前项目基于 **LangChain 1.1.x + Supervisor-Forum 多 Agent 架构**，通过 `backend/orchestration/supervisor_agent.py` + `backend/agents/` 完成多 Agent 协调与投资报告生成。
- 原始的 ReAct Agent 和早期 LangGraph CIO Agent 实现仍然保存在 `archive/` 中，便于回滚和对比，但不再是默认路径。
- 具体的对话流程、回退策略、可用工具与未来线路图，可以参考：  
  - `readme.md` / `readme_cn.md`  
  - `docs/CONVERSATIONAL_AGENT_BLUEPRINT_V3.md`  
  - `docs/Future_Blueprint_CN.md`  
  - `docs/plans/Future_Blueprint_Execution_Plan_CN.md`  

本文件会随后端 / 前端结构的变动持续更新，建议每次大规模重构后都同步修改此处。  

