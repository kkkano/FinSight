# FinSight 对话式 Agent 执行计划

> **创建日期**: 2025-11-30  
> **状态**: 🟡 进行中  
> **当前阶段**: Phase 5 - React + TypeScript 前端 (可选)

---

## 📋 执行原则

1. **单 Agent 优先** - 先做好单 Agent，稳定后再考虑多 Agent
2. **测试驱动** - 每完成一步必须测试通过才能继续
3. **英文提示词** - 所有 SYSTEM_PROMPT 用英文，中文翻译记录在文档
4. **增量开发** - 小步快跑，每个 PR 可独立验证
5. **文档同步** - 每次更新都记录到 DEVELOPMENT_LOG.md

---

## 🎯 总体目标

将 FinSight 从**单次报告生成器**升级为**对话式股票分析 Agent**，并最终提供 React + TypeScript 前端界面。

---

## 📅 分阶段执行计划

### Phase 1: 基础架构与可靠性 (预计 5-7 天)

| 步骤 | 任务 | 优先级 | 预计时间 | 依赖 | 状态 |
|------|------|--------|----------|------|------|
| 1.1 | 创建项目目录结构 | P0 | 0.5h | 无 | ✅ 完成 |
| 1.2 | 实现 DataCache 缓存模块 | P0 | 2h | 1.1 | ✅ 完成 |
| 1.3 | 实现 ToolOrchestrator 多源回退 | P0 | 4h | 1.2 | ✅ 完成 |
| 1.4 | 实现 DataValidator 验证中间件 | P1 | 2h | 1.3 | ✅ 完成 |
| 1.5 | 增强 tools.py 错误处理 | P1 | 2h | 1.3 | ✅ 完成 |
| 1.6 | Phase 1 集成测试 | P0 | 2h | 1.5 | ✅ 完成 |

### Phase 2: 对话能力 (预计 5-7 天) ✅ 已完成

| 步骤 | 任务 | 优先级 | 预计时间 | 依赖 | 状态 |
|------|------|--------|----------|------|------|
| 2.1 | 实现 ContextManager 上下文管理 | P0 | 3h | Phase 1 | ✅ 完成 |
| 2.2 | 实现 ConversationRouter 意图路由 | P0 | 4h | 2.1 | ✅ 完成 |
| 2.3 | 创建多模式提示词 (CHAT/REPORT/ALERT) | P0 | 3h | 2.2 | ✅ 完成 |
| 2.4 | 实现 ChatHandler 快速回答 | P1 | 2h | 2.3 | ✅ 完成 |
| 2.5 | 实现 ReportHandler 深度报告 | P1 | 2h | 2.3 | ✅ 完成 |
| 2.6 | 实现 FollowupHandler 追问处理 | P2 | 2h | 2.5 | ✅ 完成 |
| 2.7 | Phase 2 集成测试 | P0 | 3h | 2.6 | ✅ 完成 |

### Phase 3: 主程序重构与 CLI (预计 3-4 天) ✅ 已完成

| 步骤 | 任务 | 优先级 | 预计时间 | 依赖 | 状态 |
|------|------|--------|----------|------|------|
| 3.1 | 重构 main.py 支持对话模式 | P0 | 3h | Phase 2 | ✅ 完成 |
| 3.2 | 添加对话式 REPL 界面 | P1 | 2h | 3.1 | ✅ 完成 |
| 3.3 | 端到端测试 | P0 | 2h | 3.2 | ✅ 完成 |

### Phase 4: API 后端 (预计 3-4 天) ✅ 已完成

| 步骤 | 任务 | 优先级 | 预计时间 | 依赖 | 状态 |
|------|------|--------|----------|------|------|
| 4.1 | 创建 FastAPI 后端框架 | P0 | 2h | Phase 3 | ✅ 完成 |
| 4.2 | 实现 /chat 对话 API | P0 | 2h | 4.1 | ✅ 完成 |
| 4.3 | 实现 /analyze 报告 API | P1 | 2h | 4.1 | ✅ 完成 |
| 4.4 | 实现 WebSocket 实时推送 | P2 | 3h | 4.2 | ✅ 完成 |
| 4.5 | API 测试 | P0 | 2h | 4.4 | ✅ 完成 |

### Phase 5: React + TypeScript 前端 (预计 7-10 天)

