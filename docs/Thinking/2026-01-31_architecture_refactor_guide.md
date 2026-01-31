# FinSight 架构重构参考手册

> **文档版本**: v1.0
> **创建日期**: 2026-01-31
> **目标**: 单入口 + 单路由 + 单追问（保留轻量 SchemaRouter）

---

## 一、架构问题诊断

### 1.1 当前存在的 8 个核心问题

| # | 问题 | 严重程度 | 位置 |
|---|------|:---:|------|
| 1 | **路由混乱** - 6 个 chat 端点共存 | 🔴 高 | `main.py` |
| 2 | **双重路由** - SchemaRouter 调用两次 | 🔴 高 | `main.py` + `router.py` |
| 3 | **双 Intent 系统** - router.Intent vs intent_classifier.Intent | 🟡 中 | `router.py` + `intent_classifier.py` |
| 4 | **旧 Agent 未清理** - ReAct Agent 仍在初始化 | 🟡 中 | `main.py:78-89` |
| 5 | **追问来源多处** - SchemaRouter + Supervisor + ChatHandler | 🔴 高 | 多文件 |
| 6 | **文档与代码不符** - 架构图过时 | 🟡 中 | `docs/` |
| 7 | **编码混乱** - 存在 BOM 标记 | 🟢 低 | `schema_router.py` |
| 8 | **临时文件未清理** - main_temp.py 等 | 🟢 低 | 根目录 |

### 1.2 当前 6 个 Chat 端点（需要收敛）

```
/chat                     ← 待删除
/chat/stream              ← 待删除
/chat/smart               ← 待删除
/chat/smart/stream        ← 待删除
/chat/supervisor          ← 保留（唯一入口）
/chat/supervisor/stream   ← 保留（唯一入口）
```

### 1.3 SchemaRouter 重复调用问题

```
当前流程（错误）:
┌─────────────────────────────────────────────────────────┐
│ /chat/supervisor                                        │
│   └─ SchemaRouter.route_query() ← 第1次调用             │
│        └─ agent.router.route()                          │
│             └─ SchemaRouter.route_query() ← 第2次调用   │
└─────────────────────────────────────────────────────────┘

目标流程（正确）:
┌─────────────────────────────────────────────────────────┐
│ /chat/supervisor                                        │
│   └─ agent.router.route()                               │
│        └─ SchemaRouter.route_query() ← 唯一一次调用     │
└─────────────────────────────────────────────────────────┘
```

---

## 二、2026 成熟多 Agent 编排方式对比

### 2.1 主流框架编排模式

| 框架 | 编排模式 | 适用场景 |
|------|---------|---------|
| **LangGraph** | 图式编排、状态保持、可恢复流程 | 长任务、多步、需要流程控制 |
| **LangChain** | Router（轻量）/ Supervisor（重） | 意图分类 + 多 Agent 协作 |
| **Semantic Kernel** | Concurrent / Sequential / Handoff / Magentic | 标准化编排（实验阶段） |
| **AutoGen** | Agent-Agent 自动对话协作 | 研究型/复杂任务 |
| **CrewAI** | Sequential / Hierarchical | 经理-工人式编排 |

### 2.2 成熟框架的共同取向

| 特征 | 说明 |
|------|------|
| **入口少** | 1~2 个统一入口 |
| **路由一层** | 分类一次，不重复判断 |
| **追问统一** | interrupts / clarify 节点集中管理 |
| **Supervisor 唯一** | 只有一个编排中心 |

### 2.3 FinSight 对应成熟框架的组件

| FinSight 组件 | 对应成熟框架 |
|:---|:---|
| `ConversationRouter` | LangChain Router / CrewAI Hierarchy |
| `SchemaRouter` (追问) | LangChain Subagent interrupts / SK Handoff |
| `SupervisorAgent` | LangChain Supervisor / AutoGen Manager |
| `ForumHost` | 独创的"群体智慧综合"（类似 SK Magentic） |

