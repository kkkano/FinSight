# FinSight Workbench — Mission Control 改造规划

> 最后更新: 2026-02-13 | 分支: feat/v1.2.0-agentic
> 依赖: AGENTIC_SPRINT_TODOLIST.md Phase 3 (P3-1 ~ P3-3)
> 前置条件: P0-5 (TaskSection 接后端) + P1-1 (ExecutionStore) 完成后启动

---

## Current State (v0.8.0)

**文件**: `frontend/src/pages/Workbench.tsx` (282 行)

### 现有功能

| Section | 描述 | 状态 |
|---------|------|------|
| **Latest Reports** | 投资报告列表，点击查看 | ✅ 可用 |
| **Market News** | 实时新闻 + 排名/原始切换 | ✅ 可用 |
| **Ask About News** | 点击新闻 → 发送到 Chat 分析 | ✅ 可用 |
| **Today's Tasks** | 静态任务占位 | ⚠️ 硬编码 |

### 当前布局

```
┌─────────────────────────────────────────────┐
│ Workbench Header                            │
├──────────────────┬──────────────────────────┤
│ Latest Reports   │ Market News              │
│ - Report cards   │ - Ranked / Raw toggle    │
│ - Click to view  │ - "Ask about this" btn   │
│                  │                          │
├──────────────────┴──────────────────────────┤
│ Today's Tasks (static placeholder)          │
└─────────────────────────────────────────────┘
```

---

## 目标布局 — Mission Control

```
┌──────────────────────────────────────────────────────────────────────┐
│ Workbench Header + ExecutionBanner (全局执行进度)                      │
├─────────────────────────────┬────────────────────────────────────────┤
│  主区域 (左/上下两栏)         │  右侧面板 (ContextPanelShell)           │
│  ┌───────────────────────┐  │  ┌──────────────────────────────────┐  │
│  │ TaskSection            │  │  │ Tab: 执行结果 | MiniChat          │  │
│  │ - 任务队列 (动态生成)   │  │  │                                  │  │
│  │ - 执行状态指示          │  │  │ StreamingResultPanel             │  │
│  │ - 点击触发 Agent 执行   │  │  │ - 实时 markdown 流式输出          │  │
│  │ - pending/running/done  │  │  │ - Agent 状态管道图               │  │
│  └───────────────────────┘  │  │ - 降级标记 + 重试按钮             │  │
│  ┌───────────────────────┐  │  │ - 完成后展示 ReportView           │  │
│  │ ReportSection (时间线)  │  │  │                                  │  │
│  │ - 按日期分组            │  │  │ AgentLogPanel                    │  │
│  │ - ticker + 评分 + 置信  │  │  │ - Agent 思考/工具调用日志         │  │
│  │ - 点击回放 ReportView   │  │  │                                  │  │
│  │ - 对比模式 (选2份diff)  │  │  └──────────────────────────────────┘  │
│  └───────────────────────┘  │                                        │
│  ┌───────────────────────┐  │                                        │
│  │ NewsSection            │  │                                        │
│  │ - 排名/原始切换         │  │                                        │
│  └───────────────────────┘  │                                        │
├─────────────────────────────┴────────────────────────────────────────┤
│ 状态栏: 当前 Agent 健康 | 令牌消耗 | 最近执行                          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## P3-1: Workbench 布局重构

### P3-1a: 右侧面板 (ContextPanelShell)

**修改**: `frontend/src/components/layout/WorkspaceShell.tsx`

- Workbench 视图新增右侧面板 `ContextPanelShell`
- 包含两个子组件:
  - `StreamingResultPanel` — 实时展示 Agent 执行结果
  - `AgentLogPanel` — Agent 思考/工具调用日志
- 执行任务时右侧自动展开

**组件结构**:
```typescript
// WorkspaceShell.tsx — Workbench 专用布局
<div className="flex h-full">
  <main className="flex-1 overflow-auto">
    {/* 主区域: TaskSection + ReportSection + NewsSection */}
  </main>
  <aside className="w-[480px] border-l border-fin-border">
    <ContextPanelShell activeTab={hasActiveRun ? 'execution' : 'chat'}>
      <Tab id="execution"><StreamingResultPanel runId={activeRunId} /></Tab>
      <Tab id="chat"><MiniChat /></Tab>
    </ContextPanelShell>
  </aside>
</div>
```

### P3-1b: 主区域上下两栏

- **上栏**: TaskSection (任务队列) + 执行状态指示
- **下栏**: ReportSection (时间线) + NewsSection
- 使用 `flex flex-col` 布局，支持 resize 手柄拖拽调整比例

---

---

## P3-2: 任务执行状态机

### P3-2a: TaskSection 状态指示

**修改**: `frontend/src/components/workbench/TaskSection.tsx`

任务卡片状态流转:
```
pending (默认) → running (点击执行) → done (完成) → expired (过期)
```

| 状态 | 样式 | 行为 |
|------|------|------|
| `pending` | 灰色边框 + 播放图标 | 点击 → 触发 `executeAgent(task.execution_params)` |
| `running` | 橙色边框 + 脉冲动画 | 显示 Agent 管道进度: `price ✓ → news ⟳ → fundamental ○` |
| `done` | 绿色边框 + 勾选图标 | 显示"查看报告" / "重新执行"按钮 |
| `expired` | 暗色 + 删除线 | 任务过期不可执行 |

**数据流**:
```
TaskSection → useExecuteAgent({ ...task.execution_params })
  → executionStore.startExecution()
  → apiClient.executeAgent() → SSE events
  → StreamingResultPanel 实时展示
  → 完成后: executionStore.run.status === 'done'
  → TaskCard 切换为 done 状态
