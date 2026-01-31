# 路由架构决策思考记录

> **日期**: 2026-01-31
> **主题**: 为什么这样设计路由架构？

## 一、问题背景

### 1.1 发现的混乱现象

在代码审查中发现了以下问题：

1. **6 个 Chat 端点共存** - `/chat`, `/chat/stream`, `/chat/smart`, `/chat/smart/stream`, `/chat/supervisor`, `/chat/supervisor/stream`
2. **SchemaRouter 被调用两次** - API 层调一次，Router 内又调一次
3. **双 Intent 系统** - `router.Intent` 和 `intent_classifier.Intent` 并存
4. **追问来源多处** - SchemaRouter、Supervisor、ChatHandler 都在生成追问

### 1.2 为什么这是问题？

```
用户视角：
"我问了一个问题，为什么有时候追问格式不一样？"
"为什么相似的问题有时候走不同的流程？"

开发者视角：
"我要改追问逻辑，需要改几个地方？" → 3+处
"我要调试路由，需要看几个文件？" → 5+个
"我加一个新意图，需要改几处？" → 4+处
```

## 二、决策过程

### 2.1 参考了哪些成熟框架？

| 框架 | 编排模式 | 特点 |
|------|---------|------|
| LangGraph | 图式编排 | 状态保持、可恢复、interrupt |
| LangChain | Router/Supervisor | 意图分类 + Agent 协作 |
| CrewAI | Sequential/Hierarchical | 经理-工人式 |
| AutoGen | Agent-Agent 对话 | 自动协作 |

### 2.2 成熟框架的共同特征

1. **入口少** - 通常 1-2 个统一入口
2. **路由一层** - 分类一次，不重复判断
3. **追问统一** - interrupts/clarify 节点集中管理
4. **Supervisor 唯一** - 只有一个编排中心

### 2.3 FinSight 的独特性

FinSight 有一个独创的 **ForumHost**（群体智慧综合），这在主流框架中少见。需要保留这个创新。

## 三、最终决策

### 3.1 单入口原则

**决策**: 只保留 `/chat/supervisor` 和 `/chat/supervisor/stream`

**理由**:
- 减少维护成本
- 统一用户体验
- 简化调试流程

### 3.2 单路由原则

**决策**: SchemaRouter 只在 `ConversationRouter.route()` 内调用一次

**理由**:
- 避免重复计算
- 避免状态不一致
- 便于追踪和调试

### 3.3 单追问原则

**决策**: Clarify 只来自 SchemaRouter

**理由**:
- 追问模板统一管理
- 行为可预测
- 测试简单

### 3.4 双层 Intent 设计

**决策**: 保留两层 Intent，但明确职责边界

```
Layer 1: router.Intent
├── 用途: 决定走哪个 Handler
├── 使用者: ConversationRouter
└── 值: CHAT, REPORT, ALERT, GREETING, CLARIFY...

Layer 2: AgentIntent (原 intent_classifier.Intent)
├── 用途: 决定调用哪些专家 Agent
├── 使用者: IntentClassifier, SupervisorAgent
└── 值: PRICE, NEWS, TECHNICAL, FUNDAMENTAL...
```

**为什么不合并？**

如果合并，会出现：
- 职责混乱：一个枚举既要决定 Handler 又要决定 Agent
- 维护困难：修改一处可能影响两层逻辑
- 语义模糊：PRICE 是意图还是 Agent？

## 四、规则优先级设计

### 4.1 为什么 ECONOMIC_EVENTS 要放在 simple_query_indicators 之前？

**问题场景**:
```
用户: "最近有什么宏观事件"
```

如果 simple_query_indicators 先匹配：
- "有什么" 命中 → 返回 CHAT ❌

如果 ECONOMIC_EVENTS 先匹配：
- "宏观事件" 命中 → 返回 ECONOMIC_EVENTS ✅

**决策**: 专业意图（ALERT, NEWS_SENTIMENT, ECONOMIC_EVENTS）优先于通用指示词。

### 4.2 最终优先级

```
1. GREETING      - 问候最先（高置信度，无成本）
2. ALERT         - 监控/提醒（用户明确意图）
3. NEWS_SENTIMENT - 新闻情绪（专业意图）
4. ECONOMIC_EVENTS - 经济日历（专业意图）
5. REPORT        - 深度分析（需要 ticker）
6. CHAT          - 通用查询（默认路径）
7. FOLLOWUP      - 追问（需要上下文）
8. CLARIFY       - 兜底（信息不足）
```

## 五、回归测试策略

### 5.1 为什么需要回归测试？

**痛点**: 每次修改路由逻辑都担心破坏现有行为

**解决**: 64 个基线测试用例，覆盖所有意图和边界条件

### 5.2 测试用例设计原则

1. **必须通过的核心用例** - 8 个基本场景
2. **边界条件** - 拼音、英文、混合查询
3. **参数化测试** - 同类意图多个示例
4. **一致性测试** - 相同输入必须相同输出

## 六、经验教训

### 6.1 避免的坑

1. **不要在 API 层直接调用 SchemaRouter** - 应该通过 Router
2. **不要在多处生成追问** - 统一由 SchemaRouter 生成
3. **不要混淆两层 Intent** - 明确职责边界
4. **不要忽视规则优先级** - 专业意图优先于通用指示词

### 6.2 收获的模式

1. **单入口模式** - 简化维护和调试
2. **职责单一** - 每个组件只做一件事
3. **回归保护** - 每次修改都有测试保障
4. **文档驱动** - 先写标准文档再实现

## 七、后续演进

### 7.1 Phase D: REPORT 迁移到 LangGraph

REPORT 路径天然适合 DAG：
- 多 Agent 并行执行 → LangGraph `Send` API
- Forum 综合 → LangGraph 节点
- 追问中断 → LangGraph `interrupt`

### 7.2 保持手搓的部分

CHAT 路径保持手搓：
- 简单查询 1-2 Agent 即可
- Fast-path 直接返回
- 框架开销不值得

## 八、总结

**核心洞察**: FinSight 的架构设计没有问题，问题在于"实现路径重复"。

**解决方案**: 收敛为成熟的 Supervisor 模式 + 统一的追问入口。

**价值**: 减少 60% 的路由相关代码，提升可维护性和可测试性。

---

> **文档维护者**: AI Assistant (幽浮喵)
> **最后更新**: 2026-01-31