| 步骤 | 任务 | 优先级 | 预计时间 | 依赖 | 状态 |
|------|------|--------|----------|------|------|
| 5.1 | 初始化 React + TS + Vite 项目 | P0 | 1h | Phase 4 | 🔲 待开始 |
| 5.2 | 设计 UI 组件架构 | P0 | 2h | 5.1 | 🔲 待开始 |
| 5.3 | 实现聊天界面组件 | P0 | 4h | 5.2 | 🔲 待开始 |
| 5.4 | 实现股票数据展示组件 | P1 | 3h | 5.2 | 🔲 待开始 |
| 5.5 | 实现报告展示组件 | P1 | 3h | 5.2 | 🔲 待开始 |
| 5.6 | 接入后端 API | P0 | 3h | 5.5 | 🔲 待开始 |
| 5.7 | 响应式设计与优化 | P2 | 2h | 5.6 | 🔲 待开始 |
| 5.8 | 前端测试 | P0 | 2h | 5.7 | 🔲 待开始 |

---

## 📁 目录结构规划

```
FinSight/
├── backend/                    # 🆕 后端代码
│   ├── api/                    # FastAPI 接口
│   │   ├── __init__.py
│   │   ├── main.py            # API 入口
│   │   ├── routes/
│   │   │   ├── chat.py        # 对话接口
│   │   │   └── analyze.py     # 分析接口
│   │   └── websocket.py       # WebSocket
│   │
│   ├── conversation/           # 对话管理
│   │   ├── __init__.py
│   │   ├── router.py          # 意图路由
│   │   └── context.py         # 上下文管理
│   │
│   ├── handlers/               # 模式处理器
│   │   ├── __init__.py
│   │   ├── chat_handler.py
│   │   ├── report_handler.py
│   │   └── followup_handler.py
│   │
│   ├── orchestration/          # 工具编排
│   │   ├── __init__.py
│   │   ├── orchestrator.py    # 核心编排器
│   │   ├── cache.py           # 数据缓存
│   │   └── validator.py       # 数据验证
│   │
│   ├── prompts/                # 提示词模板
│   │   ├── __init__.py
│   │   ├── chat_prompt.py
│   │   ├── report_prompt.py
│   │   └── system_prompts.py  # 统一管理
│   │
│   └── tests/                  # 后端测试
│       ├── __init__.py
│       ├── test_cache.py
│       ├── test_orchestrator.py
│       ├── test_router.py
│       └── smoke_test.py
│
├── frontend/                   # 🆕 React + TS 前端
│   ├── src/
│   │   ├── components/        # UI 组件
│   │   ├── hooks/             # 自定义 Hooks
│   │   ├── services/          # API 调用
│   │   ├── types/             # TypeScript 类型
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
│
├── docs/                       # 文档
│   ├── EXECUTION_PLAN.md      # 本文件
│   ├── DEVELOPMENT_LOG.md     # 开发日志
│   └── PROMPTS_CN.md          # 提示词中文版
│
├── agent.py                    # 保留兼容
├── langchain_agent.py          # 保留
├── tools.py                    # 保留，扩展
├── config.py                   # 保留
└── main.py                     # 重构
```

---

## 🧪 测试策略

### 每步测试要求

| 步骤类型 | 测试要求 | 通过标准 |
|----------|----------|----------|
| 模块实现 | 单元测试 | 所有 assert 通过 |
| 阶段完成 | 集成测试 | 端到端流程正常 |
| 功能合并 | 冒烟测试 | 5 个代表性股票测试通过 |

### 测试代码位置
- 单元测试: `backend/tests/test_*.py`
- 集成测试: `backend/tests/integration/`
- 冒烟测试: `backend/tests/smoke_test.py`

---

## 🔒 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| API 限速导致测试不稳定 | 中 | 使用 mock 数据进行单元测试 |
| LLM 响应不稳定 | 中 | 设置重试机制，降级到规则匹配 |
| 前后端接口不一致 | 低 | 先定义 OpenAPI schema |
| 缓存失效导致数据过时 | 低 | TTL 机制 + 强制刷新选项 |

---

## ✅ 执行确认

**我确认以下计划无误，准备开始执行：**

1. ✅ 从 Phase 1 Step 1.1 开始（创建目录结构）
2. ✅ 每步完成后运行测试
3. ✅ 测试通过后更新 DEVELOPMENT_LOG.md
4. ✅ 测试失败则停止，修复后再继续
5. ✅ 提示词使用英文，中文版记录在 PROMPTS_CN.md

---

## 📊 进度追踪

| 阶段 | 开始时间 | 完成时间 | 状态 |
|------|----------|----------|------|
| Phase 1 | 2025-11-30 | 2025-11-30 | ✅ 完成 |
| Phase 2 | - | - | 🔲 待开始 |
| Phase 3 | - | - | 🔲 待开始 |
| Phase 4 | - | - | 🔲 待开始 |
| Phase 5 | - | - | 🔲 待开始 |

---

*最后更新: 2025-11-30*

