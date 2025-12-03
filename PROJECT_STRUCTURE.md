# FinSight 项目结构说明（最新）

> 本文件同步了当前重构后的实际目录结构，方便你和后续合作者快速理解：  
> 哪些代码在“用”、哪些已经归档，以及前后端分别放在哪里。

---

## 📁 根目录概览

项目根目录下的关键内容：

- `backend/`：后端代码（FastAPI + ConversationAgent + LangGraph CIO Agent + 工具层）。
- `frontend/`：前端代码（React + TypeScript + Vite + Tailwind）。
- `docs/`：文档与蓝图（架构说明、数据源说明、开发日志等）。
- `test/`：高层测试与集成测试脚本。
- `archive/`：老版本 Agent / 工具 / 测试的归档区。
- `langchain_tools.py`：当前使用的 LangChain 工具注册表，供 LangGraph Agent 绑定。
- `streaming_support.py`：流式输出支持工具（已实现，后续计划更紧密集成到主流程）。
- `.env`：环境变量配置（LLM、数据源 API key 等，不会提交到仓库）。
- `requirements.txt`：**当前主用的 Python 依赖列表（已更新为 LangChain 1.1 + LangGraph 1.0.4 等）。**
- `readme.md` / `readme_cn.md`：中英文项目总览说明。

---

## 🧱 后端结构（`backend/`）

> 后端是整个系统的「大脑」和「数据中枢」，负责对话编排、调用工具以及对外提供 API。

### 1. 顶层文件

- `backend/langchain_agent.py`  
  - 基于 **LangGraph** 的 CIO Agent 实现。（类：`LangChainFinancialAgent`）  
  - 内部使用 `MessagesState + ToolNode` 和 `langchain_tools.FINANCIAL_TOOLS` 做工具调用，负责生成 800+ 字的机构风格报告。  

- `backend/tools.py`  
  - 核心金融工具实现：行情、公司信息、新闻、宏观数据、情绪、回撤分析等。  
  - 每个工具内部使用多数据源回退（yfinance / 各种 API / 搜索 / 抓取），是整个系统的数据基础层。  

- `backend/cli_app.py`  
  - 命令行入口（本地调试时可以直接通过 CLI 调用 Agent / 工具）。  

- `backend/config.py`  
  - 后端配置与 LLM / API key 相关的读取逻辑（例如从 `.env` 中加载）。  

- `backend/llm_service.py`  
  - LLM 服务的封装（兼容 LiteLLM / OpenAI 兼容接口等），供部分模块复用。  

- `backend/langsmith_integration.py`  
  - 与 LangSmith 的集成代码，用于调用链路与性能的可观测性。  

### 2. API 层（`backend/api/`）

- `backend/api/main.py`  
  - FastAPI 应用入口：  
    - `/`：健康检查。  
    - `/chat`：主对话接口（使用 `ConversationAgent`）。  
    - `/chat/stream`：流式对话接口（结合 `streaming_support.py`）。  
    - `/api/config`：前端设置读取与保存（LLM 配置、界面布局偏好等）。  
    - `/api/export/pdf`：将对话导出为 PDF。  
    - 其它：与股票行情 / 订阅相关的辅助接口。  

- `backend/api/chart_detector.py`  
  - 对回答中的内容进行分析，帮助判断应该渲染什么类型的图表。  

> 启动后端通常使用：`python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload`

### 3. 对话与编排层

- `backend/conversation/agent.py`  
  - `ConversationAgent`：对话统一入口，负责：  
    - 维护会话上下文（调用 `ContextManager`）。  
    - 调用 `ConversationRouter` 判断意图（CHAT / REPORT / FOLLOWUP / ALERT / CLARIFY / GREETING 等）。  
    - 将请求分发给不同的 Handler（Chat / Report / Followup）。  
    - 在 REPORT 场景中调用 `LangChainFinancialAgent`（LangGraph CIO Agent）。  

- `backend/conversation/context.py`  
  - `ContextManager`：管理历史对话轮次，处理“这只股票”“上一个问题”之类的引用。  

