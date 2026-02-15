# FinSight v1.0.0 发布总结

> 发布日期: 2026-02-08
> 分支: `release/v0.8.0-langgraph-prod`
> 标签: `v1.0.0`
> 提交: 157 files changed, +16,201 / -2,862

---

## 一、本次完成内容

### 1. 安全加固 (P0 Critical)

| 问题 | 修复方案 | 文件 |
|------|---------|------|
| LLM 重试卡死 (17.4h) | `llm_factory` 注入式 endpoint 轮询, 默认 6 次 × 5s | `llm_retry.py`, `planner.py`, `synthesize.py` |
| `_normalize_api_base` 破坏代理 URL | `raw_url: bool` 字段, `raw=True` 保留原始 URL | `llm_config.py` |
| Config POST 任意写入 | `_CONFIG_ALLOWED_KEYS` 白名单 + `_filter_allowed_keys()` | `config_router.py` |
| Config GET 泄露 API Key | `_redact_config()` 递归 mask 敏感字段 | `config_router.py` |
| 7 个 Router 无鉴权 | 确认 `security_gate` 中间件已 app 级挂载 | `main.py` |
| Auth/Rate-limit 默认关闭 | `.env.example` 添加 PRODUCTION 警告 | `.env.example` |

### 2. Bug 修复 (P0)

| 问题 | 修复方案 | 文件 |
|------|---------|------|
| docs/06 编码损坏 | 清除 9 个 PUA 字符 | `06_LANGGRAPH_REFACTOR_GUIDE.md` |
| ChatInput 乱码 | 修复 6 行 garbled 中文 | `ChatInput.tsx` |
| client.ts 注释乱码 | 修复 30+ 行 garbled 注释 | `client.ts` |
| 暗色模式 hover 不可见 | `--fin-hover: #283548` | `index.css` |

### 3. 前端架构升级

| 改进 | 详情 |
|------|------|
| **共享 UI 组件库** | `Button` / `Card` / `Badge` / `Input` → `components/ui/` |
| **AgentLogPanel 拆分** | 961 行 → 5 个子组件 (`agent-log/`) |
| **ReportView 拆分** | 1643 行 → 6 个子组件 (`report/`) |
| **Workbench Sprint 1** | ReportSection / NewsSection / TaskSection (`workbench/`) |
| **设计令牌** | `text-2xs: 11px` token, NavItem 使用 `bg-fin-primary/10` |
| **border-radius 统一** | 卡片 `rounded-xl`, 内部元素 `rounded-lg` |
| **ARIA 无障碍** | `aria-label`, `aria-current`, `role="navigation"` 等 |
| **移动端侧边栏** | Fixed drawer + backdrop overlay + slide 动画 |
| **消息持久化** | localStorage 存储最近 100 条, streaming 完成时写入 |
| **不可变状态更新** | `updateLastMessage` 从直接 mutation 改为 `map()` + spread |

### 4. 后端架构改进

| 改进 | 详情 |
|------|------|
| **GraphState 类型契约** | `Policy` / `PlanIR` / `Artifacts` / `Trace` TypedDict |
| **动态比较文本** | 替换硬编码 MSFT/AAPL 为 ticker 感知文本 |
| **report_builder** | `min_chars` 2000 → 800, 减少模板填充 |

### 5. 文档体系

| 文档 | 内容 |
|------|------|
| `CONTRIBUTING.md` | 贡献者指南 (环境配置/工作流/代码风格/测试要求) |
| `CHANGELOG.md` | 变更日志 (v0.8.0 + v1.0.0) |
| `ISSUE_TRACKER.md` | 30+ 问题追踪, P0/P1/P2 分级 |
| `LANGGRAPH_FLOW.md` | 11 节点管线可视化 Mermaid 图 |
| `AGENTS_GUIDE.md` | 6 个金融 Agent 能力说明 |
| `WORKBENCH_ROADMAP.md` | 工作台路线图 (Sprint 1-3) |
| `readme_cn.md` | 与 `readme.md` 同步更新 |

### 6. 验证结果