### 2.4 结论

> **FinSight 的架构设计没有问题，问题在于"实现路径重复"。**
> 收敛后就是成熟的 Supervisor 模式。

---

## 三、目标架构

### 3.1 最终架构图

```
                        ┌──────────────────────────────────────┐
                        │         /chat/supervisor             │
                        │         (唯一入口)                   │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
                        ┌──────────────────────────────────────┐
                        │       ConversationAgent.chat_async   │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
                        ┌──────────────────────────────────────┐
                        │         ConversationRouter           │
                        │                                      │
                        │  ┌────────────────────────────────┐  │
                        │  │  SchemaRouter (轻量, 一次调用)  │  │
                        │  │  - slot 检测                   │  │
                        │  │  - 追问生成 (唯一来源)         │  │
                        │  └────────────────────────────────┘  │
                        └──────────────────┬───────────────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
                    ▼                      ▼                      ▼
            ┌───────────┐          ┌───────────┐          ┌───────────┐
            │  GREETING │          │   ALERT   │          │CHAT/REPORT│
            │  直接回复  │          │  告警处理  │          │           │
            └───────────┘          └───────────┘          └─────┬─────┘
                                                                │
                                                                ▼
                                                   ┌────────────────────────┐
                                                   │    SupervisorAgent     │
                                                   │   (统一编排中心)        │
                                                   │                        │
                                                   │  1. LLM 选择 Agent     │
                                                   │  2. Fast-path 判断     │
                                                   │  3. 并行执行           │
                                                   │  4. Forum 综合         │
                                                   └────────────────────────┘
```

### 3.2 核心原则

| 原则 | 说明 |
|------|------|
| **单入口** | 只保留 `/chat/supervisor` + `/chat/supervisor/stream` |
| **单路由** | SchemaRouter 只在 `ConversationRouter.route()` 内调用一次 |
| **单追问** | Clarify 只来自 SchemaRouter（统一模板） |
| **Fast-path** | 简单查询（1-2 Agent）快速返回，不走 Forum |

---

## 四、4 个硬性条件（必须满足）

> ⚠️ **违反以下任一条件都会导致链路断裂或性能回退**

### 4.1 SchemaRouter 必须保留的能力

| 能力 | 原因 |
|------|------|
| `pending_tool_call` | 多轮追问状态，用户补充"特斯拉"时系统能自动继续 |
| `SlotCompletenessGate` | 防止"分析股票"误走 `get_market_sentiment` |
| `schema_action/args/missing/question` | 下游 Router/Handler/前端测试全依赖这个结构 |
| 低置信度/异常兜底 | LLM 输出格式错或 tool 不在白名单时仍返回 clarify |

### 4.2 SchemaRouter 禁用时必须有 Fallback

```python
# 当 USE_SCHEMA_ROUTER=false 或 LLM 缺失时
if schema_disabled:
    return fallback_clarify("请提供更多信息，例如股票代码或公司名称。")
```

### 4.3 Supervisor 必须有 Fast-path

```python
# 避免简单查询走完整 Forum 流程
if len(selected_agents) <= 2:
    return self._simple_synthesis(results)  # 直接拼接
else:
    return await self._forum_synthesis(results)  # Forum 综合
```

### 4.4 删除旧 Agent 必须同步处理 Diagnostics

```python
# 方案 A: 删除端点
# 方案 B: 返回"未启用"
@app.get("/diagnostics/langgraph")
async def diagnostics_langgraph():
    return {
        "status": "disabled",
        "data": {"available": False, "reason": "langgraph agent removed"},
        "timestamp": datetime.now().isoformat()
    }
```

---

## 五、落地执行清单

### Phase 1｜清理旧入口（不影响核心逻辑）

#### 1.1 删除旧 API 端点

**文件**: `backend/api/main.py`

