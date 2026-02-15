# FinSight Workbench — AI 任务执行中心 改造规划

> 最后更新: 2026-02-15 | 分支: feat/pm0-memory-langgraph
> 依赖: AGENTIC_SPRINT_TODOLIST.md Phase 3 (P3-1 ~ P3-5)
> 前置条件: P0-5 (TaskSection 接后端) + P1-1 (ExecutionStore) 完成后启动

---

## 设计转型

### 核心问题

当前工作台 (v0.8.0) 定位模糊，2/3 内容与仪表盘重复：

| 板块 | 现状 | 问题 |
|------|------|------|
| **最新收录研报** | 展示最近 8 条研报 | 与 Dashboard 功能重叠，应在侧边栏即可查看 |
| **市场快讯** | 直接复用 Dashboard 的 news 数据 | **完全重复**，"问这条" 跳到 Chat 太绕 |
| **今日任务** | 5 条规则硬编码任务 | 方向对但太弱 — 非 AI 驱动，规则太简单 |

### 转型方向

> **从「被动信息展示面板」→「AI 驱动的任务执行中心」**

| 维度 | 仪表盘 (Dashboard) | 工作台 (Workbench) |
|------|--------------------|--------------------|
| 核心定位 | 围绕单一 symbol 的数据监控 | 围绕**持仓组合**的行动决策 |
| 用户行为 | 被动看（价格/图表/新闻/KPI） | 主动做（执行/确认/追问/回看） |
| AI 角色 | 展示 AI 分析结果 | **AI 主动推任务 + 一键执行 + interrupt 追问** |
| 交互模式 | 静态数据刷新 | LangGraph interrupt/resume 对话式执行 |

---

## 目标布局

```
┌──────────────────────────────────────────────────────────────────────┐
│ Workbench Header                                                     │
│ 持仓概览条: 总市值 ¥1.2M | 今日 +1.3% | 科技 62% 消费 23% 医疗 15%  │
├─────────────────────────────┬────────────────────────────────────────┤
│  主区域                      │  右侧面板 (ContextPanelShell)           │
│  ┌───────────────────────┐  │  ┌──────────────────────────────────┐  │
│  │ AI 任务队列             │  │  │ Tab: 执行过程 | 执行历史           │  │
│  │                        │  │  │                                  │  │
│  │ ⚡ AAPL 昨日跌 3.2%    │  │  │ 正在分析 AAPL 风险...             │  │
│  │    需要风险评估吗？     │  │  │ ├─ ✅ 获取价格数据                │  │
│  │              [执行]    │  │  │ ├─ ✅ 获取新闻情绪                │  │
│  │                        │  │  │ ├─ ⏸ 需要确认：分析范围？         │  │
│  │ 📊 NVDA 财报明天发布   │  │  │ │   [近1周] [近1月] [近3月]       │  │
│  │    要提前做分析吗？     │  │  │ │   ← LangGraph interrupt        │  │
│  │              [执行]    │  │  │ ├─ ... (用户选择后恢复)           │  │
│  │                        │  │  │ └─ 📄 报告生成完毕                │  │
│  │ 🔄 TSLA 研报已过期     │  │  │         [查看完整报告]            │  │
│  │    7天未更新，需更新？   │  │  │                                  │  │
│  │              [执行]    │  │  │ ────────────────────────────────  │  │
│  │                        │  │  │ 执行历史:                        │  │
│  │ 📰 美联储议息结果出炉   │  │  │ ├─ 14:30 AAPL 风险评估 ✅        │  │
│  │    分析对持仓的影响？    │  │  │ ├─ 11:20 NVDA 深度分析 ✅        │  │
│  │              [执行]    │  │  │ └─ 09:00 组合再平衡 ✅            │  │
│  │                        │  │  │                                  │  │
│  │ ⚖️ 科技股占比 78%      │  │  └──────────────────────────────────┘  │
│  │    建议再平衡检查       │  │                                        │
│  │              [执行]    │  │                                        │
│  └───────────────────────┘  │                                        │
│  ┌───────────────────────┐  │                                        │
│  │ Report Timeline        │  │                                        │
│  │ (折叠，按需展开)        │  │                                        │
│  └───────────────────────┘  │                                        │
├─────────────────────────────┴────────────────────────────────────────┤
│ 状态栏: Agent 健康 | 令牌消耗 | 最近执行                               │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 三层架构设计

### Layer 1: AI 任务生成（替换 `daily_tasks.py` 硬编码规则）

**现状**：`daily_tasks.py` 用 if/else 生成 5 条固定任务，规则太简单。

**改为**：LLM 驱动的智能任务生成。

#### 输入信号

```
输入信号:
  ├─ 用户持仓 (watchlist tickers + 持仓比例 + 成本价)
  ├─ 价格异动 (昨日涨跌幅超阈值的 ticker)
  ├─ 市场事件 (重大新闻、美联储/CPI 等宏观事件)
  ├─ 财报日历 (近 3 天内有财报发布的 ticker)
  ├─ 研报时效 (哪些 ticker 的研报超过 N 天未更新)
  ├─ 组合健康 (持仓集中度、板块偏离度)
  └─ 用户历史行为 (最近关注什么、执行过什么任务)
