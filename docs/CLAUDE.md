# CLAUDE.md - FinSight AI 开发指南与决策记录

此文件为 Claude 在此项目中工作时提供的最新开发指导、架构分析和决策记录。

**最后更新**: 2025-12-07  
**项目版本**: LangChain 1.1.0 + LangGraph 1.0.4 + React 18 + FastAPI  
**API密钥**: `.env` 文件（不上传 Git）

---

## 📋 工作原则

本文档遵循以下原则指导所有开发工作：

1. **深度思考优先** - 实现任何功能前，必须反思其对整体架构的影响
2. **测试驱动** - 每个功能实现后必须通过测试，才能进行下一个功能
3. **文档即时性** - 每个完成的功能立即更新此文档，包含时间戳和测试结果
4. **架构诚实** - 发现潜在问题立即提出并记录分析，不隐瞒设计缺陷
5. **决策可追溯** - 重要决策记录决策时间、理由和实现状态

---

## 项目概述

FinSight AI 是一个**对话式金融分析助手**，采用现代化的多模块架构：

- **核心架构**: ConversationAgent（意图路由） + ToolOrchestrator（工具协调） + 多处理器（CHAT/REPORT/FOLLOWUP）
- **前端**: React 18 + TypeScript + Tailwind CSS，支持暗/亮主题切换
- **后端**: FastAPI + LangChain 1.1.0 + LangGraph 1.0.4，支持流式输出
- **可观测性**: LangSmith 集成，自动追踪 Agent 执行流程
- **测试**: pytest 框架，包含单元测试、集成测试、端到端测试

### 实际架构对比

| 组件 | 实现状态 | 位置 | 说明 |
|------|--------|------|------|
| ConversationAgent | ✅ 已实现 | `backend/conversation/agent.py` | 统一对话入口，集成路由和处理器 |
| ConversationRouter | ✅ 已实现 | `backend/conversation/router.py` | 意图分类（CHAT/REPORT/ALERT/FOLLOWUP/CLARIFY/GREETING） |
| ContextManager | ✅ 已实现 | `backend/conversation/context.py` | 上下文管理，支持多轮对话 |
| ChatHandler | ✅ 已实现 | `backend/handlers/chat_handler.py` | 快速对话（<10秒响应） |
| ReportHandler | ✅ 已实现 | `backend/handlers/report_handler.py` | 深度分析报告生成 |
| FollowupHandler | ✅ 已实现 | `backend/handlers/followup_handler.py` | 追问处理 |
| ToolOrchestrator | ✅ 已实现 | `backend/orchestration/orchestrator.py` | 工具调用和数据缓存 |
| FastAPI 主服务 | ✅ 已实现 | `backend/api/main.py` | REST API 服务，支持流式输出 |
| React 前端 | ✅ 已实现 | `frontend/src/` | 聊天 UI、图表、主题切换 |

---

## 🏗️ 架构诊断与潜在问题

### 已识别的架构优势

1. **模块化设计** - 各组件职责清晰，耦合度低
   - ConversationRouter 独立处理意图分类
   - 各 Handler 各司其职，易于扩展
   - ToolOrchestrator 独立管理工具和缓存

2. **完整的对话流程** - 从输入→路由→处理→输出，流程清晰

3. **可观测性** - LangSmith 集成提供完整追踪

### 需要关注的架构问题