| 端点 | 操作 |
|------|------|
| `@app.post("/chat")` | 删除整个函数 |
| `@app.post("/chat/stream")` | 删除整个函数 |
| `@app.post("/chat/smart")` | 删除整个函数 |
| `@app.post("/chat/smart/stream")` | 删除整个函数 |

**结果**: 只保留 `/chat/supervisor` 和 `/chat/supervisor/stream`

#### 1.2 删除旧 ReAct Agent 初始化

**文件**: `backend/api/main.py`

删除以下代码块:
```python
agent = CreateReActAgent(
    use_llm=True,
    use_orchestrator=True,
    use_report_agent=True
)
```

删除相关 import:
```python
from backend.conversation.agent import create_agent as CreateReActAgent
```

#### 1.3 处理 /diagnostics/langgraph

**文件**: `backend/api/main.py`

选择 A（删除）或 B（返回未启用）。

---

### Phase 2｜SchemaRouter 轻量化（保留核心能力）

**文件**: `backend/conversation/schema_router.py`

#### 2.1 必须保留

- `pending_tool_call` 机制
- `SlotCompletenessGate` 类
- `schema_action / schema_args / schema_missing / schema_question` 输出结构

#### 2.2 可以精简

- 复杂异常分支
- 过长的工具描述 / `tool_lines`
- 多余 fallback 解释信息

#### 2.3 必须保留兜底

```python
if invalid_json or unknown_tool:
    return {"schema_action": "clarify", "schema_question": "..."}
```

---

### Phase 3｜Router 单路由

#### 3.1 确认 SchemaRouter 只在 Router 内调用

**文件**: `backend/conversation/router.py`

确认保留:
```python
schema_router = self._get_schema_router()
if schema_router:
    schema_result = schema_router.route_query(...)
```

#### 3.2 删除 API 层 SchemaRouter 调用

**文件**: `backend/api/main.py`

删除 `/chat/supervisor` 和 `/chat/supervisor/stream` 内的 SchemaRouter 直接调用。

改为:
```python
intent, metadata, _handler = agent.router.route(...)
```

---

### Phase 4｜Supervisor 统一编排

#### 4.1 CHAT/REPORT 统一走 Supervisor

**文件**: `backend/conversation/agent.py`

调整逻辑:
- CHAT 不再直接走 ChatHandler
- 改为 Supervisor 处理（但保留 fast-path）

#### 4.2 Supervisor 内做 fast-path

**文件**: `backend/orchestration/supervisor_agent.py`

```python
async def process(self, query, tickers, context):
    agents = await self._select_agents(query)
    results = await asyncio.gather(...)

    if len(agents) <= 2:
        return self._simple_synthesis(results)
    else:
        return await self._forum_synthesis(results)
```

#### 4.3 删除硬编码追问

**文件**: `backend/orchestration/supervisor_agent.py`

删除自己生成 clarify 文案的逻辑，必须走 SchemaRouter 生成的 `schema_question`。

---

### Phase 5｜清理 + 测试

#### 5.1 删除临时文件

```
backend/api/main_temp.py
*.bak / backup 文件
```

#### 5.2 统一编码

新增 `.gitattributes`:
```
*.py text eol=lf
*.md text eol=lf
```

#### 5.3 测试

```bash
pytest
```

#### 5.4 回归测试

- "分析股票" → 追问 ticker
- "TSLA 分析" → Supervisor 正常执行
- 简单问价 → fast-path 快速返回

---

## 六、后续迁移路线（Phase A-D）

> 当前 Phase 1-5 完成后，可考虑以下迁移

### Phase A: 收敛现状 ✅
即当前正在做的事情。

### Phase B: 统一意图与状态模型
- `ConversationRouter.Intent` 作为唯一对话级意图
- `IntentClassifier.Intent` 改名为 `AgentIntent`
- Trace/metadata 统一字段命名

### Phase C: 统一多 Agent 编排为"单控制器"
- Chat 也走 Supervisor（带 fast-path）
- Report 走 Supervisor + Forum
- 不再区分 ChatHandler / ReportHandler