```

#### 输出格式

```python
class AITask(BaseModel):
    id: str                      # 唯一标识
    title: str                   # 人类可读标题
    reason: str                  # 为什么推荐这个任务
    category: Literal[
        "risk",                  # 风险预警
        "opportunity",           # 机会发现
        "research",              # 深度研究
        "rebalance",             # 组合再平衡
        "event",                 # 事件驱动
        "maintenance",           # 研报维护/更新
    ]
    priority: Literal["critical", "high", "normal"]
    tickers: list[str]           # 相关 ticker
    execution_params: dict       # 可直接传入 LangGraph 的执行参数
    requires_confirmation: bool  # 是否需要用户确认才执行（高风险操作）
```

#### 生成策略

分两层：**规则层**（零延迟，确定性高）+ **LLM 层**（个性化增强）

```
规则层 (确定性任务):
  ├─ 持仓跌幅 > 5%  → critical / risk / "需要风险评估"
  ├─ 财报日 T-1     → high / event / "财报前分析"
  ├─ 研报 > 7 天    → normal / maintenance / "研报过期更新"
  └─ 持仓集中度 > 70% → normal / rebalance / "建议再平衡"

LLM 层 (个性化补充):
  ├─ 基于市场新闻 + 持仓的交叉分析
  ├─ 发现规则层遗漏的机会/风险
  └─ 生成更具体的分析建议（不是泛泛的"分析一下"）
```

### Layer 2: LangGraph Interrupt 机制（核心改造）

**现状**：`clarify` 节点通过条件路由到 `END` 实现"软中断"，用户需要重新发起完整请求。

**改为**：真正的 LangGraph `interrupt_before` / `Command(resume=...)` 机制。

#### Interrupt 点设计

```python
# runner.py — 编译图时声明 interrupt 点
graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["execute_plan"],   # planner 产出计划后暂停，用户预览
)
```

#### 交互流程

```
用户点击 [执行] 任务
  ↓
首次 invoke(thread_id=T1, query=task.query)
  → build_initial_state → ... → planner → [interrupt_before execute_plan]
  → 返回 planner 的执行计划给前端预览
  ↓
前端展示: "将执行以下分析步骤: 1.获取价格 2.获取新闻 3.基本面分析 ..."
用户点击 [确认执行] 或调整参数
  ↓
Command(resume=user_confirmation, thread_id=T1)
  → execute_plan → synthesize → render → END
  → 流式返回分析结果
  ↓
