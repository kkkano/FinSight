# FinSight 路由架构标准文档

> **文档版本**: v1.0
> **创建日期**: 2026-01-31
> **状态**: 开发标准
> **目的**: 记录架构决策过程，作为后续开发的标准参考

---

## 目录

1. [问题诊断](#1-问题诊断)
2. [决策过程与推导](#2-决策过程与推导)
3. [核心架构原则](#3-核心架构原则)
4. [当前架构详解](#4-当前架构详解)
5. [组件职责边界](#5-组件职责边界)
6. [Intent 枚举设计](#6-intent-枚举设计)
7. [数据流说明](#7-数据流说明)
8. [回归测试基线](#8-回归测试基线)
9. [已知的"坑"与规避策略](#9-已知的坑与规避策略)
10. [TODO List v2](#10-todo-list-v2)
11. [附录：关键代码位置索引](#11-附录关键代码位置索引)

---

## 1. 问题诊断

### 1.1 原始问题

在重构前，系统存在以下问题：

| 问题 | 症状 | 根因 |
|------|------|------|
| **Intent 枚举混淆** | 两处定义不同的 Intent 枚举，开发者困惑 | 缺乏清晰的层次划分文档 |
| **路由逻辑分散** | 规则匹配、LLM 分类、Schema 验证三套逻辑交织 | 单一职责原则违反 |
| **Clarify 逻辑不一致** | 有时走 SchemaRouter，有时走规则匹配 | 没有统一的澄清入口 |
| **测试覆盖不足** | 边界条件容易遗漏 | 缺乏回归测试基线 |

### 1.2 为什么需要两套 Intent

这是**核心设计决策**，必须理解：

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户查询入口                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: ConversationRouter (router.py)                        │
│  ─────────────────────────────────────────                      │
│  Intent: CHAT | REPORT | ALERT | GREETING | CLARIFY | FOLLOWUP  │
│                                                                 │
│  职责: 决定走哪个 Handler                                         │
│  - CHAT      → ChatHandler (快速问答)                            │
│  - REPORT    → SupervisorAgent (深度报告)                        │
│  - ALERT     → AlertHandler (监控订阅)                           │
│  - GREETING  → 直接响应                                          │
│  - CLARIFY   → 请求澄清                                          │
│  - FOLLOWUP  → FollowupHandler                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (仅当 CHAT/REPORT)
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: IntentClassifier (keywords.py)                        │
│  ─────────────────────────────────────────                      │
│  AgentIntent: PRICE | NEWS | TECHNICAL | FUNDAMENTAL | MACRO    │
│                                                                 │
│  职责: 决定调用哪些专家 Agent                                     │
│  - PRICE       → PriceAgent                                     │
│  - NEWS        → NewsAgent                                      │
│  - TECHNICAL   → TechnicalAgent                                 │
│  - FUNDAMENTAL → FundamentalAgent                               │
│  - MACRO       → MacroAgent                                     │
└─────────────────────────────────────────────────────────────────┘
```

**关键洞察**：
- `router.py` 的 Intent 是**路由级别**（决定走哪条路）
- `keywords.py` 的 AgentIntent 是**执行级别**（决定调用谁）
- 两者服务于**不同的架构层次**，不应合并！

---

## 2. 决策过程与推导

### 2.1 决策 1：保留双层 Intent 设计

**问题**: 为什么不合并成一套 Intent？

**推导过程**:
```
假设合并 → 单一 Intent 枚举包含 15+ 种类型
         → Handler 选择逻辑变复杂
         → Agent 选择逻辑也变复杂
         → 违反单一职责原则
         → 维护成本上升

结论: 保持分层，各司其职
```

**最终决策**:
- Layer 1 (ConversationRouter): 粗粒度路由 (8 种 Intent)
- Layer 2 (IntentClassifier): 细粒度分类 (12 种 AgentIntent)

### 2.2 决策 2：SchemaRouter 作为 Clarify 唯一入口

**问题**: Clarify 逻辑散落在多处，如何统一？

**推导过程**:
```
原状态:
  - router._quick_match() 可能返回 CLARIFY
  - router._llm_classify() 可能返回 CLARIFY
  - schema_router 可能返回 CLARIFY
  → 三个来源，行为不一致

期望状态:
  - 所有 CLARIFY 都通过 SchemaRouter
  - SchemaRouter 负责验证参数完整性
  - SchemaRouter 负责生成澄清问题
  → 单一来源，行为一致
```

**最终决策**:
```python
# router.py 中的处理逻辑
if intent == Intent.CLARIFY:
    metadata["clarify_fallback"] = True
    intent = Intent.CHAT  # 降级为 CHAT，不直接返回 CLARIFY
```

### 2.3 决策 3：规则优先，LLM 兜底

**问题**: 何时使用规则匹配，何时使用 LLM？

**推导过程**:
```
规则匹配:
  ✓ 速度快 (0ms vs 500ms+)
  ✓ 可预测
  ✓ 无成本
  ✗ 覆盖范围有限

LLM 分类:
  ✓ 泛化能力强
  ✓ 处理模糊表达
  ✗ 慢且有成本
  ✗ 可能不稳定

最优策略: 规则优先 + LLM 兜底
```

**最终决策**:
```python
# 执行顺序
1. _quick_match()        # 规则快速匹配
2. schema_router.route() # Schema 验证 (含 LLM 调用)
3. _llm_classify()       # LLM 兜底 (仅当前两步无结果)
```

### 2.4 决策 4：SlotCompletenessGate 业务规则层

**问题**: Schema 验证只能检查字段存在性，无法处理业务逻辑

**推导过程**:
```
场景: 用户输入 "特斯拉"
  - Schema 角度: ticker 字段可以从 "特斯拉" 解析出 TSLA ✓
  - 业务角度: 用户没说要干什么！是查价格还是分析？

需要一层业务规则:
  - 检测 "只有公司名，没有动作词" 的情况
  - 主动询问用户意图
```

**最终决策**: 引入 `SlotCompletenessGate` 类
```python
class SlotCompletenessGate:
    """
    业务规则层，超越 Schema 的字段验证
    - 检测 "公司名 + 无动作词" → 请求澄清
    - 检测 "分析意图但无 ticker" → 请求提供 ticker
    - 检测 "比较意图但 ticker < 2" → 请求更多 ticker
    """
```

---

## 3. 核心架构原则

### 3.1 单一职责原则 (SRP)

| 组件 | 唯一职责 |
|------|----------|
| `ConversationRouter` | 路由决策（走哪个 Handler） |
| `SchemaToolRouter` | 参数验证与补全 |
| `SlotCompletenessGate` | 业务规则验证 |
| `IntentClassifier` | 细粒度意图分类 |
| `ConversationAgent` | 组件编排与流程控制 |

### 3.2 开闭原则 (OCP)

新增工具/意图时：
```python
# 好的做法：扩展 DEFAULT_TOOL_SPECS
DEFAULT_TOOL_SPECS["new_tool"] = ToolSpec(
    name="new_tool",
    schema=NewToolSchema,
    intent="chat",
    description="New tool description",
)

# 不好的做法：修改 _quick_match() 中的 if-else 链
```

### 3.3 依赖倒置原则 (DIP)

```python
# ConversationAgent 依赖抽象接口
class ConversationAgent:
    def __init__(self, llm=None):
        self.router = ConversationRouter(llm)  # 依赖注入
        self.context = ContextManager()
```

---

## 4. 当前架构详解

### 4.1 整体流程图

```
用户输入
    │
    ▼
┌───────────────────────────────────────────────────────────┐
│ ConversationAgent.chat()                                  │
│   │                                                       │
│   ├─→ ContextManager.update()  # 更新上下文               │
│   │                                                       │
│   ├─→ ConversationRouter.route()                          │
│   │       │                                               │
│   │       ├─→ _quick_match()      # 规则快速匹配          │
│   │       │     ├─ GREETING?  → 返回                      │
│   │       │     ├─ REPORT?    → 返回                      │
│   │       │     ├─ ALERT?     → 返回                      │
│   │       │     └─ 其他       → 继续                      │
│   │       │                                               │
│   │       ├─→ SchemaToolRouter.route_query()              │
│   │       │     ├─ LLM → {tool_name, args, confidence}    │
│   │       │     ├─ SlotCompletenessGate.validate()        │
│   │       │     ├─ Schema validation                      │
│   │       │     └─ 返回 SchemaRouteResult                 │
│   │       │                                               │
│   │       └─→ _llm_classify()     # LLM 兜底              │
│   │                                                       │
│   ├─→ Handler 分发                                        │
│   │     ├─ GREETING  → 直接响应                           │
│   │     ├─ CHAT      → ChatHandler                        │
│   │     ├─ REPORT    → SupervisorAgent                    │
│   │     ├─ ALERT     → AlertHandler                       │
│   │     ├─ FOLLOWUP  → FollowupHandler                    │
│   │     └─ CLARIFY   → 返回澄清问题                        │
│   │                                                       │
│   └─→ 返回响应                                            │
└───────────────────────────────────────────────────────────┘
```

### 4.2 SchemaToolRouter 详解

```
┌─────────────────────────────────────────────────────────────┐
│ SchemaToolRouter.route_query(query, context)                │
│                                                             │
│ Step 1: 检查 pending_tool_call (多轮对话续接)               │
│         └─ 有 → _handle_pending() → 补全参数               │
│                                                             │
│ Step 2: _call_llm_for_tool()                                │
│         └─ LLM 返回 {tool_name, args, confidence}           │
│                                                             │
│ Step 3: 置信度检查                                          │
│         └─ confidence < 0.7 → Clarify                       │
│                                                             │
│ Step 4: SlotCompletenessGate.validate()                     │
│         └─ 业务规则不满足 → Clarify (设置 pending)          │
│                                                             │
│ Step 5: Schema 必填字段验证                                  │
│         └─ 缺少必填字段 → Clarify (设置 pending)            │
│                                                             │
│ Step 6: 应用默认值 → 返回 SchemaRouteResult                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 组件职责边界

### 5.1 职责矩阵

| 组件 | 意图识别 | 参数提取 | 参数验证 | 业务规则 | 流程控制 |
|------|:--------:|:--------:|:--------:|:--------:|:--------:|
| ConversationRouter | ✓ | ✓ | ✗ | ✗ | ✗ |
| SchemaToolRouter | ✗ | ✓ | ✓ | ✗ | ✗ |
| SlotCompletenessGate | ✗ | ✗ | ✗ | ✓ | ✗ |
| ConversationAgent | ✗ | ✗ | ✗ | ✗ | ✓ |
| IntentClassifier | ✓ | ✗ | ✗ | ✗ | ✗ |

### 5.2 边界规则

**规则 1**: ConversationRouter 不应直接返回 CLARIFY
```python
# 错误做法
if some_condition:
    return Intent.CLARIFY, metadata

# 正确做法
# 让 SchemaRouter 处理 clarify 逻辑
```

**规则 2**: SchemaToolRouter 不应处理 Handler 选择
```python
# 错误做法
if tool_name == "analyze_stock":
    return self._call_report_handler()

# 正确做法
# 只返回 intent 和 metadata，由 ConversationAgent 分发
```

**规则 3**: SlotCompletenessGate 只做验证，不做执行
```python
# 错误做法
def validate(...):
    if missing_ticker:
        ticker = self._fetch_from_somewhere()  # 不应该！

# 正确做法
def validate(...):
    if missing_ticker:
        return {"should_clarify": True, "reason": "..."}
```

---

## 6. Intent 枚举设计

### 6.1 Layer 1: 路由级 Intent (`router.py`)

```python
class Intent(Enum):
    """路由级别意图 - 决定走哪个 Handler"""

    CHAT = "chat"                    # 快速问答 → ChatHandler
    REPORT = "report"                # 深度分析 → SupervisorAgent
    ALERT = "alert"                  # 监控订阅 → AlertHandler
    ECONOMIC_EVENTS = "economic_events"  # 经济日历
    NEWS_SENTIMENT = "news_sentiment"    # 新闻情绪
    CLARIFY = "clarify"              # 需要澄清
    FOLLOWUP = "followup"            # 追问
    GREETING = "greeting"            # 问候/闲聊
```

### 6.2 Layer 2: 执行级 Intent (`keywords.py`)

```python
class AgentIntent(Enum):
    """执行级别意图 - 决定调用哪些专家 Agent"""

    GREETING = "greeting"            # 问候
    PRICE = "price"                  # 价格查询 → PriceAgent
    NEWS = "news"                    # 新闻查询 → NewsAgent
    SENTIMENT = "sentiment"          # 情绪分析
    TECHNICAL = "technical"          # 技术分析 → TechnicalAgent
    FUNDAMENTAL = "fundamental"      # 基本面 → FundamentalAgent
    MACRO = "macro"                  # 宏观分析 → MacroAgent
    REPORT = "report"                # 综合报告
    COMPARISON = "comparison"        # 对比分析
    SEARCH = "search"                # 搜索
    CLARIFY = "clarify"              # 需要澄清
    OFF_TOPIC = "off_topic"          # 离题
```

### 6.3 Intent 映射关系

```
Layer 1 Intent    →    Layer 2 处理方式
─────────────────────────────────────────
CHAT             →    IntentClassifier 细分
REPORT           →    SupervisorAgent 调度多个 AgentIntent
ALERT            →    专用 AlertHandler
GREETING         →    直接响应
CLARIFY          →    返回澄清问题
FOLLOWUP         →    FollowupHandler
```

---

## 7. 数据流说明

### 7.1 正常查询流程

```
输入: "苹果股票现在多少钱"

1. ConversationRouter._quick_match()
   └─ 匹配关键词 "多少钱" → 返回 None (继续)

2. SchemaToolRouter.route_query()
   ├─ LLM 返回: {tool_name: "get_price", args: {ticker: "AAPL"}, confidence: 0.95}
   ├─ SlotCompletenessGate.validate() → None (通过)
   ├─ Schema 验证 → 通过
   └─ 返回: SchemaRouteResult(intent="chat", metadata={...})

3. ConversationAgent 分发到 ChatHandler

4. ChatHandler 调用 PriceAgent 获取价格

5. 返回响应
```

### 7.2 需要澄清的流程

```
输入: "特斯拉"

1. ConversationRouter._quick_match()
   └─ 无明确意图关键词 → 返回 None

2. SchemaToolRouter.route_query()
   ├─ LLM 返回: {tool_name: "get_price", args: {ticker: "TSLA"}, confidence: 0.6}
   ├─ SlotCompletenessGate.validate()
   │   └─ _is_company_name_only() → True
   │   └─ 返回: {should_clarify: True, reason: "company_name_only", question: "..."}
   └─ 返回: SchemaRouteResult(intent="clarify", metadata={...})

3. ConversationAgent 返回澄清问题:
   "您想对特斯拉做什么？查价格、看新闻还是深度分析？"
```

### 7.3 多轮对话流程

```
Turn 1: "分析一下"
  └─ SchemaRouter: missing ticker → Clarify + 设置 pending_tool_call

Turn 2: "苹果"
  └─ SchemaRouter._handle_pending()
     ├─ 从 "苹果" 提取 ticker = "AAPL"
     ├─ 补全 args
     └─ 返回: SchemaRouteResult(intent="report", metadata={ticker: "AAPL"})
```

---

## 8. 回归测试基线

### 8.1 必须通过的测试用例

| 测试用例 | 输入 | 期望 Intent | 期望行为 |
|----------|------|-------------|----------|
| 简单问候 | "你好" | GREETING | 直接响应，不调用 LLM |
| 价格查询 | "AAPL 股价" | CHAT | 调用 PriceAgent |
| 深度分析 | "分析苹果" | REPORT | 调用 SupervisorAgent |
| 对比查询 | "苹果和微软对比" | CHAT | 调用 CompareStocks |
| 监控设置 | "TSLA 跌破 200 提醒我" | ALERT | 调用 AlertHandler |
| 纯公司名 | "特斯拉" | CLARIFY | 返回澄清问题 |
| 追问 | "为什么" (有上下文) | FOLLOWUP | 调用 FollowupHandler |
| 市场情绪 | "市场恐慌指数" | CHAT | 调用 GetMarketSentiment |
| 经济日历 | "最近有什么宏观事件" | ECONOMIC_EVENTS | 调用 GetEconomicEvents |

### 8.2 边界测试

| 测试用例 | 输入 | 关键验证点 |
|----------|------|------------|
| 拼音问候 | "nihao" | 应识别为 GREETING |
| 含金融词的问候 | "你好，我想问股票" | 应识别为 CHAT 而非 GREETING |
| 模糊分析 | "帮我看看这个" (无上下文) | 应返回 CLARIFY |
| 低置信度 | LLM 返回 confidence=0.3 | 应返回 CLARIFY |

### 8.3 测试文件位置

```
backend/tests/
├── test_router_greeting.py          # 问候测试
├── test_router_report_intent.py     # 报告意图测试
├── test_router_market_news_intent.py # 市场新闻测试
├── test_router_clarify_fallback.py  # Clarify 降级测试
└── test_trace_schema.py             # Schema 追踪测试
```

---

## 9. 已知的"坑"与规避策略

### 9.1 坑 1: "分析" 关键词的歧义

**问题**: "分析" 既可能是深度报告，也可能是简单查询

```
"分析一下苹果"     → 应该是 REPORT
"分析一下占比"     → 应该是 CHAT (简单查询)
```

**规避策略**:
```python
# 检查是否有简单查询指示词
simple_query_indicators = ['占比', '比例', '权重', '成分', '构成', ...]
if any(kw in query_lower for kw in simple_query_indicators):
    return Intent.CHAT  # 优先 CHAT
```

### 9.2 坑 2: Context 丢失导致 FOLLOWUP 失败

**问题**: 用户说 "为什么"，但上下文已过期

**规避策略**:
```python
if any(kw in query_lower for kw in followup_keywords):
    if context_summary and context_summary != "无历史对话":
        return Intent.FOLLOWUP
    else:
        metadata["clarify_reason"] = "followup_without_context"
        return Intent.CLARIFY  # 有追问词但无上下文 → 澄清
```

### 9.3 坑 3: SchemaRouter pending 过期

**问题**: 用户中途换话题，pending_tool_call 还在

**规避策略**:
```python
# 设置 TTL
if self._pending_expired(pending, self.pending_ttl_seconds):  # 默认 600 秒
    self._clear_pending(context)
```

### 9.4 坑 4: Intent 枚举导入混淆

**问题**: 从错误的模块导入 Intent

```python
# 错误！这会导入执行级 Intent
from backend.config.keywords import AgentIntent as Intent

# 正确
from backend.conversation.router import Intent  # 路由级
from backend.config.keywords import AgentIntent  # 执行级
```

**规避策略**: 在代码顶部添加注释说明

### 9.5 坑 5: Clarify 循环

**问题**: 某些场景下可能无限 Clarify

**规避策略**:
```python
# router.py 中强制降级
if intent == Intent.CLARIFY:
    metadata["clarify_fallback"] = True
    intent = Intent.CHAT  # 最终降级到 CHAT，避免循环
```

---

## 10. TODO List v2

### Phase 1: 核心稳定化 (当前)

- [x] 统一 Intent 枚举文档说明
- [x] SchemaRouter 作为 Clarify 唯一入口
- [x] SlotCompletenessGate 业务规则层
- [ ] 补全回归测试用例
- [ ] 性能基准测试

### Phase 2: 功能增强

- [ ] 多轮对话上下文持久化
- [ ] 意图纠正机制 ("不对，我是想问...")
- [ ] 用户偏好学习

### Phase 3: 可观测性

- [ ] 路由决策日志标准化
- [ ] Intent 分类准确率监控
- [ ] LLM 调用成本追踪

### Phase 4: 扩展性

- [ ] 插件化 ToolSpec 注册
- [ ] 自定义 SlotCompletenessGate 规则
- [ ] 多语言意图模板

---

## 11. 附录：关键代码位置索引

| 文件 | 关键类/函数 | 用途 |
|------|-------------|------|
| `backend/conversation/router.py` | `Intent` | 路由级意图枚举 |
| `backend/conversation/router.py` | `ConversationRouter` | 主路由器 |
| `backend/conversation/router.py:118` | `route()` | 核心路由方法 |
| `backend/conversation/router.py:238` | `_quick_match()` | 规则快速匹配 |
| `backend/conversation/schema_router.py` | `SchemaToolRouter` | Schema 驱动路由 |
| `backend/conversation/schema_router.py:209` | `SlotCompletenessGate` | 业务规则验证 |
| `backend/conversation/schema_router.py:374` | `route_query()` | Schema 路由入口 |
| `backend/conversation/agent.py` | `ConversationAgent` | 统一入口 |
| `backend/config/keywords.py` | `AgentIntent` | 执行级意图枚举 |
| `backend/config/ticker_mapping.py` | `extract_tickers()` | Ticker 提取 |

---

## 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-01-31 | 初始版本，记录完整架构决策 |

---

> **重要提醒**: 修改路由逻辑前，务必先阅读本文档，理解设计决策背景。如有疑问，先讨论再动手。