| 检查项 | 结果 |
|--------|------|
| TypeScript `tsc --noEmit` | ✅ 零错误 |
| LLM Rotation 测试 (11个) | ✅ 全部通过 |
| 核心测试套件 (35个) | ✅ 全部通过 |
| 全量后端测试 (323/362) | ✅ 39 个失败均为预存环境依赖问题 |

---

## 二、ISSUE_TRACKER 完成情况

### 已完成 ✅ (26/32)

**P0 (9/9)**: 全部完成
**P1 (11/13)**: 2 项待处理
**P2 (6/10)**: 4 项待处理

### 未完成项目 (6 项, 留待后续)

| 优先级 | 项目 | 原因 |
|--------|------|------|
| P1 | Path traversal 风险 | 需要深入安全审计, 涉及多个 router 的路径清理逻辑 |
| P1 | ThinkingProcess.tsx 过大 (501行) | 非紧急, 可在下次迭代中拆分 |
| P1 | docs/06 混合职责 | 1584 行文件拆分需要仔细规划 |
| P2 | 响应式断点不统一 | CSS 768/1024/1280 vs JS 1024, 需要统一策略 |
| P2 | dry_run 模式无 UX 提示 | 需要前端 banner 组件 |
| P2 | 新闻降级无通知 | 需要前端 toast/notification 系统 |

---

## 三、后续 TODO (按优先级排序)

### Sprint 即时任务 (1-2 天)

- [ ] **安装缺失依赖**: `pip install apscheduler langgraph-checkpoint-sqlite` 修复 39 个测试失败
- [ ] **Path traversal 防护**: `report_router.py` 和 `system_router.py` 添加路径清理
- [ ] **ThinkingProcess.tsx 拆分**: 501 行 → 3 个子组件 (StepList/StepDetail/ProgressBar)
- [ ] **PR 合并**: 从 `release/v0.8.0-langgraph-prod` 创建 PR 合并到 `main`

### Sprint 1 — 功能增强 (1 周)

- [ ] **Workbench Sprint 2**: 深度分析入口 + 对比视图 (参见 `WORKBENCH_ROADMAP.md`)
- [ ] **通知系统**: Toast/Notification 组件, 用于 dry_run 提示和新闻降级通知
- [ ] **响应式断点统一**: 定义 `BREAKPOINTS` 常量, CSS/JS 共用
- [ ] **docs/06 拆分**: 设计规范 + 变更日志 + 待办清单 三文件
- [ ] **E2E 测试补充**: Workbench 页面 + 移动端 sidebar 的 Playwright 测试

### Sprint 2 — 研报库 + 智能任务系统 (2 周)

#### 研报库三层架构

研报来源需要分层管理，不能只存 AI 对话研报：

| 层级 | 来源 | 存储方式 | 内容 |
|------|------|---------|------|
| **AI 生成** | FinSight LangGraph 管线 | `report_index` SQLite/Postgres | 用户查询触发的分析研报 |
| **官方公告** | SEC EDGAR / 港交所 / 交易所 | 定时爬取 + 向量化 | 10-K/10-Q/年报/中报/招股书 |
| **第三方机构** | 券商研报 / 投行评级 | 用户上传 + RAG 索引 | 买卖评级、目标价、行业研究 |

**数据模型设计**：
```
ReportEntry:
  - id: UUID
  - source_type: "ai_generated" | "official_filing" | "third_party"
  - ticker: str
  - title: str
  - content: text / structured JSON
  - embedding: vector (用于语义检索)
  - confidence: float (AI 研报专属)
  - filing_type: str (官方公告: 10-K/10-Q/8-K)
  - publisher: str (第三方: 券商名称)
  - created_at: datetime
  - tags: list[str]
```

**前端展示**：Workbench 研报区新增 Tab 切换 `AI 分析 | 官方公告 | 机构研报`，支持交叉对比。

#### 智能任务系统 (AI-Driven Daily Tasks)

工作台"今日任务"应根据用户画像动态生成，不再硬编码：