### Phase D: REPORT 迁移到 LangGraph（详细规划）

> **推荐策略**: 先把 REPORT 路径迁入 LangGraph，Chat 继续手搓
> **理由**: REPORT 天然适合 DAG（多 Agent → Forum → 合成），风险最低

#### D.1 为什么只迁移 REPORT？

| 对比项 | REPORT | CHAT |
|--------|--------|------|
| 流程复杂度 | 高（多 Agent + Forum + 合成） | 低（1-2 Agent 直接返回） |
| 适合 DAG | ✅ 非常适合 | ❌ 过重 |
| 迁移成本 | 中等 | 高（需要重写全部） |
| 风险 | 低（隔离） | 高（影响核心路径） |

#### D.2 LangGraph REPORT Graph 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     ReportGraph (LangGraph)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────┐     ┌──────────────┐     ┌─────────────────┐     │
│   │  START  │────▶│ ClarifyNode  │────▶│ AgentSelectNode │     │
│   └─────────┘     └──────────────┘     └────────┬────────┘     │
│                          │                      │               │
│                          │ (need_clarify)       │               │
│                          ▼                      ▼               │
│                   ┌────────────┐      ┌─────────────────┐      │
│                   │  INTERRUPT │      │ParallelAgentNode│      │
│                   │ (等待用户) │      │  (Send API)     │      │
│                   └────────────┘      └────────┬────────┘      │
│                                                │               │
│                                                ▼               │
│                                       ┌─────────────┐          │
│                                       │  ForumNode  │          │
│                                       │ (综合分析)  │          │
│                                       └──────┬──────┘          │
│                                              │                 │
│                                              ▼                 │
│                                       ┌─────────────┐          │
│                                       │ OutputNode  │          │
│                                       │ (ReportIR)  │          │
│                                       └──────┬──────┘          │
│                                              │                 │
│                                              ▼                 │
│                                          ┌───────┐             │
│                                          │  END  │             │
│                                          └───────┘             │
└─────────────────────────────────────────────────────────────────┘
```

#### D.3 Graph State 定义

```python
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import MessagesState

class ReportGraphState(TypedDict):
    """Report Graph 的状态结构"""
    # 输入
    query: str
    tickers: List[str]
    context: Dict[str, Any]

    # 路由信息
    intent: str  # "REPORT"
    selected_agents: List[str]

    # 追问状态
    need_clarify: bool
    clarify_question: Optional[str]
    missing_slots: List[str]

    # Agent 执行结果
    agent_results: Dict[str, Any]

    # Forum 综合
    forum_output: Optional[Dict[str, Any]]

    # 最终输出
    report: Optional[Dict[str, Any]]

    # 追踪
    trace: List[Dict[str, Any]]
```

#### D.4 核心节点实现

##### ClarifyNode（追问节点）

```python
from langgraph.types import interrupt

def clarify_node(state: ReportGraphState) -> ReportGraphState:
    """检查是否需要追问"""
    tickers = state.get("tickers", [])
    query = state["query"]

    # 检查必要信息
    if not tickers and _needs_ticker(query):
        return {
            **state,
            "need_clarify": True,
            "clarify_question": "请提供股票代码或公司名称，例如 AAPL 或 特斯拉",
            "missing_slots": ["ticker"]
        }

    return {**state, "need_clarify": False}

def should_interrupt(state: ReportGraphState) -> str:
    """条件边：是否中断等待用户"""
    if state.get("need_clarify"):
        return "interrupt"
    return "continue"
```

##### ParallelAgentNode（并行 Agent 执行）

```python
from langgraph.constants import Send

def agent_select_node(state: ReportGraphState) -> List[Send]:
    """选择并并行分发到多个 Agent"""
    query = state["query"]
    tickers = state["tickers"]

    # LLM 选择或规则选择
    agents = _select_agents_for_report(query)

    # 使用 Send 并行分发
    return [
        Send("agent_worker", {"agent_name": name, "query": query, "tickers": tickers})
        for name in agents
    ]