#### ⚠️ 问题 1: 意图分类的准确性
- **现状**: Router 使用 LLM 进行意图分类
- **风险**: 如果 LLM 分类不准确，会导致错误的 Handler 被调用
- **影响**: 用户体验下降，可能给出错误的信息类型
- **决议**: 需要在 Router 中添加置信度阈值和回退机制
- **状态**: 🔲 待实现 [见 TODO #1]

#### ⚠️ 问题 2: 工具调用的串联和并联
- **现状**: ToolOrchestrator 支持多源回退，但串联/并联策略不清晰
- **风险**: 某些查询可能需要多个工具协同，当前实现可能不够灵活
- **影响**: 无法处理复杂的多维度分析
- **决议**: 需要在 ToolOrchestrator 中实现工具组合策略
- **状态**: 🔲 待分析 [见 TODO #2]

#### ⚠️ 问题 3: 前后端数据同步
- **现状**: 前端通过 SSE 接收流式数据，但错误处理和重连机制未验证
- **风险**: 网络中断时可能丢失部分数据
- **影响**: 用户看不到完整的分析过程
- **决议**: 需要添加完整的错误恢复和数据一致性检查
- **状态**: 🔲 待测试 [见 TODO #3]

#### ⚠️ 问题 4: 会话上下文的管理
- **现状**: ContextManager 维护最近 N 轮对话
- **风险**: 长会话时，早期上下文可能被遗忘，影响连贯性
- **影响**: 长对话中用户需要重复提供背景信息
- **决议**: 考虑实现摘要机制或向量化存储重要信息
- **状态**: 🔲 待优化 [见 TODO #4]

#### ⚠️ 问题 5: LLM 成本和速率限制
- **现状**: 多处使用 LLM（Router、各 Handler、数据验证）
- **风险**: 高并发时可能触发速率限制；成本难以控制
- **影响**: 生产环境可能出现服务中断
- **决议**: 需要实现调用计数、缓存和智能降级
- **状态**: 🔲 待规划 [见 TODO #5]

---

## 🧪 开发工作流程 & 测试协议

此部分定义了如何在此项目中开发新功能。**所有开发必须严格遵循此协议**。

### 功能开发的 4 个阶段

#### 第 1 阶段: 需求分析与架构审视 (0.5-1 小时)

**目标**: 确保决策正确，避免后期返工

**步骤**:
1. 理解功能需求的完整含义
2. 检查此功能如何与现有架构交互
3. 识别可能的副作用和依赖关系
4. 列出可能的边界情况和异常场景

**输出**: 在此文档中写下思考过程

**示例**:
```markdown
### TODO #1: 实现 Router 置信度阈值

**分析** (2025-12-07 14:30):
- Router 当前直接使用 LLM 分类结果，无容错机制
- 如果分类不准确（置信度低），会导致错误的 Handler 被调用
- 需要添加置信度评分和回退逻辑
- 影响: ConversationAgent.chat() 中 router.classify() 的返回值结构
- 依赖: LLM 需要返回置信度分数
- 风险: LLM API 可能不支持置信度，需要实现替代方案

**决议**: 先实现简单的词汇匹配 + LLM 分类组合，使用关键词权重作为置信度
```

#### 第 2 阶段: 代码实现 (1-4 小时)

**要求**:
1. 先完成最小可行实现 (MVP)，不要过度设计
2. 添加详细的代码注释，解释 "为什么" 而不仅仅是 "是什么"
3. 遵循项目现有的代码风格和约定
4. 模块之间使用清晰的接口

#### 第 3 阶段: 单元与集成测试 (1-2 小时)

**测试类型**:

1. **单元测试** - 测试单个函数/方法
2. **集成测试** - 测试组件之间的交互
3. **端到端测试** - 测试完整用户流程

**测试执行**:
```bash
# 运行所有测试
cd backend && pytest tests/ -v

# 运行特定测试
pytest tests/test_improved_router.py -v

# 运行特定测试函数
pytest tests/test_improved_router.py::test_keyword_match_high_confidence -v

# 生成覆盖率报告
pytest tests/ --cov=backend --cov-report=html
```

**测试通过标准**:
- ✅ 所有单元测试通过
- ✅ 所有集成测试通过
- ✅ 代码覆盖率 ≥ 80%
- ✅ 没有新的警告或弃用消息

#### 第 4 阶段: 文档更新与结果记录 (0.5 小时)

**记录模板**:
```markdown
### TODO #1: 实现 Router 置信度阈值

**实现完成时间**: 2025-12-07 17:30

**实现内容**:
- ✅ 创建 `backend/conversation/router_v2.py`
- ✅ 添加 ImprovedConversationRouter 类
- ✅ 实现关键词匹配和 LLM 回退
- 代码行数: 250 行（含注释）

**测试结果** (2025-12-07 18:00):
- ✅ 10 个单元测试全部通过
- ✅ 5 个集成测试全部通过
- ✅ 代码覆盖率: 87%
- 执行时间: 12.3 秒

**性能指标**:
- 关键词匹配（快速路径）: 平均 15ms
- LLM 分类（回退）: 平均 2.3 秒
- 整体准确率: 94%（基于 100 个测试样本）

**发现的问题与改进**:
- 发现 Intent.CLARIFY 的关键词定义不够清晰
- 已在 router_keywords.yaml 中完善关键词列表
- 建议后续添加用户反馈循环优化关键词权重

**决议**: ✅ 此实现满足要求，可以合并到主代码
```

### 开发检查清单

在提交代码前，检查以下项目:

- [ ] 进行了充分的需求分析和架构审视
- [ ] 实现了最小可行版本 (MVP)，没有过度设计
- [ ] 代码有清晰的注释和文档
- [ ] 所有单元测试通过 (≥80% 覆盖率)
- [ ] 所有集成测试通过
- [ ] 没有新的代码警告或错误
- [ ] 性能符合预期（如适用）
- [ ] 已在此文档中记录分析、实现、测试和结果
- [ ] 已识别并记录潜在的未来改进

---

## 开发命令

### 环境设置
```bash
# 创建虚拟环境 (Windows - 推荐 Conda)
conda create -n FSenv python=3.11
conda activate FSenv

# 或使用 venv
python -m venv .venv && .\.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 前端依赖
cd frontend && npm install

# 备选（国内镜像）
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 运行应用
```bash
# 后端服务 (FastAPI)
cd backend && python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 前端开发服务 (React + Vite)
cd frontend && npm run dev

# CLI 模式（仅命令行，不启动 FastAPI）
python main.py "分析 AAPL 股票" --model gemini-2.5-pro
```

### 测试
```bash
# 后端单元测试
cd backend && pytest tests/ -v

# LangSmith 集成测试
python test_langsmith_integration.py

# 前端（如有）
cd frontend && npm run test
```

---

## 架构组件详解

### 后端
- **`backend/api/main.py`**: FastAPI 主服务，定义 `/sendMessage` 等 REST API
- **`backend/conversation/agent.py`**: ConversationAgent，处理多轮对话、意图路由
- **`backend/conversation/router.py`**: 意图分类（CHAT/REPORT/FOLLOWUP）
- **`backend/orchestration/orchestrator.py`**: ToolOrchestrator，工具调用与数据缓存
- **`backend/tools.py`**: 9 大金融工具，支持级联多源回退
- **`backend/langsmith_integration.py`**: LangSmith 集成，实时追踪 Agent 执行
- **`backend/config.py`**: 集中化配置，支持多个 LLM 提供商

### 前端
- **`frontend/src/App.tsx`**: React 主应用，包含主题切换（暗/亮）
- **`frontend/src/components/ChatList.tsx`**: 聊天列表与消息渲染
- **`frontend/src/components/ChatInput.tsx`**: 用户输入框与 API 调用
- **`frontend/src/components/StockChart.tsx`**: ECharts 股票图表
- **`frontend/src/store/useStore.ts`**: Zustand 状态管理
- **`frontend/src/api/client.ts`**: FastAPI 客户端

---

## 故障排除

### 前端

| 问题 | 原因 | 解决 |
|------|------|------|
| 主题不切换 | Tailwind darkMode 未配置 | 检查 `tailwind.config.js` 有 `darkMode: 'class'` |
| API 返回空 | 后端未返回 response 字段 | 检查 `backend/api/main.py` 的 `/sendMessage` |
| 图表不显示 | ECharts 未加载或数据异常 | 检查浏览器控制台 / `backend/api/chart_detector.py` |
| CSS 报错 | Tailwind utility 类不存在 | 颜色需在 `theme.extend.colors` 定义或使用 `@layer` |

### 后端

| 问题 | 原因 | 解决 |
|------|------|------|
| 工具调用失败 | API 密钥缺失或过期 | 检查 `.env` 与 API 提供商配置 |
| 限流导致超时 | API 达到速率限制 | 增加缓存时间或升级到付费 API |
| LangSmith 未追踪 | `LANGSMITH_API_KEY` 缺失 | 检查 `.env` 与 `ENABLE_LANGSMITH=true` |
| 流式输出卡住 | 回调处理异常 | 检查 `streaming_support.py` 日志 |

---

## 更新日志

### 2025-12-07
- ✅ 完成项目架构全面评估
- ✅ 识别 5 大潜在架构问题
- ✅ 建立完整的开发工作流程和测试协议
- ✅ 创建详细的 CLAUDE.md 决策记录文档
- 📝 此文档现已成为项目决策中心

### 2025-11-29
- ✅ 前端主题切换（暗/亮）完全修复
- ✅ LangSmith 可观测性集成完成
- ✅ 流式输出与 Agent 执行通过验证
- ✅ 后端 API 返回结构规范化
- ✅ LangChain 1.0.1 → 1.1.0 升级


---最新测试效果
您好，我是 FinSight AI 金融助手。直接输入股票代码或问题（例如：AAPL 股价走势、特斯拉最新新闻），我会用实时数据和图表帮你分析。

纳斯达克最近如何
您好！纳斯达克指数近期表现非常强劲哦，主要得益于科技巨头的盈利增长和人工智能（AI）热潮的持续推动。尽管美联储降息预期有所波动，但科技股的创新能力是其核心支撑。不过，当前较高的估值和宏观经济不确定性也意味着市场可能存在一定的波动风险，建议您保持关注。
(base) PS D:\AgentProject\FinSight> D:/Anaconda/Scripts/activate
(base) PS D:\AgentProject\FinSight> conda activate FSenv
(FSenv) PS D:\AgentProject\FinSight> python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
INFO: Will watch for changes in these directories: ['D:\AgentProject\FinSight']
INFO: Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO: Started reloader process [22660] using StatReload
[Init] Core tools imported successfully.
[Init] Chart detector imported successfully.
[ConversationAgent] LLM 初始化成功 (langchain_openai)
[Bridge] 成功从 backend.tools 导入
[Bridge] 已注册 5 个价格数据源
[ConversationAgent] Report Agent 初始化成功
[ChatHandler] 从 orchestrator 获取 tools 模块
[ReportHandler] 从 orchestrator 获取 tools 模块
[Init] ReAct Agent initialized successfully.
INFO: Started server process [30740]
INFO: Waiting for application startup.
[Scheduler] price_change scheduler started: every 15.0 min.
[Scheduler] price_change scheduler started: every 30.0 min.
INFO: Application startup complete.
2025-12-07 20:24:53,706 [INFO] price_change run completed: checked=1, sent=0
[NewsFetcher] yfinance news failed for AAPL: Too Many Requests. Rate limited. Try after a while.
[NewsFetcher] finnhub news failed for AAPL: HTTPSConnectionPool(host='finnhub.io', port=443): Max retries exceeded with url: /api/v1/company-news?symbol=AAPL&from=2025-12-05&to=2025-12-07&token=d3uf9opr01qil4apq1ogd3uf9opr01qil4apq1p0 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032)')))
2025-12-07 20:25:01,334 [INFO] news run completed: checked=1, sent=0
INFO: 127.0.0.1:63703 - "GET /api/config HTTP/1.1" 200 OK
INFO: 127.0.0.1:59329 - "GET /api/subscriptions HTTP/1.1" 200 OK
INFO: 127.0.0.1:55782 - "OPTIONS /chat HTTP/1.1" 200 OK
[Router] LLM 意图识别: 纳斯达克最近如何... -> chat

Attempting Alpha Vantage API for ^IXIC...
Attempting Finnhub API for ^IXIC...
Attempting yfinance for ^IXIC...
yfinance exception: Too Many Requests. Rate limited. Try after a while.
Attempting to scrape Yahoo Finance for ^IXIC...
Attempting to find price via search for ^IXIC...
[Search] ✅ DuckDuckGo 搜索成功: ^IXIC stock price today...
[Search] ✅ 成功使用 1 个搜索源: DuckDuckGo
INFO: 127.0.0.1:55782 - "POST /chat HTTP/1.1" 200 OK
INFO: 127.0.0.1:55782 - "OPTIONS /api/chart/detect HTTP/1.1" 200 OK
INFO: 127.0.0.1:55782 - "POST /api/chart/detect HTTP/1.1" 200 OK
[get_stock_historical_data] 尝试使用 yfinance ^IXIC (尝试 1/1)...
[get_stock_historical_data] yfinance 失败 (尝试 1/1): Too Many Requests. Rate limited. Try after a while.
[get_stock_historical_data] yfinance 速率限制，等待 1 秒后重试...
[get_stock_historical_data] yfinance 速率限制，等待 2 秒后重试...
[get_stock_historical_data] yfinance 失败 (尝试 3/3): Too Many Requests. Rate limited. Try after a while.
[get_stock_historical_data] Finnhub 也失败: FinnhubAPIException(status_code: 403): You don't have access to this resource.
[get_stock_historical_data] 尝试从 Yahoo Finance 网页抓取 ^IXIC...
[get_stock_historical_data] 检测到指数代码 ^IXIC，尝试使用 yfinance 专门获取指数数据...
[get_stock_historical_data] yfinance 获取指数数据失败: Too Many Requests. Rate limited. Try after a while.
[get_stock_historical_data] 尝试使用 Massive.com ^IXIC...
[get_stock_historical_data] Massive.com 返回空数据或错误: DELAYED
[get_stock_historical_data] 尝试 yfinance 备用方法（等待后重试）...
D:\AgentProject\FinSight\backend\tools.py:1992: FutureWarning: YF.download() has changed argument auto_adjust default to True
hist = yf.download(
1 Failed download:
['^IXIC']: YFRateLimitError('Too Many Requests. Rate limited. Try after a while.')
[get_stock_historical_data] 使用 price fallback 为 ^IXIC 生成平滑序列
[API] K 线数据已缓存: ^IXIC (5d, 1h)
INFO: 127.0.0.1:55782 - "GET /api/stock/kline/%5EIXIC?period=5d&interval=1h HTTP/1.1" 200 OK
[API] 从缓存获取 K 线数据: ^IXIC (5d, 1h)
INFO: 127.0.0.1:60957 - "GET /api/stock/kline/%5EIXIC?period=5d&interval=1h HTTP/1.1" 200 OK
[API] 从缓存获取 K 线数据: ^IXIC (5d, 1h)
INFO: 127.0.0.1:60957 - "GET /api/stock/kline/%5EIXIC?period=5d&interval=1h HTTP/1.1" 200 OK
[API] 从缓存获取 K 线数据: ^IXIC (5d, 1h)
INFO: 127.0.0.1:60957 - "GET /api/stock/kline/%5EIXIC?period=5d&interval=1h HTTP/1.1" 200 OK
[API] 从缓存获取 K 线数据: ^IXIC (5d, 1h)
INFO: 127.0.0.1:60957 - "GET /api/stock/kline/%5EIXIC?period=5d&interval=1h HTTP/1.1" 200 OK
[API] 从缓存获取 K 线数据: ^IXIC (5d, 1h)
INFO: 127.0.0.1:60957 - "GET /api/stock/kline/%5EIXIC?period=5d&interval=1h HTTP/1.1" 200 OK

----
参考以下建议，并结合当前项目需求和架构，完成后续开发任务。
![alt text](d5b0063cde53cf9d4e97da5e4e814286.jpg)
D:\AgentProject\FinSight\docs\Future_Blueprint_Execution_Plan_CN.md