- `backend/conversation/router.py`  
  - 意图识别与分发逻辑，定义了 `Intent` 枚举和路由策略。  

- `backend/handlers/`  
  - `chat_handler.py`：聊天/轻量分析场景。  
  - `report_handler.py`：深度报告场景（调用 LangGraph CIO Agent）。  
  - `followup_handler.py`：追问与上下文相关补充。  
  - （未来可继续添加 `alert_handler.py` 等与订阅相关的 Handler）。  

- `backend/orchestration/`  
  - `orchestrator.py`：ToolOrchestrator，统一管理工具调用顺序、缓存和重试策略。  
  - `tools_bridge.py`：将 `backend.tools` 注册进 Orchestrator，并与 LangChain 工具层打通。  
  - `cache.py` / `validator.py` 等：缓存和数据校验相关模块。  

### 4. 服务与其他模块

- `backend/services/`  
  - `pdf_export.py`：PDF 导出服务。  
  - `subscription_service.py`（及未来其他服务）：邮件订阅 / Alert / 第三方服务封装。  

- `backend/tests/`  
  - 面向后端内部模块的单元测试与阶段性集成测试（如 `test_orchestrator.py`、`test_phase*_integration.py` 等）。  

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

- `Future_Blueprint_Execution_Plan_CN.md`  
  - 本次新增：针对上述蓝图的 **落地执行计划与优先级**（P0–P4 分阶段）。  

- `DATA_SOURCES_ADDED.md` / `DATA_SOURCE_FIXES.md`  
  - 数据源引入和修复记录。  

- `API_KEYS_CONFIGURED.md`  
  - API Key 配置说明与注意事项。  

- `DEVELOPMENT_LOG.md` / `TESTING_GUIDE.md` / `TASK_PROGRESS.md` 等  
  - 开发过程、测试说明、任务进度记录。  

旧的 LangChain 迁移相关文档（如 `migration_*.md`、`LangChain迁移报告.md` 等）已被保留在 docs 中，作为历史背景与设计参考，但并不再描述当前架构。

---

## 🧪 测试结构（`test/` 与 `backend/tests/`）

测试主要分为两层：

- `backend/tests/`  
  - 侧重后端内部模块的单元测试与阶段性集成测试，例如：  
    - `test_cache.py`、`test_validator.py`：基础设施层。  
    - `test_orchestrator.py`、`test_phase*_integration.py`：工具编排与分阶段集成。  
    - `test_conversation_experience.py`：对话体验与路由逻辑。  

- `test/`  
  - 更偏“系统级 / 脚本化”的测试与试验脚本，例如：  
    - `test_financial_graph_agent.py`：LangGraph CIO Agent 行为验证（使用假模型，避免真实调接口）。  
    - `test_tools_fix.py`、`test_tools_fixes.py`：工具修复相关测试。  
    - `test_api_keys.py`、`test_index_recognition.py` 等：针对特定功能的检查。  

> 默认测试入口：在项目根目录执行 `python -m pytest` 即可运行大多数测试。

---

## 🗃 归档区（`archive/`）

> 归档目录用于收纳旧版本的实现和测试文件，方便回溯，但默认不再修改。

- `archive/legacy/`  
  - `agent.py`：最早的 ReAct Agent 实现（已被当前 ConversationAgent + LangGraph CIO Agent 取代）。  
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

- 当前项目基于 **LangChain 1.1.x + LangGraph 1.0.x**，并通过 `langchain_tools.py` + `backend/langchain_agent.py` 完成现代化的工具调用与 CIO 报告生成。  
- 原始的 ReAct Agent 和早期 LangChain 版本实现仍然保存在 `archive/` 中，便于回滚和对比，但不再是默认路径。  
- 具体的对话流程、回退策略、可用工具与未来线路图，可以参考：  
  - `readme.md` / `readme_cn.md`  
  - `docs/CONVERSATIONAL_AGENT_BLUEPRINT_V3.md`  
  - `docs/Future_Blueprint_CN.md`  
  - `docs/Future_Blueprint_Execution_Plan_CN.md`  

本文件会随后端 / 前端结构的变动持续更新，建议每次大规模重构后都同步修改此处。  