def agent_worker(state: Dict) -> Dict:
    """单个 Agent 执行"""
    agent_name = state["agent_name"]
    query = state["query"]
    tickers = state["tickers"]

    agent = get_agent(agent_name)
    result = agent.execute(query, tickers)

    return {"agent_name": agent_name, "result": result}
```

##### ForumNode（综合节点）

```python
def forum_node(state: ReportGraphState) -> ReportGraphState:
    """Forum 综合所有 Agent 结果"""
    agent_results = state["agent_results"]
    query = state["query"]

    # 调用现有 ForumHost
    forum = ForumHost(llm)
    synthesis = forum.synthesize(query, agent_results)

    return {**state, "forum_output": synthesis}
```

#### D.5 Graph 构建

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

def build_report_graph():
    """构建 Report Graph"""
    graph = StateGraph(ReportGraphState)

    # 添加节点
    graph.add_node("clarify", clarify_node)
    graph.add_node("agent_select", agent_select_node)
    graph.add_node("agent_worker", agent_worker)
    graph.add_node("forum", forum_node)
    graph.add_node("output", output_node)

    # 添加边
    graph.add_edge(START, "clarify")
    graph.add_conditional_edges(
        "clarify",
        should_interrupt,
        {
            "interrupt": END,  # 中断等待用户输入
            "continue": "agent_select"
        }
    )
    graph.add_edge("agent_worker", "forum")
    graph.add_edge("forum", "output")
    graph.add_edge("output", END)

    # 编译
    memory = MemorySaver()
    return graph.compile(checkpointer=memory, interrupt_before=["clarify"])
```

#### D.6 流式输出适配

```python
async def stream_report_graph(query: str, tickers: List[str]):
    """流式执行 Report Graph"""
    graph = build_report_graph()
    config = {"configurable": {"thread_id": str(uuid4())}}

    initial_state = {
        "query": query,
        "tickers": tickers,
        "context": {},
        "agent_results": {},
        "trace": []
    }

    async for event in graph.astream_events(initial_state, config):
        kind = event["event"]

        if kind == "on_chain_stream":
            # 流式输出中间结果
            yield {"type": "progress", "data": event["data"]}

        elif kind == "on_chain_end":
            # 最终结果
            yield {"type": "done", "data": event["data"]["output"]}
```

#### D.7 迁移步骤

| 步骤 | 内容 | 预估时间 |
|------|------|:---:|
| D.7.1 | 定义 `ReportGraphState` | 1h |
| D.7.2 | 实现 ClarifyNode（复用 SchemaRouter 逻辑） | 2h |
| D.7.3 | 实现 AgentSelectNode + 并行 Send | 2h |
| D.7.4 | 实现 ForumNode（封装现有 ForumHost） | 1h |
| D.7.5 | 实现 OutputNode（生成 ReportIR） | 1h |
| D.7.6 | 构建 Graph + 添加 Checkpointing | 2h |
| D.7.7 | 流式输出适配（SSE） | 2h |
| D.7.8 | 测试 + 回归验证 | 2h |
| **总计** | | **~13h** |

#### D.8 迁移后架构对比

```
迁移前:
/chat/supervisor/stream
  → ConversationRouter
    → SupervisorAgent (手搓)
      → asyncio.gather (手搓并行)
        → ForumHost (手搓综合)

迁移后:
/chat/supervisor/stream
  → ConversationRouter
    → Intent == REPORT?
      → YES: ReportGraph (LangGraph)
             - ClarifyNode (interrupt)
             - ParallelAgentNode (Send)
             - ForumNode
             - OutputNode
      → NO:  SupervisorAgent (保持手搓，fast-path)
```

#### D.9 LangGraph 优势