```

### P3-2b: 执行历史

- 最近 10 次执行记录
- 每条记录包含: duration、agent 状态、结论快照
- 点击历史记录 → 回放 ReportView

---

---

## P3-3: Report Timeline (报告时间线)

### P3-3a: 时间线视图

**修改**: `frontend/src/components/workbench/ReportSection.tsx`

ReportSection 从列表视图升级为时间线视图:

```
2026-02-13 ─────────────────────────────
  │
  ├── AAPL  投资评级: BUY   置信度: 87%  ★★★★
  │   └── "Apple 营收超预期，AI 业务增长强劲"
  │
  ├── TSLA  投资评级: HOLD  置信度: 72%  ★★★
  │   └── "特斯拉交付量低于预期，但 FSD 进展积极"
  │
2026-02-12 ─────────────────────────────
  │
  ├── NVDA  投资评级: BUY   置信度: 91%  ★★★★★
  │   └── "AI 芯片需求持续强劲，数据中心业务爆发"
```

**功能**:
- 按日期分组，每个节点: ticker + 标题 + 评分 + 置信度
- 点击节点 → 调用 `getReportReplay(id)` → ReportView 回放
- **对比模式**: 选择两份报告 → diff 展示（评分变化、新增/删除风险、价格变动）

### P3-3b: 报告对比 API

**新建**: 后端 `GET /api/reports/compare?id1=X&id2=Y`

**返回**:
```json
{
  "report_a": { "id": "...", "ticker": "AAPL", "date": "..." },
  "report_b": { "id": "...", "ticker": "AAPL", "date": "..." },
  "diff": {
    "rating_change": "HOLD → BUY",
    "confidence_change": "+12%",
    "price_change": "+5.3%",
    "new_risks": ["AI 监管风险"],
    "removed_risks": ["供应链中断"],
    "score_changes": {
      "fundamental": { "before": 72, "after": 85 },
      "technical": { "before": 65, "after": 78 }
    }
  }
}
```

---

---

## 产品打磨 (Phase 4 相关)

### P4-1: Command Palette 增强

**修改**: `frontend/src/components/CommandPalette.tsx`

| 命令 | 行为 |
|------|------|
| `/analyze AAPL` | 触发 `executeAgent({ query: "分析 AAPL", tickers: ["AAPL"] })` |
| `/compare AAPL vs TSLA` | 触发对比报告生成 |
| `/agents` | 打开 Agent 控制面板 |
| `/report AAPL` | 跳转最新 AAPL 报告回放 |

### P4-2: Dashboard ↔ Agent 联动

- Agent 完成分析后自动刷新 Dashboard（监听 `run.status === 'done'`）
- Dashboard 异常检测: 跌幅 > 3% 时 SnapshotCard 显示 "⚠️ 异常波动，建议分析"

### P4-3: Agent 健康仪表盘

- 后端 `/health` 增加 per-agent 指标 (成功率、平均延迟、circuit_breaker 状态)
- 前端 AgentControlPanel: 🟢 健康 (>90%) / 🟡 降级 (50-90%) / 🔴 不可用 (<50%)

### P4-4: 定时调度

- 每日 08:00 UTC+8 自动刷新 watchlist 报告
- 新闻评分超阈值时自动触发 DeepSearch

---

## 技术依赖

### 前置条件

| 依赖项 | 来源 | 状态 |
|--------|------|------|
| `execution_service.run_graph_pipeline()` | P0-1 | ✅ 已完成 |
| `apiClient.executeAgent()` | P0-1e | ✅ 已完成 |
| `report_id` 回放闭环 | P0-2 | ✅ 已完成 |
| `fallback_reason` 结构化 | P0-3 | ✅ 部分完成 |
| 分层限流器 | P0-4 | ✅ 已完成 |
| TaskSection 接后端 | P0-5 | ⏳ 未开始 |
| ExecutionStore | P1-1 | ⏳ 未开始 |
| `useExecuteAgent` hook | P1-1b | ⏳ 未开始 |
| StreamingResultPanel | P1-4 | ⏳ 未开始 |

### API 依赖

| 功能 | 所需 API | 状态 |
|------|----------|------|
| 报告列表 | `GET /api/reports` | ✅ 已有 |
| 新闻流 | `GET /api/market/news` | ✅ 已有 |
| 报告回放 | `GET /api/reports/:id` | ✅ 已有 |
| 每日任务 | `GET /api/tasks/daily` | ✅ 已有 (需增强) |
| Agent 执行 | `POST /api/execute` | ✅ 已有 |
| 报告对比 | `GET /api/reports/compare` | ❌ 需新建 |

### 组件架构

```
pages/Workbench.tsx (容器)
├── components/workbench/TaskSection.tsx          (任务队列 + 状态机)
├── components/workbench/ReportSection.tsx        (报告时间线)
├── components/workbench/NewsSection.tsx           (新闻流)
├── components/execution/StreamingResultPanel.tsx  (实时结果)
├── components/execution/ExecutionBanner.tsx       (全局进度条)
├── components/layout/ContextPanelShell.tsx        (右侧面板容器)
├── store/executionStore.ts                        (执行状态)
└── hooks/useExecuteAgent.ts                       (执行 hook)
```