如果 Agent 执行中缺少信息（如用户未指定时间范围）:
  → 在 execute_plan 内部 interrupt
  → 前端就地展示追问 UI: [近1周] [近1月] [近3月]
  → 用户选择后 Command(resume=choice) → 继续执行
```

#### 后端 API 变更

```python
# execution_router.py — 支持 resume
@router.post("/api/execute/resume")
async def resume_execution(
    thread_id: str,
    resume_value: Any,      # 用户的回答/选择
    session_id: str,
):
    """恢复被 interrupt 暂停的执行。"""
    runner = await get_graph_runner()
    # 使用 LangGraph Command 恢复
    result = await runner.graph.ainvoke(
        Command(resume=resume_value),
        config={"configurable": {"thread_id": thread_id}},
    )
    ...
```

#### 前置条件

- Checkpointer **必须持久化** (sqlite/postgres)，否则 interrupt 后状态丢失
- 当前已支持 sqlite/postgres，但默认是 memory — 需切换默认值
- `graph.compile()` 需添加 `interrupt_before` 参数

### Layer 3: 执行区 UI（前端改造）

**现状**：`TaskSection.tsx` 有 `idle → running → done/error` 状态和 SSE 流。

**改为**：支持 interrupt 暂停 + 就地追问 + resume 恢复。

#### 执行状态机扩展

```
idle → running → interrupted → running → done
                     ↓                    ↓
                  (用户交互)           (查看报告)
                     ↓
                   error
