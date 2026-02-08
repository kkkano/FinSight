# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范。

---

## [1.0.0] - 2026-02-08

从 v0.8.0 LangGraph 管线基础上完成生产就绪化，覆盖 LLM 容错、UI 打磨、安全加固与文档体系建设。

### 新增

- **LLM 端点轮询容错**：通过 `llm_factory` 注入实现多端点 round-robin 故障切换，429/配额错误时自动旋转至下一端点（`LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS` 可配）
- **raw_url 代理模式**：支持完整代理 URL 直通，兼容企业级 API 网关场景
- **消息持久化**：对话消息通过 `localStorage` 自动持久化，页面刷新后恢复会话历史
- **移动端侧边栏**：响应式抽屉式侧边栏，带遮罩层，支持手势关闭
- **共享 UI 组件库**：抽取 `Button`、`Card`、`Badge`、`Input` 四个基础组件至 `frontend/src/components/ui/`，统一设计规范
- **GraphState 类型契约**：定义 `Policy`、`PlanIR`、`Artifacts`、`Trace` 等 TypedDict 契约，贯通前后端状态流转
- **证据质量信号**：Agent 卡片展示证据质量评分与新鲜度徽章
- **执行进度条**：聊天界面显示当前执行步骤的实时进度状态
- **Agent 选择评分可视化**：Trace 面板暴露并渲染 Agent 选择分数与决策理由
- **章节级引用**：报告 payload 与模板中支持 section-level citations
- **渐进式升级策略**：Agent 证据质量信号触发渐进式数据源升级
- **Filing 指标标准化**：基本面 Agent 统一 YoY/QoQ 同比环比指标格式
- **宏观 Agent 增强**：来源优先级合并与冲突感知的证据质量评估
- **检索评估增强**：新增漂移门控与 Postgres 夜间基准测试

### 修复

- **配置端点安全加固**：`/api/config` 接口添加字段白名单过滤，API Key 返回时自动脱敏
- **深色模式悬停可见性**：修复深色主题下悬停状态颜色对比度不足的问题
- **编码损坏修复**：解决 `ChatInput.tsx` 和 `client.ts` 中非 ASCII 字符编码异常
- **比较结论硬编码**：移除 MSFT/AAPL 比较报告中硬编码的结论文本，改为动态生成
- **updateLastMessage 变异模式**：重构为不可变更新模式，消除 Zustand 状态直接修改
- **report_builder 最小字符数**：`min_chars` 阈值从 2000 降低至 800，减少短报告被误判为不合格

### 变更

- **AgentLogPanel 拆分**：将 Agent 日志面板拆分为独立子组件，提升可维护性
- **ReportView 组件拆分**：报告视图按职责拆分为多个聚焦组件

### 样式

- **text-2xs 设计令牌**：新增超小号文本尺寸令牌
- **NavItem 设计令牌修复**：修正导航项令牌引用错误
- **border-radius 统一**：全局圆角值归一化，消除不一致
- **ARIA 无障碍**：关键交互元素补充 `aria-label` 和 `role` 属性

### 文档

- 新增 `LANGGRAPH_FLOW.md` -- LangGraph 11 节点管线可视化流程
- 新增 `AGENTS_GUIDE.md` -- 6 个金融子 Agent 能力与配置说明
- 新增 `WORKBENCH_ROADMAP.md` -- Workbench 分析师工作台路线图
- 新增 `ISSUE_TRACKER.md` -- 已知问题与待办追踪
- 新增 `CONTRIBUTING.md` -- 项目贡献指南
- 更新 `06_LANGGRAPH_REFACTOR_GUIDE.md` -- 补充 patch note 与 fund-domain 路线图

---

## [0.8.0] - 2026-02-07

从 Supervisor-Forum 架构迁移至 LangGraph StateGraph，实现 11 节点声明式管线编排，完成生产级发布。

### 新增

- **LangGraph 11 节点管线**：基于 `StateGraph` 架构实现完整编排链路
  - `BuildInitialState` -> `NormalizeUIContext` -> `DecideOutputMode` -> `ResolveSubject` -> `Clarify` -> `ParseOperation` -> `PolicyGate` -> `Planner` -> `ExecutePlan` -> `Synthesize` -> `Render`
- **6 个金融子 Agent**：每个 Agent 配备独立熔断器与重试策略
  - `PriceAgent` -- 实时行情（yfinance / Finnhub / Alpha Vantage 多源回退）
  - `NewsAgent` -- 新闻舆情（RSS + Finnhub + 反思循环 + 结构化输出）
  - `TechnicalAgent` -- 技术分析（MACD / RSI / 布林带）
  - `FundamentalAgent` -- 基本面研究（财报解读 + 估值模型）
  - `MacroAgent` -- 宏观分析（FRED API 实时数据）
  - `DeepSearchAgent` -- 深度研报（多轮搜索 + SSRF 防护 + 搜索收敛）
- **Planner-Executor 模式**：通过 `PlanIR` 中间表示驱动计划生成与执行
  - 支持 `stub`（确定性）和 `llm`（约束生成）两种 Planner 模式
  - A/B 实验框架：按 thread 稳定分桶，可配拆分比例与盐值
- **SSE 流式传输**：支持 `trace` 与 `raw` 两种事件类型的服务端推送
  - 前端实时消费 Agent 执行轨迹与中间结果
  - 支持 `EventSource` 与 `fetch` 两种客户端消费模式
- **Dashboard 仪表盘**：
  - Watchlist 自选股列表（实时行情卡片）
  - News Feed 新闻流（多选新闻上下文关联分析）
  - Market Data 市场概览数据
  - 多选新闻触发 NEWS 意图强制分类
- **Workbench 工作台**：面向分析师的专业工作流视图
- **设计系统**：`fin-*` CSS 自定义属性体系
  - 完整的浅色/深色双主题色板
  - 语义色定义（primary / success / danger / warning / predict）
  - 文本层级、边框、卡片、面板等组件级令牌
- **持久化 Checkpointer**：支持 `sqlite` 和 `postgres` 两种后端
  - 可控回退：`LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK` 开关
- **统一状态契约**：`subject_type + operation + output_mode` 三元组驱动全管线
- **PolicyGate 策略门控**：管线执行前的安全与合规校验节点
- **Session 上下文管理**：TTL 驱动的 LRU 会话上下文缓存
- **安全基础设施**：
  - API Key 认证（`API_AUTH_ENABLED`）
  - HTTP 速率限制（`RATE_LIMIT_ENABLED`）
  - CORS 精细控制
  - SSRF 防护（URL 校验 + 私有 IP 检测）

### 变更

- 主编排路径从 `SupervisorAgent + ForumHost` 迁移至 `LangGraph StateGraph`
- 旧 Supervisor/SchemaRouter/ConversationRouter 标记为 `@deprecated`
- API 路由入口统一为 `/chat/supervisor` 和 `/chat/supervisor/stream`
- 测试框架配置更新：`pytest.ini` 添加废弃警告过滤

### 依赖

- `langgraph` 升级至 `1.0.7`
- `langgraph-checkpoint` 升级至 `3.0.0`
- `langgraph-checkpoint-sqlite` 升级至 `3.0.3`
- `langgraph-checkpoint-postgres` 升级至 `3.0.4`
- `langchain` 升级至 `1.2.7`
- `langchain-core` 升级至 `1.2.7`

---

[1.0.0]: https://github.com/<org>/FinSight/compare/v0.8.0...v1.0.0
[0.8.0]: https://github.com/<org>/FinSight/releases/tag/v0.8.0