| 优势 | 说明 |
|------|------|
| **可视化** | `graph.get_graph().draw_png()` 自动生成流程图 |
| **状态持久化** | Checkpointing 支持对话恢复 |
| **中断/恢复** | `interrupt` 原生支持追问流程 |
| **并行原语** | `Send` API 优雅处理并行 Agent |
| **流式输出** | `astream_events` 原生支持 SSE |
| **可测试性** | 每个节点可独立单测 |

---

## 七、LangGraph / LangChain 当前使用情况

### 7.1 LangGraph 使用

| 功能 | 位置 | 说明 |
|------|------|------|
| `StateGraph` + `MessagesState` | `langchain_agent.py:38` | 构建 ReAct 工具调用图 |
| `ToolNode` + `tools_condition` | `langchain_agent.py:39` | 预置的工具节点和条件路由 |
| `MemorySaver` | `langchain_agent.py:37` | 内存检查点 |

**结论**: LangGraph 只用于构建旧的 ReAct Agent，未充分利用其 Supervisor / interrupt 等能力。

### 7.2 LangChain 使用

| 功能 | 使用方式 | 频率 |
|------|---------|------|
| `ChatOpenAI` | LLM 初始化 | `llm_config.py` |
| `HumanMessage` | 构造消息调用 LLM | 遍布全项目 (20+ 处) |
| `@tool` 装饰器 | 定义工具 | `langchain_tools.py` |

**结论**: LangChain 几乎只用了 `ChatOpenAI` 和 `HumanMessage`，大量功能手搓实现。

### 7.3 手搓 vs 框架对比

| 功能 | 框架有的 | 项目做法 |
|------|---------|---------|
| Agent 编排 | LangGraph `StateGraph` | 手写 `SupervisorAgent` (1100+ 行) |
| Intent 分类 | LangGraph `conditional_edges` | 手写 `IntentClassifier` + `Router` |
| 工具路由 | LangGraph `ToolNode` | 手写 `SchemaToolRouter` (724 行) |
| 多 Agent 并行 | LangGraph `Send` API | 手写 `asyncio.gather` |
| 追问/Clarify | LangGraph `interrupt` | 手写 `CLARIFY_TEMPLATES` |
| 记忆管理 | LangGraph `MemorySaver` | 手写 JSON 文件存储 |

---

## 八、附录

### 附录 A: 关键文件位置

| 文件 | 行数 | 职责 |
|------|------|------|
| `backend/api/main.py` | ~1548 | API 端点、入口 |
| `backend/conversation/router.py` | ~557 | 对话路由 |
| `backend/conversation/schema_router.py` | ~724 | Schema 路由、追问 |
| `backend/conversation/agent.py` | ~1000+ | 对话 Agent |
| `backend/orchestration/supervisor_agent.py` | ~1100 | Supervisor 编排 |
| `backend/orchestration/forum.py` | ~200+ | Forum 综合 |

### 附录 B: 相关文档

| 文档 | 说明 |
|------|------|
| `docs/01_ARCHITECTURE.md` | 架构文档（需更新） |
| `docs/Thinking/unified_supervisor_proposal.py` | Unified Supervisor 提案代码 |
| 本文档 | 架构重构参考手册 |

### 附录 C: 验收标准

| Phase | 验收条件 |
|-------|---------|
| Phase 1 | 请求全部进入 `/chat/supervisor`，旧端点不可访问 |
| Phase 2 | SchemaRouter 代码减量，但输出结构不变 |
| Phase 3 | Trace 中 SchemaRouter 只触发一次 |
| Phase 4 | CHAT/REPORT 统一走 Supervisor，简单查询走 fast-path |
| Phase 5 | pytest 全通过，Clarify 流程正常 |

---

## 九、变更日志

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-01-31 | v1.0 | 初始版本，包含完整架构分析和落地清单 |

---

> **文档维护者**: AI Assistant
> **最后更新**: 2026-01-31
