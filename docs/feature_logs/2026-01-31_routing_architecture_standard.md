# 2026-01-31 路由架构标准化

> **版本**: v0.6.8
> **状态**: 已完成核心实现

## 本次变更概述

建立了完整的路由架构标准文档，作为后续开发的规范和决策依据。

## 主要工作

### 1. 创建架构标准文档

**文件**: `docs/ROUTING_ARCHITECTURE_STANDARD.md`

23KB 的完整设计文档，包含：

| 章节 | 内容 |
|------|------|
| 1. 问题诊断 | 8个核心问题、6个 Chat 端点、SchemaRouter 重复调用 |
| 2. 决策过程 | 成熟框架对比、设计取舍、最终决策 |
| 3. 核心原则 | 单入口、单路由、单追问、Fast-path |
| 4. 当前架构 | 组件职责、数据流、调用链 |
| 5. 组件边界 | 5 大组件的明确职责划分 |
| 6. Intent 设计 | 双层 Intent 架构（Layer 1 路由级 + Layer 2 执行级）|
| 7. 数据流 | 4 种场景的完整数据流图 |
| 8. 回归测试 | 64 个测试用例基线 |
| 9. 已知坑点 | 5 个常见错误和避免方法 |
| 10. TODO List | v2 版本待办事项 |
| 11. 代码索引 | 关键文件位置速查 |

### 2. 回归测试用例

**文件**: `backend/tests/test_router_regression_baseline.py`

创建了 64 个回归测试用例，覆盖：

```
TestCoreIntentRouting          # 核心意图路由 (8 用例)
TestBoundaryConditions         # 边界条件 (8 用例)
TestReportIntent               # 报告意图 (10 用例)
TestAlertIntent                # 监控意图 (5 用例)
TestMarketNewsAndSentiment     # 市场新闻/情绪 (8 用例)
TestEconomicEvents             # 经济日历 (5 用例)
TestTickerExtraction           # Ticker 提取 (3 用例)
TestSimpleQueryIndicators      # 简单查询指示词 (4 用例)
TestRoutingConsistency         # 路由一致性 (2 用例)
TestNewsSentiment              # 新闻情绪 (3 用例)
```

### 3. Router 代码修复

**文件**: `backend/conversation/router.py`

修复内容：
- 添加 'hey' 到问候关键词列表
- 重组规则优先级：ALERT → NEWS_SENTIMENT → ECONOMIC_EVENTS → REPORT → CHAT
- 移除重复的代码块
- 确保 ECONOMIC_EVENTS 不被 simple_query_indicators 掩盖

### 4. 文档同步更新

| 文件 | 更新内容 |
|------|---------|
| `docs/01_ARCHITECTURE.md` | 添加路由架构标准引用 |
| `readme.md` | 添加 ROUTING_ARCHITECTURE_STANDARD.md 链接 |
| `readme_cn.md` | 添加路由架构标准说明 |

## 测试结果

```
64 passed in 2.xx seconds
```

所有回归测试通过。

## 关键决策记录

### 为什么采用双层 Intent 设计？

| 层级 | 用途 | 使用者 |
|------|------|--------|
| Layer 1 (router.Intent) | 决定走哪个 Handler | ConversationRouter |
| Layer 2 (AgentIntent) | 决定调用哪些 Agent | IntentClassifier, SupervisorAgent |

**理由**: 两者服务于不同的架构层次，合并会导致职责混乱。

### 为什么 SchemaRouter 是 Clarify 的唯一入口？

1. **统一性**: 追问逻辑集中管理，避免多处重复
2. **可维护性**: 修改追问模板只需改一处
3. **可测试性**: 追问行为可预测、可测试

### 为什么保留规则快速通道？

1. **成本优化**: 简单问候/命令无需调用 LLM
2. **延迟优化**: 规则匹配毫秒级，LLM 调用秒级
3. **可靠性**: 规则行为确定，不受 LLM 漂移影响

## 后续计划

- [ ] Phase D: REPORT 迁移到 LangGraph
- [ ] DeepSearch 接入 RAG
- [ ] 用户长期记忆（向量库）
- [ ] RiskAgent 实现

## 相关文档

- [ROUTING_ARCHITECTURE_STANDARD.md](../ROUTING_ARCHITECTURE_STANDARD.md) - 完整架构标准
- [01_ARCHITECTURE.md](../01_ARCHITECTURE.md) - 系统架构总览
- [2026-01-31_architecture_refactor_guide.md](../Thinking/2026-01-31_architecture_refactor_guide.md) - 重构参考手册