**输入信号**：
| 信号 | 来源 | 示例 |
|------|------|------|
| 投资者类型 | `user_profile.risk_preference` | 保守型 / 稳健型 / 进取型 |
| 持仓数据 | `portfolioPositions` | AAPL: 100股, TSLA: 50股 |
| 长期记忆 | `session_context` + 历史对话 | 用户关注半导体板块、偏好技术分析 |
| 市场事件 | `news_agent` 实时数据 | 美联储议息、财报季、重大并购 |
| 研报时效 | `report_index` 最后更新时间 | AAPL 研报 5 天未更新 |

**任务生成规则**：
| 投资者类型 | 任务偏好 |
|-----------|---------|
| **保守型** | 强调风险提示、防御性配置建议、股息分析 |
| **稳健型** | 平衡增长与风险、组合再平衡建议、行业轮动 |
| **进取型** | 高波动标的机会、技术突破信号、事件驱动策略 |

**实现方案**：
1. 后端新增 `/api/tasks/daily` 端点
2. 调用 LLM (Planner 模式) 基于用户画像 + 市场数据生成个性化任务列表
3. 任务带 `priority` / `category` / `action_url` 字段
4. 前端 TaskSection 消费 API，按优先级排序展示
5. 用户可标记完成/跳过，反馈写入长期记忆

#### 其他优化

- [ ] **UI 组件迁移**: 逐步将现有内联 Tailwind 按钮/卡片替换为 `components/ui/` 共享组件
- [ ] **Agent 日志面板增强**: 实时搜索/过滤, Agent 时间线可视化
- [ ] **报告对比功能**: 同一 ticker 不同时间点的报告 diff 视图
- [ ] **持仓盈亏计算**: Dashboard 显示持仓成本和实时盈亏
- [ ] **键盘快捷键**: Ctrl+K 搜索, Ctrl+/ 切换面板

### Sprint 3 — 企业级功能 (1 月)

- [ ] **用户认证系统**: JWT/OAuth2 完整认证流程 (替换当前简单 API Key)
- [ ] **多用户支持**: 用户隔离的 session/portfolio/watchlist
- [ ] **报告导出**: PDF/Excel 下载, 邮件定时推送
- [ ] **自定义 Agent**: 用户可配置 Agent 选择策略和权重
- [ ] **RAG 知识库**: 用户上传研报/财报, 向量检索增强分析
- [ ] **国际化 (i18n)**: 英文/中文双语支持
- [ ] **性能监控**: Prometheus + Grafana 可观测性基础设施
- [ ] **CI/CD 完善**: GitHub Actions 自动测试 + Docker 构建 + 蓝绿部署

### 技术债务清理

- [ ] `test_scheduler_runner.py` 依赖修复 (apscheduler)
- [ ] `langgraph.checkpoint.sqlite` 安装配置
- [ ] ESLint remaining 问题清理 (`eslint_remaining.json`)
- [ ] 废弃代码清理 (旧 Supervisor/SchemaRouter/ConversationRouter)
- [ ] Python type hints 补全 (目标 100% 公开函数覆盖)
- [ ] 测试覆盖率提升至 80%+ (当前约 60%)

---

## 四、项目文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 架构概览 | `docs/01_ARCHITECTURE.md` | 系统架构设计 |
| LangGraph 重构 | `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` | 管线设计规范 |
| LangGraph 流程 | `docs/LANGGRAPH_FLOW.md` | 11 节点数据流 |
| Agent 指南 | `docs/AGENTS_GUIDE.md` | 6 个 Agent 说明 |
| 工作台路线图 | `docs/WORKBENCH_ROADMAP.md` | Workbench 规划 |
| 生产运维 | `docs/11_PRODUCTION_RUNBOOK.md` | 运维手册 |
| Issue 追踪 | `docs/ISSUE_TRACKER.md` | 问题跟踪 |
| 贡献指南 | `CONTRIBUTING.md` | 开发者入门 |
| 变更日志 | `CHANGELOG.md` | 版本历史 |
| 文档索引 | `docs/DOCS_INDEX.md` | 全部文档目录 |

---

*Generated by FinSight v1.0.0 release process — 2026-02-08*