```

| 状态 | UI 表现 | 用户操作 |
|------|---------|---------|
| `idle` | 任务卡片 + [执行] 按钮 | 点击执行 |
| `running` | 进度步骤 + 脉冲动画 | 等待 / 中止 |
| `interrupted` | 追问卡片 + 选项按钮 | 选择选项 / 输入文本 |
| `done` | 完成标记 + [查看报告] | 点击查看 |
| `error` | 错误信息 + [重试] | 点击重试 |

#### Interrupt UI 组件

```typescript
// InterruptCard.tsx — 就地追问 UI
interface InterruptCardProps {
  threadId: string;
  question: string;           // AI 的追问
  options?: string[];         // 选择项（如果有）
  allowFreeText?: boolean;    // 是否允许自由输入
  onResume: (value: any) => void;  // resume 回调
}
```

---

## 砍掉什么

| 砍掉 | 理由 | 行动 |
|------|------|------|
| **NewsSection** | 与 Dashboard 完全重复 | 删除 `components/workbench/NewsSection.tsx` |
| **ReportSection (当前形式)** | 信息展示不应是工作台主体 | 降级为折叠式 Report Timeline |
| **硬编码规则任务** | `daily_tasks.py` 的 if/else 规则太弱 | 替换为 LLM 驱动生成 |
| **"问这条" 导航** | 跳到 Chat 页太绕 | 在工作台内就地执行 |
| **WorkspaceShell 复用 dashboard 数据** | `useDashboardData(view==='workbench')` | 改为独立的持仓数据源 |

## 新增什么

| 新增 | 说明 |
|------|------|
| **持仓概览条** | 工作台顶部：总市值、今日盈亏、持仓分布饼图 |
| **AI 任务队列** | LLM + 规则层生成的个性化任务，带优先级/分类/理由 |
| **LangGraph interrupt 支持** | `graph.compile(interrupt_before=[...])` + `/api/execute/resume` |
| **InterruptCard 组件** | 就地追问 UI，支持选项/自由文本 |
| **执行历史面板** | 右侧面板展示今天执行过的任务和结果 |
| **Report Timeline (折叠)** | 历史研报按日期分组，时间线视图，支持对比 |

---

## 实施阶段

### Phase 3-1: 清理 + 布局重构

**目标**: 砍掉冗余内容，建立新布局骨架。

- [ ] **P3-1a** 删除 `NewsSection` 组件及 Workbench 中的引用
- [ ] **P3-1b** 删除 `WorkspaceShell` 中 `useDashboardData(view==='workbench')` 逻辑
- [ ] **P3-1c** Workbench 增加右侧面板 (ContextPanelShell)
  - Tab 1: 执行过程 (StreamingResultPanel + InterruptCard)
  - Tab 2: 执行历史
- [ ] **P3-1d** 主区域布局: TaskSection (核心) + Report Timeline (折叠)
- [ ] **P3-1e** 新增持仓概览条组件 (PortfolioSummaryBar)

### Phase 3-2: LangGraph Interrupt 机制

**目标**: 实现真正的 human-in-the-loop，替换软中断。

- [ ] **P3-2a** 修改 `runner.py` — `graph.compile()` 添加 `interrupt_before=["execute_plan"]`
- [ ] **P3-2b** 切换 Checkpointer 默认值: memory → sqlite (interrupt 必须持久化)
- [ ] **P3-2c** 新增 `POST /api/execute/resume` API — 接受 `thread_id + resume_value`
  - 使用 `Command(resume=...)` 恢复图执行
  - 返回同样的 SSE 流
- [ ] **P3-2d** 前端新增 `InterruptCard.tsx` 组件
  - 展示 AI 追问 + 选项按钮 / 自由文本输入
  - 调用 `/api/execute/resume` 恢复执行
- [ ] **P3-2e** 修改 `TaskSection.tsx` 执行状态机
  - 增加 `interrupted` 状态
  - SSE 事件中新增 `type: "interrupt"` 事件处理
- [ ] **P3-2f** 编写测试
  - 后端: interrupt/resume 端到端测试
  - 前端: InterruptCard 组件测试

### Phase 3-3: AI 任务生成

**目标**: 替换硬编码规则，实现 LLM 驱动的智能任务推荐。

- [ ] **P3-3a** 新建 `backend/services/task_generator.py` — 双层生成架构
  - 规则层: 价格异动、财报日历、研报时效、持仓集中度
  - LLM 层: 基于市场新闻 + 持仓的交叉分析
- [ ] **P3-3b** 新建 `AITask` Pydantic schema — 标准化任务输出
- [ ] **P3-3c** 修改 `GET /api/tasks/daily` — 调用新的 task_generator
  - 接受持仓数据 (tickers + weights)
  - 返回 5-8 条个性化、带优先级的任务
- [ ] **P3-3d** 前端 TaskSection 适配新的任务格式
  - 展示: 分类图标 + 标题 + 理由 + 优先级标签
  - critical 任务高亮显示
- [ ] **P3-3e** 编写测试
  - 规则层: 覆盖各触发条件
  - LLM 层: mock LLM 验证 prompt 和输出解析

### Phase 3-4: Report Timeline

**目标**: ReportSection 降级为折叠式时间线。

- [ ] **P3-4a** ReportSection 改为可折叠时间线视图
  - 按日期分组，每节点: ticker + 标题 + 评分 + 置信度
  - 默认折叠，点击展开
- [ ] **P3-4b** 后端新增 `GET /api/reports/compare?id1=X&id2=Y`
  - 返回结构化差异 (评分变化、新增/删除风险、价格变动)
- [ ] **P3-4c** 支持对比模式: 选两份报告 → diff 展示

### Phase 3-5: 持仓数据接入

**目标**: 工作台独立的持仓数据源，不复用 Dashboard 的 symbol 数据。

- [ ] **P3-5a** 新建 `GET /api/portfolio/summary` — 持仓概览
  - 总市值、今日盈亏、持仓分布
  - 各 ticker 权重 + 当日涨跌
- [ ] **P3-5b** 前端新增 `usePortfolioData` hook
- [ ] **P3-5c** PortfolioSummaryBar 接入真实数据

---

## 技术依赖

### 前置条件

| 依赖项 | 来源 | 状态 |
|--------|------|------|
| `execution_service.run_graph_pipeline()` | P0-1 | ✅ 已完成 |
| `apiClient.executeAgent()` | P0-1e | ✅ 已完成 |
| `report_id` 回放闭环 | P0-2 | ✅ 已完成 |
| `fallback_reason` 结构化 | P0-3 | ✅ 已完成 |
| 分层限流器 | P0-4 | ✅ 已完成 |
| TaskSection 接后端 | P0-5 | ✅ 已完成 |
| ExecutionStore | P1-1 | ⏳ 未开始 |
| `useExecuteAgent` hook | P1-1b | ⏳ 未开始 |
| StreamingResultPanel | P1-4 | ⏳ 未开始 |
| Checkpointer 持久化 (sqlite) | P3-2b | ⏳ 需配置 |

### LangGraph Interrupt 依赖

| 功能 | 要求 | 状态 |
|------|------|------|
| `graph.compile(interrupt_before=[...])` | langgraph >= 0.2.x | ✅ 已满足 |
| `Command(resume=...)` | langgraph >= 0.2.x | ✅ 已满足 |
| 持久化 Checkpointer | sqlite/postgres | ✅ 基础设施已有，需切换默认值 |
| `get_state()` / `update_state()` | langgraph 内置 | ✅ 可用 |

### 新增 API

| 功能 | 端点 | 状态 |
|------|------|------|
| 恢复执行 | `POST /api/execute/resume` | ❌ 需新建 |
| 持仓概览 | `GET /api/portfolio/summary` | ❌ 需新建 |
| 报告对比 | `GET /api/reports/compare` | ❌ 需新建 |
| 每日任务 (增强) | `GET /api/tasks/daily` | ✅ 已有，需改造 |

### 组件架构

```
pages/Workbench.tsx (容器)
├── components/workbench/PortfolioSummaryBar.tsx   (持仓概览条) [新建]
├── components/workbench/TaskSection.tsx            (AI 任务队列) [重构]
├── components/workbench/ReportTimeline.tsx         (报告时间线) [重构]
├── components/workbench/InterruptCard.tsx          (追问交互卡) [新建]
├── components/execution/StreamingResultPanel.tsx   (执行过程)
├── components/execution/ExecutionHistory.tsx       (执行历史) [新建]
├── components/layout/ContextPanelShell.tsx         (右侧面板容器)
├── store/executionStore.ts                         (执行状态)
├── hooks/useExecuteAgent.ts                        (执行 hook)
└── hooks/usePortfolioData.ts                       (持仓数据) [新建]

