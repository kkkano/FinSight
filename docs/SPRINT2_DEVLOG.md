# Sprint 2 开发日志 (v1.1.0)

> 日期: 2026-02-09
> 分支: `feat/v1.1.0-sprint2`
> 基于: `release/v0.8.0-langgraph-prod`

---

## 概述

本次 Sprint 完成 16 项任务 (T1-T16)，涵盖安全加固、前端组件系统、智能任务 API、文档重构、E2E 测试补充等方面。全部验证通过：ESLint 0 errors, TypeScript 编译通过, 后端 11/11 测试通过。

---

## 完成任务清单

| # | 任务 | 类型 | 状态 |
|---|------|------|------|
| T1 | Path traversal 安全防护 | 安全 | ✅ |
| T2 | ThinkingProcess.tsx 拆分 | 重构 | ✅ |
| T3 | 响应式断点统一 | 前端 | ✅ |
| T4 | 研报库三层数据模型 | 后端 | ✅ |
| T5 | 智能任务系统 API | 后端 | ✅ |
| T7 | Toast 通知组件系统 | 前端 | ✅ |
| T8 | dry_run 模式 UX 提示 | 全栈 | ✅ |
| T9 | 新闻降级通知 | 前端 | ✅ |
| T10 | docs/06 拆分 | 文档 | ✅ |
| T11 | UI 共享组件迁移 | 前端 | ✅ |
| T12 | 全局键盘快捷键 | 前端 | ✅ |
| T13 | 持仓盈亏计算 | 前端 | ✅ |
| T14 | ESLint 剩余问题清理 | 质量 | ✅ |
| T15 | E2E 测试补充 | 测试 | ✅ |
| T16 | 最终验证 + push | 运维 | ✅ |

---

## 详细变更

### 1. 安全加固

**T1: Path traversal 防御** (`backend/api/report_router.py`)
- 新增 `_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")`
- 新增 `_validate_report_id()` 函数，对 `report_id` 参数做正则校验
- 应用到 `get_report_replay` 和 `set_report_favorite` 两个 endpoint

### 2. 前端组件系统

**T2: ThinkingProcess 拆分** (`frontend/src/components/thinking/`)
- 501 行大组件拆分为 3 个子文件：
  - `ThinkingProcess.tsx` — 主容器（折叠/展开控制）
  - `ThinkingStepList.tsx` — 步骤列表渲染
  - `ThinkingStepContent.tsx` — 单步内容（Markdown + 代码高亮）

**T7: Toast 通知系统** (`frontend/src/components/ui/Toast.tsx`)
- `ToastProvider` + `useToast` Hook + `ToastContainer`
- 支持 success/error/warning/info 四种类型
- 自动消失（默认 5s）、最多同时 3 条、溢出排队
- slide-in-right 入场 + fade-out 退场动画

**T11: UI 共享组件迁移** (`frontend/src/components/ui/`)
- `Button.tsx` — variant: primary/secondary/ghost/danger, size: sm/md/lg
- `Card.tsx` — 统一 rounded-xl + border-fin-border + bg-fin-card
- `Badge.tsx` — variant: default/success/danger/warning/info
- `Input.tsx` — 统一 border/bg/focus 样式
- 迁移 SettingsModal、SubscribeModal、Watchlist、NewsFeed 使用共享组件

**T12: 全局键盘快捷键** (`frontend/src/hooks/useKeyboardShortcuts.ts`)
- Ctrl+K / Cmd+K: 打开命令面板
- Ctrl+/: 切换右侧面板
- Escape: 关闭命令面板
- `CommandPalette.tsx`: 搜索过滤 + 方向键导航 + Enter 执行

**T13: 持仓盈亏计算** (`frontend/src/hooks/usePortfolioPnL.ts`)
- `usePortfolioPnL` Hook: 基于 avgCost × shares vs 实时报价计算 P&L
- `HoldingsPnLCard.tsx`: 持仓明细卡片（盈亏金额 + 百分比 + 颜色标识）

### 3. 响应式 & 设计系统

**T3: 断点统一** (`frontend/src/config/breakpoints.ts`)
- 共享 `BREAKPOINTS` 常量: sm/md/lg/xl/2xl
- `isBelowBreakpoint()` 工具函数
- `useIsMobileLayout` 改用共享断点

### 4. 后端新功能

**T4: 研报库三层数据模型** (`backend/services/report_index.py`)
- 新增字段: `source_type` (ai_generated | official_filing | third_party)
- 新增字段: `filing_type`, `publisher`
- 迁移脚本: `scripts/report_index_v2_migrate.py`
- `list_reports()` 支持 `source_type` 过滤

**T5: 智能任务系统 API** (`backend/services/daily_tasks.py` + `backend/api/task_router.py`)
- `/api/tasks/daily` endpoint
- 基于 watchlist + 研报时效 + 未读新闻 + 风险偏好生成每日任务
- 最多 5 条，按 priority 排序（1=高, 3=低）

### 5. UX 体验增强

**T8: dry_run 模式提示** (`backend/api/system_router.py` + `WorkspaceShell.tsx`)
- `/health` 端点返回 `live_tools` 状态
- 前端启动时检测并 Toast 警告

**T9: 新闻降级通知** (`frontend/src/components/dashboard/NewsFeed.tsx`)
- 检测 marketNews + impactNews 均为空时，Toast 提示「数据源降级」
- 使用 ref 确保每次 mount 仅通知一次

### 6. 文档 & 质量

**T10: docs/06 拆分**
- `docs/06a_LANGGRAPH_DESIGN_SPEC.md` — 设计规范
- `docs/06b_LANGGRAPH_CHANGELOG.md` — 变更日志

**T14: ESLint 清零**
- 修复 8 个 ESLint errors/warnings → 0
- 修复项: unused imports (3), react-refresh suppress (1), useCallback deps (1), unused type (1)

**T15: E2E 测试补充** (`frontend/e2e/sprint2-features.spec.ts`)
- 3 个 test suite, 11 个测试用例
- Workbench 导航 (3), Mobile sidebar (3), Command palette (5)

---

## 验证结果

```
ESLint:     0 errors, 0 warnings  ✅
TypeScript: tsc --noEmit 通过      ✅
Backend:    11/11 tests passed     ✅
```

---

## 变更统计

| 类别 | 新增 | 修改 |
|------|------|------|
| 前端组件 | 8 | 12 |
| 后端服务 | 3 | 4 |
| 测试文件 | 1 | 0 |
| 文档 | 2 | 2 |
| 配置/脚本 | 2 | 1 |
| **合计** | **16** | **19** |

---

## 下一步 (Sprint 3 建议)

- [ ] 研报库前端 UI（筛选/批量/动态任务卡片）
- [ ] 深度分析入口（Workbench 一键发起）
- [ ] 对比视图（多 ticker 并排）
- [ ] 笔记/收藏/快捷键扩展
- [ ] CI/CD pipeline (GitHub Actions)
