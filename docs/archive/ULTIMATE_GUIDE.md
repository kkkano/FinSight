# FinSight 终极开发指南

> 📅 创建日期: 2025-12-27
> 🎯 目标: 将 FinSight 从「单Agent+工具」升级为「多Agent协作+反思循环+IR结构化」的专业金融研究平台

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [01_ARCHITECTURE.md](./01_ARCHITECTURE.md) | 终极架构设计图 + BettaFish 核心机制借鉴 |
| [02_PHASE0_COMPLETION.md](./02_PHASE0_COMPLETION.md) | 阶段0补完指南（熔断器已完成，剩余 tracing） |
| [03_PHASE1_IMPLEMENTATION.md](./03_PHASE1_IMPLEMENTATION.md) | 阶段1实施指南（多Agent + 反思循环） |
| [04_CODE_EXAMPLES.md](./04_CODE_EXAMPLES.md) | 核心代码示例（可直接复制使用） |

---

## 🎯 当前进度总览

```
整体进度: ████████░░░░░░░░░░░░ 约 30%

阶段0（基座强化）: █████████░ 90% - 仅缺节点级 tracing
阶段1（子Agent雏形）: ░░░░░░░░░░ 0% - 尚未开始
阶段2（IR+按需Agent）: ░░░░░░░░░░ 0% - 尚未开始
```

### 已完成 ✅
- KV 缓存 (`backend/orchestration/cache.py`)
- 熔断器 (`backend/services/circuit_breaker.py`)
- 工具编排器 (`backend/orchestration/orchestrator.py`)
- 前端诊断面板 (`frontend/src/components/DiagnosticsPanel.tsx`)
- FetchResult 标准化输出

### 待完成 🚧
- LangGraph 节点级 tracing
- `backend/agents/` 目录（多Agent架构）
- ForumHost 冲突消解
- IR Schema + Renderer

---

## 🚀 快速开始

### 立即行动（今天）

```bash
# 1. 创建 agents 目录
mkdir backend/agents

# 2. 创建基础文件
touch backend/agents/__init__.py
touch backend/agents/base.py
touch backend/agents/price_agent.py
```

### 本周目标

1. **Day 1-2**: 实现 `BaseFinancialAgent` + `AgentOutput`
2. **Day 3-4**: 实现 `PriceAgent`（复用现有 orchestrator）
3. **Day 5-7**: 实现 `NewsAgent`（含反思循环）

---

## 🔑 核心设计原则

### 借鉴 BettaFish 的关键机制

1. **论坛式协作** - Agent 不直接通信，通过 ForumHost 异步交流
2. **反思循环** - 初始搜索 → 总结 → 识别空白 → 精炼搜索 × 2-3轮
3. **IR 中间表示** - 先生成结构化 JSON，校验后再渲染
4. **高召回策略** - 多源并行搜索，LLM 仅做摘要

### LangGraph 最佳实践

1. **状态设计** - 使用 `Annotated[List, add_messages]` 累积消息
2. **Supervisor 模式** - 中央协调器分发任务到各专业 Agent
3. **子图隔离** - 每个 Agent 内部状态独立，通过标准接口通信
4. **硬限制** - `MAX_REFLECTIONS` 防止无限循环

---

## 📁 目标目录结构

```
backend/
├── agents/                    # 🆕 阶段1新建
│   ├── __init__.py
│   ├── base.py               # AgentOutput + BaseFinancialAgent
│   ├── price_agent.py        # 行情Agent（无反思）
│   ├── news_agent.py         # 新闻Agent（含反思）
│   ├── technical_agent.py    # 技术Agent
│   └── fundamental_agent.py  # 基本面Agent
├── orchestration/
│   ├── orchestrator.py       # ✅ 已有
│   ├── cache.py              # ✅ 已有
│   ├── supervisor.py         # 🆕 多Agent调度
│   └── forum.py              # 🆕 ForumHost
├── services/
│   └── circuit_breaker.py    # ✅ 已有
├── report/                    # 🆕 阶段2
│   └── ir.py                 # ReportIR + Renderer
└── langchain_agent.py        # ✅ 已有（待增强）
```

---

## ⚠️ 注意事项

1. **不要破坏现有功能** - 新 Agent 架构与现有 `langchain_agent.py` 并行
2. **渐进式迁移** - 先让新架构跑通，再逐步替换
3. **测试先行** - 每个 Agent 都要有独立测试
4. **文档同步** - 完成一个模块就更新 README

---

## 📖 参考资料

- [BettaFish GitHub](https://github.com/666ghj/BettaFish)
- [LangGraph Reflection Tutorial](https://langchain-ai.github.io/langgraph/tutorials/reflection/reflection/)
- [LangGraph Multi-Agent](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [12.9plan.md](./feature_logs/12.9plan.md) - 原始计划文档