已删除:
├── components/workbench/NewsSection.tsx             ← 删除 (与 Dashboard 重复)
```

---

## 执行顺序

```
Phase 3-1 (清理 + 布局)
  ↓
Phase 3-2 (LangGraph interrupt) ← 核心改造，最大风险点
  ↓
Phase 3-3 (AI 任务生成) ← 可与 3-2 并行
  ↓
Phase 3-4 (Report Timeline)
  ↓
Phase 3-5 (持仓数据接入)
```

## 风险评估

| Phase | 风险 | 说明 |
|-------|------|------|
| 3-1 | 低 | 纯删除 + 布局调整，不影响现有功能 |
| 3-2 | **高** | LangGraph interrupt 是新模式，需要验证 checkpointer 持久化 + 前后端 SSE 协议 |
| 3-3 | 中 | LLM 生成任务质量不可控，需要规则层兜底 |
| 3-4 | 低 | 纯 UI 改造 |
| 3-5 | 中 | 需要持仓数据源（可能需要新的外部 API） |

## 验证方式

1. **P3-1**: 工作台页面正常渲染，NewsSection 已删除
2. **P3-2**: 点击任务 → 执行 → interrupt 暂停 → 用户选择 → resume 继续 → 完成
3. **P3-3**: `/api/tasks/daily` 返回个性化任务，包含 category/priority/reason
4. **P3-4**: Report Timeline 按日期分组展示，对比模式可用
5. **P3-5**: 持仓概览条展示真实数据
