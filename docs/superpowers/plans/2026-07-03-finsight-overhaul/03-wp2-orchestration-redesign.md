# WP2 LangGraph 编排层重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把意图层收敛为单一事实源 `IntentFrame`，把执行层从"连续块排队"升级为显式 DAG，让 agent 拿到完整任务简报（`AgentBrief`）并能读到先行 agent 的产出摘要（证据黑板），多问题 query 的回答按任务分节。

**Architecture:** 六步走：先立"金样快照"防护网 → 定义 IntentFrame/AgentBrief 数据模型 → 意图管线改造（LLM router 为唯一决策者、关键词瀑布降级为 fallback）→ PlanIR 加 `depends_on` + DAG 执行器 → AgentBrief 注入与黑板 → 图拓扑诚实化 + 按任务分节渲染。全程 env 开关可回退。

**Tech Stack:** LangGraph 1.0.7、Pydantic v2、asyncio。

## Global Constraints

- 每一步都有 env kill-switch，默认值保持旧行为，灰度开启：`FINSIGHT_INTENT_FRAME`、`FINSIGHT_DAG_EXECUTOR`、`FINSIGHT_AGENT_BRIEF`、`FINSIGHT_EVIDENCE_BUS`（取值 `off|shadow|on`，默认 `off`）。
- 不新增依赖。
- 所有新模块放 `backend/graph/intent/` 与 `backend/graph/planning/` 两个新包；旧文件在 WP2 内**只加不删**（删除与搬家属于 WP3）。
- SSE 事件契约（`docs/execution-event-contract.md`）不变：前端不感知本 WP。

---

## 附：现状诊断（为什么"怪"——执行者必读）

以下每条都在基线代码里核实过，是本计划每个任务的动机：

1. **五套意图表示并存（ORC-01）**：`understand_request` 同时产出 `understanding`、`understanding.v2`（`FINSIGHT_UNDERSTANDING_V2_MODE` 默认 shadow）、`intent_contract`(+复数形式，`intent_contract_mode()` 三态)、`request_frame`(+复数)、`reply_contract`（先 build 一次、应用到 tasks、再 build 第二次，见 `understand_request.py:3268-3284`）。下游各取所需：planner 看 tasks+contract，synthesize 看 reply_contract+contract，renderer 看 understanding。没有一个结构是权威的。
2. **LLM 说了不算（ORC-02）**：`route_conversation`（LLM）给出 `ConversationDecision` 后，主函数里有 `_direct_decision_must_project_tasks` 可以推翻 direct → research（:2545），关键词瀑布可以在 router 绑定任务后继续加塞（:2634-3000 的十几个 `if not blocked_tasks and …` 块），还有 4 条不经 LLM 的提前 return（社交、brief、URL、backtest frame）。阅读者无法回答"这个 query 会走哪条路"。
3. **agent 是聋子（ORC-03）**：`agent_adapter.py:392` `_agent.research(query=query, ticker=ticker)`——plan 里精心构造的 `required_evidence`、`time_scope`、对话上下文、前组 agent 的发现，全都没传进去。每个 agent 只能对着原始 query 文本自己再猜一遍意图、自己再调一遍工具。
4. **并行组不是依赖（ORC-04/05）**：`executor.py` 把 steps 按 `parallel_group` **连续块**切成串行组、组内 gather。组 1→组 2 只是时间先后，组 2 的 agent 看不到组 1 的任何产出（唯一例外：`run_python_compute` 的 `step:` 数据集注入）。README 宣传的"组 1 price·news → 组 2 fundamental·technical"给人依赖流水线的印象，实际是纯排队。
5. **"辩论"是摆设（ORC-06）**：`research_debate` 默认关，开了也是确定性规则把 evidence_ledger 拼成正反清单，无 agent 交互。
6. **图拓扑说谎（ORC-07）**：`resolve_subject/clarify/parse_operation` 注册在图里但主路径不经过；`understand_request` 内部直接函数调用 `decide_output_mode/parse_operation/route_conversation`。看图 ≠ 懂执行。
7. **双 planner 边界靠猜（ORC-08）**：`_should_use_task_graph_planner` 用操作名集合+reason 字符串判断走规则 planner 还是 LLM planner，集合与 understand 的产出耦合，加一种 operation 要同时改三处。

**设计决策（Decisions）**

- **D1 单一意图源**：`IntentFrame` 是 understand 阶段唯一输出；`intent_contract` 的 `required_evidence` 变成 `IntentTask` 字段；`request_frame`/`understanding_v2` 冻结废除；`reply_contract` 变成 IntentFrame 内嵌、只 build 一次。
- **D2 LLM 主导 + 规则兜底**：`route_conversation` 是唯一路由决策者。关键词逻辑只保留两个位置：(a) `signals.py` 提取客观信号（ticker/URL/数字），(b) `fallback_rules.py` 在 LLM 不可用或返回 research-无任务时构造任务。规则不得推翻 LLM 的 direct/clarify 决策；"必须落地为任务"的强制（原 `_direct_decision_must_project_tasks`）改为 **router prompt 内约束 + 一次显式复核函数**，且复核只能"降级为 clarify"不能"伪造 research"。
- **D3 DAG 执行**：`PlanStep` 增加 `depends_on: list[str]`；执行器改为就绪即跑；`parallel_group` 保留为纯展示 lane 标签。
- **D4 AgentBrief**：agent 签名 `research(query, ticker, on_event=None, brief: AgentBrief | None = None)`；brief 携带 objective/required_evidence/time_scope/output_mode/context_digest。
- **D5 证据黑板**：executor 维护 `context_bus`，agent step 完成后写入摘要；后续 agent step 启动前把 digest 注入其 inputs。星型黑板，不做点对点消息（YAGNI）。
- **D6 图诚实化**：从图中删除三个 legacy 节点注册；`route_conversation`/`parse_operation`/`decide_output_mode` 移出 `nodes/` 语义（WP2 先改调用关系与注册，物理搬家在 WP3）。
- **D7 优先级/置信度具名化**：magic number 收进 `intent/priorities.py` 常量表。
- **D8 多任务分节**：`len(tasks)>=2` 且 subject 不同 → chat 渲染按 task 分节，来源是 executor 已有的 `artifacts.task_results`。

---

### Task 0: 金样快照防护网（先于一切）

**Files:**
- Create: `tests/golden/__init__.py`、`tests/golden/conftest.py`、`tests/golden/test_golden_pipeline.py`、`tests/golden/snapshots/`（目录）

**Interfaces:**
- Produces: `run_pipeline_deterministic(query, ui_context) -> dict`（LLM 全关、工具 dry-run 下跑完整图并抽取稳定切片）。后续所有 WP2/WP3 任务以此为回归防线。

- [x] **Step 1: 写快照 harness**

```python
# tests/golden/conftest.py
# -*- coding: utf-8 -*-
"""金样快照：LLM 关闭 + dry_run 下，管线对固定 query 的结构化输出必须逐字节稳定。"""
import asyncio
import json
import os
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

DETERMINISTIC_ENV = {
    "LANGGRAPH_EXECUTE_LIVE_TOOLS": "false",   # executor dry-run
    "AGENT_LLM_ANALYZE_ENABLED": "false",
    "LANGGRAPH_PLANNER_AB_ENABLED": "false",
    "FINSIGHT_UNDERSTANDING_V2_MODE": "off",
    "DEBATE_GRAPH_ENABLED": "false",
    # LLM router 不可用 → 走确定性 fallback 路径（这正是我们要冻结的规则行为）
    "OPENAI_COMPATIBLE_API_KEY": "",
    "OPENAI_COMPATIBLE_API_BASE": "",
}


@pytest.fixture()
def deterministic_env(monkeypatch):
    for key, value in DETERMINISTIC_ENV.items():
        monkeypatch.setenv(key, value)
    yield


def _stable_slice(final_state: dict) -> dict:
    """抽取与时间/随机无关的结构切片。"""
    understanding = final_state.get("understanding") or {}
    plan_ir = final_state.get("plan_ir") or {}
    return {
        "route": understanding.get("route"),
        "tasks": [
            {
                "subject_type": t.get("subject_type"),
                "tickers": t.get("tickers"),
                "operation": (t.get("operation") or {}).get("name"),
                "reason": t.get("reason"),
            }
            for t in (understanding.get("tasks") or [])
        ],
        "blocked_reasons": [b.get("reason") for b in (understanding.get("blocked_tasks") or [])],
        "plan_steps": [
            {"kind": s.get("kind"), "name": s.get("name"), "group": s.get("parallel_group")}
            for s in (plan_ir.get("steps") or [])
        ],
        "output_mode": final_state.get("output_mode"),
    }


def run_pipeline_deterministic(query: str, ui_context: dict | None = None) -> dict:
    from backend.graph.runner import GraphRunner

    async def _run() -> dict:
        runner = GraphRunner.create()
        final_state = await runner.ainvoke(
            thread_id=f"golden-{abs(hash(query)) % 10_000}",
            query=query,
            ui_context=ui_context or {},
        )
        return _stable_slice(final_state)

    return asyncio.run(_run())


def assert_matches_snapshot(name: str, payload: dict) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{name}.json"
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if os.getenv("GOLDEN_UPDATE") == "1" or not path.exists():
        path.write_text(rendered, encoding="utf-8")
        return
    assert path.read_text(encoding="utf-8") == rendered, (
        f"golden snapshot drift: {name}. 若 diff 是本任务预期行为变更，"
        f"用 GOLDEN_UPDATE=1 重录并在 commit message 里解释每一处 diff。"
    )
```

```python
# tests/golden/test_golden_pipeline.py
# -*- coding: utf-8 -*-
import pytest

from .conftest import assert_matches_snapshot, run_pipeline_deterministic

GOLDEN_QUERIES = {
    "single_price": "AAPL 现在多少钱",
    "single_report": "给我一份 NVDA 的投资分析",
    "compare": "对比 AAPL 和 MSFT 的估值",
    "multi_question": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候",
    "macro_only": "美国 CPI 最近走势怎么样",
    "news_impact": "TSLA 最近的新闻对股价有什么影响",
    "greeting": "你好",
    "vague_no_subject": "帮我分析一下",
    "url_doc": "总结一下 https://example.com/a-16k-filing 的要点",
    "alert": "AAPL 涨到 250 提醒我",
    "portfolio_no_context": "我的持仓该怎么调仓",
    "cn_ticker": "600036 走势如何",
}


@pytest.mark.parametrize("name", sorted(GOLDEN_QUERIES))
def test_golden(name, deterministic_env):
    payload = run_pipeline_deterministic(GOLDEN_QUERIES[name])
    assert_matches_snapshot(name, payload)
```

- [x] **Step 2: 首录快照并人工审读**

Run: `GOLDEN_UPDATE=1 python -m pytest tests/golden -x -q` 然后 `python -m pytest tests/golden -x -q`
Expected: 第二次全绿。**打开每个 snapshot JSON 人工检查**：route/tasks/steps 是否符合直觉，把明显荒谬处记录到 `tests/golden/KNOWN_QUIRKS.md`（只记录，不修——它们是现状基线）。

- [x] **Step 3: Commit**

```bash
git add tests/golden
git commit -m "test(golden): deterministic pipeline snapshots as refactor safety net (12 canonical queries)"
```

---

### Task 1: IntentFrame / AgentBrief 数据模型

**Files:**
- Create: `backend/graph/intent/__init__.py`、`backend/graph/intent/frame.py`
- Test: `backend/tests/test_intent_frame.py`

**Interfaces:**
- Produces（后续任务全部依赖，签名逐字使用）:

```python
class IntentTask(BaseModel):
    id: str
    subject_type: str                    # company|macro|theme|portfolio|news_item|news_set|research_doc|filing|index|crypto|fund|unknown
    subject_label: str = ""
    tickers: list[str] = Field(default_factory=list)
    operation: str                       # 扁平字符串，不再是 {"name":..} 嵌套
    operation_confidence: float = 0.75
    params: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list)   # ← 吸收自 intent_contract
    priority: int = 50
    reason: str = ""

class BlockedIntent(BaseModel):
    id: str
    reason: str
    question: str
    suggestions: list[str] = Field(default_factory=list)
    fallback_allowed: bool = False

class IntentFrame(BaseModel):
    schema_version: str = "intent_frame/v1"
    route: str                           # research|direct|clarify|alert
    query: str
    output_mode: str = "chat"
    language: str = "zh"
    tasks: list[IntentTask] = Field(default_factory=list)
    blocked: list[BlockedIntent] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    fallback_assumptions: list[str] = Field(default_factory=list)
    reply_plan: dict[str, Any] = Field(default_factory=dict)     # ← 原 reply_contract 收编
    confidence: float = 0.5
    source: str = "rules_fallback"       # llm_router|rules_fallback|mixed

@dataclass
class AgentBrief:
    query: str
    ticker: str
    objective: str = ""                  # 来自 IntentTask.operation
    required_evidence: list[str] = field(default_factory=list)
    time_scope: dict[str, Any] = field(default_factory=dict)
    output_mode: str = "chat"
    context_digest: str = ""             # 证据黑板摘要，≤1200 字符

def intent_frame_from_legacy(understanding: dict, *, reply_contract: dict | None = None,
                             intent_contract: dict | None = None) -> IntentFrame: ...
def legacy_understanding_from_frame(frame: IntentFrame) -> dict: ...
```

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_intent_frame.py
from backend.graph.intent.frame import IntentFrame, IntentTask, intent_frame_from_legacy, legacy_understanding_from_frame


def test_roundtrip_legacy_understanding():
    legacy = {
        "route": "research",
        "original_query": "对比 AAPL 和 MSFT",
        "language": "zh",
        "tasks": [{
            "id": "t1", "subject_type": "company", "subject_label": "AAPL, MSFT",
            "tickers": ["AAPL", "MSFT"],
            "operation": {"name": "compare", "confidence": 0.86, "params": {}},
            "priority": 20, "reason": "multi_ticker_compare",
        }],
        "blocked_tasks": [], "context_refs": [], "fallback_assumptions": [],
    }
    frame = intent_frame_from_legacy(legacy)
    assert frame.route == "research"
    assert frame.tasks[0].operation == "compare"
    assert frame.tasks[0].operation_confidence == 0.86

    back = legacy_understanding_from_frame(frame)
    assert back["route"] == "research"
    assert back["tasks"][0]["operation"]["name"] == "compare"
    assert back["tasks"][0]["tickers"] == ["AAPL", "MSFT"]


def test_required_evidence_absorbed_from_contract():
    legacy = {"route": "research", "original_query": "q", "tasks": [
        {"id": "t1", "subject_type": "company", "tickers": ["AAPL"],
         "operation": {"name": "investment_opinion", "confidence": 0.8}, "priority": 25, "reason": "x"},
    ], "blocked_tasks": []}
    contract = {"required_evidence": ["price_snapshot", "recent_news"], "primary_tickers": ["AAPL"]}
    frame = intent_frame_from_legacy(legacy, intent_contract=contract)
    assert frame.tasks[0].required_evidence == ["price_snapshot", "recent_news"]
```

- [ ] **Step 2: 确认失败**：`python -m pytest backend/tests/test_intent_frame.py -x -q` → ImportError。

- [ ] **Step 3: 实现 `frame.py`**（按上面签名完整实现；`intent_frame_from_legacy` 的映射规则：`understanding.route` 的 `"clarify"` 保持、`"alert"` 保持、`"research"` 保持，legacy 无 route 时按 tasks 非空 → research 否则 clarify；task.operation dict → 扁平字段；`intent_contract.required_evidence` 应用到 `primary_tickers` 命中的所有 task；`legacy_understanding_from_frame` 逆向重建，包含 `user_visible_summary` 的重新拼接——逻辑照抄 `understand_request.py:3315-3323` 的 summary_bits 规则）。

- [ ] **Step 4: 测试通过 + Commit**

```bash
git add backend/graph/intent backend/tests/test_intent_frame.py
git commit -m "feat(intent): IntentFrame/AgentBrief models with lossless legacy adapters"
```

---

### Task 2: 关键词与信号统一（ORC-12 / D2a）

**Files:**
- Create: `backend/graph/intent/keywords.py`、`backend/graph/intent/signals.py`
- Modify: `backend/graph/nodes/understand_request.py`、`backend/graph/nodes/conversation_router.py`（改 import，不改逻辑）
- Test: `backend/tests/test_intent_signals.py`

**Interfaces:**
- Produces:

```python
# keywords.py —— 全部意图关键词元组的唯一家。逐字搬运，禁止增删改任何词条。
_PRICE_HINTS: tuple[str, ...]; _NEWS_HINTS; _IMPACT_HINTS; _TECHNICAL_HINTS; _MACRO_HINTS
_THEME_HINTS; _PORTFOLIO_HINTS; _FALLBACK_HINTS; _VAGUE_SUBJECT_HINTS; _ASSET_DEICTIC_HINTS  # …以及两文件中其余全部 *_HINTS
def contains_any(text: str, hints: tuple[str, ...]) -> bool

# signals.py —— 客观信号提取（无路由决策）
@dataclass
class QuerySignals:
    tickers: list[str]
    urls: list[str]
    has_macro: bool
    has_portfolio: bool
    has_theme: bool
    wants_brief: bool
    is_casual: bool
def extract_signals(query: str, *, ui_context: dict) -> QuerySignals
```

- [ ] **Step 1: 盘点两份关键词**

Run: `grep -n "_HINTS\s*=\|_HINTS:" backend/graph/nodes/understand_request.py backend/graph/nodes/conversation_router.py`
把所有元组名列成清单。对同名但内容漂移的元组（例如技术面/估值 hints），**取并集**并在 `keywords.py` 中用注释标注来源差异。

- [ ] **Step 2: 写测试**（漂移回归：两个消费方看到同一份词表）

```python
# backend/tests/test_intent_signals.py
from backend.graph.intent import keywords
from backend.graph.intent.signals import extract_signals


def test_hints_have_single_source():
    import backend.graph.nodes.understand_request as ur
    import backend.graph.nodes.conversation_router as cr
    assert ur._TECHNICAL_HINTS is keywords._TECHNICAL_HINTS
    assert cr_technical_hints_alias(cr) is keywords._TECHNICAL_HINTS  # 按 cr 中实际符号名断言 identity


def test_extract_signals_basic():
    s = extract_signals("对比 AAPL 和 MSFT 的估值，顺便看下美联储", ui_context={})
    assert set(s.tickers) == {"AAPL", "MSFT"}
    assert s.has_macro is True
    assert s.is_casual is False
```

- [ ] **Step 3: 实现**：新建两个模块；`understand_request.py` / `conversation_router.py` 顶部改为 `from backend.graph.intent.keywords import *_HINTS…`（旧模块内保留 `_TECHNICAL_HINTS = keywords._TECHNICAL_HINTS` 别名以兼容既有引用）。`extract_signals` 的实现= 逐字搬运 `understand_request` 中 `extract_tickers/_extract_urls/_contains_any(_MACRO_HINTS)/is_casual_chat/_is_explicit_brief_request` 的现有调用组合。

- [ ] **Step 4: 验证**：`python -m pytest backend/tests/test_intent_signals.py tests/golden -x -q` → 全绿（金样零 diff 证明纯机械）。

- [ ] **Step 5: Commit**

```bash
git commit -am "refactor(intent): single-source keyword tables + QuerySignals extractor (zero behavior change)"
```

---

### Task 3: 意图管线重排——LLM 唯一决策者 + fallback 降级（ORC-02 / D2）

**Files:**
- Create: `backend/graph/intent/pipeline.py`、`backend/graph/intent/fallback_rules.py`、`backend/graph/intent/priorities.py`
- Modify: `backend/graph/nodes/understand_request.py`（主函数改为薄壳分发）
- Test: `backend/tests/test_intent_pipeline.py`

**Interfaces:**
- Produces:

```python
# priorities.py
PRIORITY_WORKFLOW_ACTION = 8      # 原 :2446 的 8
PRIORITY_UI_SELECTION = 10        # 原 :2718
PRIORITY_PRIMARY_COMPARE = 20     # 原 :2793/2811
PRIORITY_PER_TICKER_EVIDENCE = 24
PRIORITY_PRIMARY_TASK = 25
PRIORITY_COMPARE_SUBTASK = 26
PRIORITY_MACRO = 30
PRIORITY_THEME = 35
PRIORITY_PORTFOLIO = 40
PRIORITY_WEAK_FALLBACK = 80
CONFIDENCE_WITH_TASKS = 0.78      # 原 :3332
CONFIDENCE_NO_TASKS = 0.42

# pipeline.py
async def build_intent_frame(state: GraphState) -> IntentFrame:
    """唯一入口。顺序固定：
    1. signals = extract_signals(query, ui_context)
    2. 硬前置（不经 LLM 是合理的三类）：空 query→clarify；纯社交→direct；workflow_action(backtest frame)→research
    3. decision = await route_conversation(...)   # LLM router；异常/超时 → decision=None
    4. if decision 为 direct/clarify/out_of_scope → 复核 review_direct_decision()（只能降级为 clarify，不得改成 research）→ 产出 frame 返回
    5. if decision 为 research → tasks = build_tasks_from_decision(decision, signals)（router task_hints 投影，含 required_evidence）
    6. if decision is None（LLM 不可用）→ tasks = fallback_rules.build_tasks(signals, state)（原关键词瀑布，整体搬运）
    7. if decision 为 research 且步骤5产出 tasks 为空 → 同样落入 fallback_rules（source="mixed"）
    8. augment_support_tasks(tasks, signals)      # 原"support task 加塞"逻辑收敛成一个纯函数：只补充，不新建主任务
    9. assemble：route 判定（原 :3227-3246 规则逐字搬）、reply_plan（build_reply_contract 只调一次）、confidence 用常量
    """

def review_direct_decision(query: str, decision: ConversationDecision, signals: QuerySignals) -> Literal["keep", "clarify"]:
    """原 _direct_decision_must_project_tasks 的替代：发现 direct 决策明显缺证据时，降级 clarify 请用户确认，
    不再伪造 research。判定条件逐字搬运原函数，但输出语义收窄。"""
```

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_intent_pipeline.py
import pytest
from unittest.mock import AsyncMock, patch

from backend.graph.intent.pipeline import build_intent_frame


@pytest.mark.asyncio
async def test_llm_research_decision_is_authoritative():
    """LLM 判 research + task_hints → 任务来自 hints，关键词瀑布不得另起炉灶。"""
    decision = make_decision(route="research", task_hints=[{"operation": "price", "tickers": ["AAPL"]}])
    with patch("backend.graph.intent.pipeline.route_conversation", new=AsyncMock(return_value=decision)):
        frame = await build_intent_frame({"query": "AAPL 现在多少钱", "ui_context": {}})
    assert frame.source == "llm_router"
    assert [t.operation for t in frame.tasks] == ["price"]


@pytest.mark.asyncio
async def test_llm_direct_decision_cannot_be_overridden_to_research():
    decision = make_decision(route="direct_answer")
    with patch("backend.graph.intent.pipeline.route_conversation", new=AsyncMock(return_value=decision)):
        frame = await build_intent_frame({"query": "PE 是什么意思", "ui_context": {}})
    assert frame.route in {"direct", "clarify"}   # 绝不允许 research


@pytest.mark.asyncio
async def test_router_unavailable_falls_back_to_rules():
    with patch("backend.graph.intent.pipeline.route_conversation", new=AsyncMock(side_effect=TimeoutError)):
        frame = await build_intent_frame({"query": "AAPL 现在多少钱", "ui_context": {}})
    assert frame.source == "rules_fallback"
    assert any(t.operation == "price" for t in frame.tasks)


@pytest.mark.asyncio
async def test_multi_question_produces_multi_tasks():
    with patch("backend.graph.intent.pipeline.route_conversation", new=AsyncMock(side_effect=TimeoutError)):
        frame = await build_intent_frame({"query": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候", "ui_context": {}})
    subject_types = {t.subject_type for t in frame.tasks}
    assert "company" in subject_types and "macro" in subject_types
```

（`make_decision` 为测试内 helper，按 `ConversationDecision` 真实字段构造。）

- [ ] **Step 2: 确认失败** → ImportError。

- [ ] **Step 3: 实现（大工程，按序）**

3a. `fallback_rules.build_tasks(signals, state) -> tuple[list[IntentTask], list[BlockedIntent], list[str]]`：把 `understand_request.py:2634-3000` 的关键词瀑布（active_symbol 兜底、holdings、selection、company 主块、macro、theme、portfolio）**整体剪切**进来，输出改为 IntentTask（用 Task1 的模型），行为逐字保持（对照金样）。
3b. `pipeline.build_intent_frame` 按上面 docstring 的 9 步组装；步骤 2 的三个硬前置从原函数 :2413-2536 搬运；`_apply_reply_contract_to_tasks` + 二次 build 的双重构建改为**单次**：先 build tasks 完成后 build 一次 reply_plan（原双 build 的第二次输入=第一次输出，函数是幂等投影，单次等价——若金样 diff 证明不等价，保留双调用并在代码注释说明）。
3c. `understand_request.py` 主函数改为：

```python
async def understand_request(state: GraphState) -> dict[str, Any]:
    mode = os.getenv("FINSIGHT_INTENT_FRAME", "off").strip().lower()
    if mode in {"shadow", "on"}:
        frame = await build_intent_frame(state)
        if mode == "on":
            result = state_updates_from_frame(frame, state)   # 见 3d
            await _emit_understanding_trace(result["understanding"])
            return result
        # shadow：记录到 trace，继续走旧路径对拍
        state.setdefault("trace", {})["intent_frame_shadow"] = frame.model_dump()
    return await _legacy_understand_request(state)   # ← 原主函数整体改名，不动一行
```

3d. `state_updates_from_frame(frame, state) -> dict`：产出与旧返回 dict 完全同构的键集（`understanding/tasks/blocked_tasks/subject/operation/facets/output_mode/clarify/chat_responded/artifacts/trace` …），其中 `understanding = legacy_understanding_from_frame(frame)`，`understanding["intent_frame"] = frame.model_dump()`。`subject/operation/facets` 的推导逐字搬运原 :3286-3308。

- [ ] **Step 4: 对拍验证**

Run: `python -m pytest backend/tests/test_intent_pipeline.py -x -q`（新逻辑单测）
Run: `python -m pytest tests/golden -x -q`（默认 off，零 diff）
Run: `FINSIGHT_INTENT_FRAME=on GOLDEN_UPDATE=1 python -m pytest tests/golden -x -q && git diff --stat tests/golden/snapshots`
Expected: on 模式重录快照后，diff 仅限 `KNOWN_QUIRKS.md` 中登记过的荒谬项被修正（例如 direct 被强改 research 的路径消失）。**每一处 diff 都要能对着 D2 解释；解释不了的 diff = bug，修完再来。**审读完把 on 模式快照存到 `tests/golden/snapshots_v2/` 目录（两套并存，直到 WP2 收尾切换）。

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(intent): single-decision pipeline behind FINSIGHT_INTENT_FRAME flag; keyword cascade demoted to fallback"
```

---

### Task 4: 冻结并下线 understanding_v2 / request_frame 双轨（ORC-01 收尾）

**Files:**
- Modify: `backend/graph/nodes/understand_request.py`、`backend/graph/nodes/synthesize.py`、`backend/graph/nodes/policy_gate.py`、`backend/graph/report_builder.py`
- Test: 既有测试套 + 金样

- [ ] **Step 1: 盘点消费方**

Run: `grep -rn "request_frame\|understanding_v2\|intent_contract" backend/graph backend/api --include="*.py" -l`
对每个文件记录：读的是哪个字段、用来做什么。产出 `docs/superpowers/plans/2026-07-03-finsight-overhaul/notes-contract-consumers.md`（一张表）。

- [ ] **Step 2: 逐消费方切换**：读 `request_frame.workflow_action` 的 → 改读 `IntentTask(operation="backtest")`；读 `intent_contract.required_evidence` 的（policy_gate `_required_evidence_from_state` :338、planner）→ 改读 `IntentTask.required_evidence`；`understanding_v2` 消费方（`grep` 结果预期只有 trace/诊断）→ 直接删。每切一个消费方跑一次金样（on 模式）。

- [ ] **Step 3: 默认值切换**：`FINSIGHT_UNDERSTANDING_V2_MODE` 默认改 `off`；`intent_contract_mode()`（`grep -n "def intent_contract_mode" backend/graph`）默认改 `off`，enforce 分支保留一个发布周期后由 WP3 删除。

- [ ] **Step 4: Commit**

```bash
git commit -am "refactor(intent): consumers read IntentFrame fields; freeze understanding_v2/request_frame dual tracks"
```

---

### Task 5: PlanIR depends_on + DAG 执行器（ORC-04 / D3）

**Files:**
- Modify: `backend/graph/plan_ir.py`（PlanStep 增字段）
- Create: `backend/graph/dag_executor.py`
- Modify: `backend/graph/executor.py`（入口按 flag 分发）
- Test: `backend/tests/test_dag_executor.py`

**Interfaces:**
- Produces:

```python
# plan_ir.py 的 PlanStep 增加：
depends_on: list[str] = Field(default_factory=list)   # 前置 step id；空=无依赖

# dag_executor.py
async def execute_plan_dag(plan_ir, *, tool_invokers, agent_invokers, dry_run,
                           cache=None, cancel_event=None,
                           context_bus: dict[str, Any] | None = None) -> tuple[dict, list]:
    """就绪即跑调度：所有 depends_on ⊆ done 的 step 并发启动；step 失败且非 optional →
    其传递闭包内的后继标记 skipped(reason='upstream_failed')，不相干分支继续。
    向后兼容：若所有 step 的 depends_on 为空，先调 group_steps_by_parallel_group 推导
    隐式依赖（第 N 组每个 step depends_on 第 N-1 组全部 step id），行为与旧执行器等价。
    返回值结构与旧 execute_plan 完全一致（artifacts/step_results/task_results/errors/signals + exec_events）。"""
```

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_dag_executor.py
import asyncio
import pytest

from backend.graph.dag_executor import execute_plan_dag


def make_step(id, name, depends_on=(), kind="tool", optional=False):
    return {"id": id, "kind": kind, "name": name, "inputs": {"step": id},
            "depends_on": list(depends_on), "optional": optional}


@pytest.mark.asyncio
async def test_ready_steps_run_concurrently_and_dependents_wait():
    order: list[str] = []
    async def slow(inputs):
        order.append(f"start:{inputs['step']}")
        await asyncio.sleep(0.05 if inputs["step"] == "a" else 0.01)
        order.append(f"end:{inputs['step']}")
        return {"ok": inputs["step"]}
    plan = {"steps": [make_step("a", "t"), make_step("b", "t"), make_step("c", "t", depends_on=["a", "b"])]}
    artifacts, _ = await execute_plan_dag(plan, tool_invokers={"t": slow}, agent_invokers={}, dry_run=False)
    assert order.index("start:b") < order.index("end:a")          # a、b 并发
    assert order.index("start:c") > order.index("end:a")          # c 等 a
    assert order.index("start:c") > order.index("end:b")          # c 等 b
    assert set(artifacts["step_results"]) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_required_failure_skips_downstream_but_not_siblings():
    async def tool(inputs):
        if inputs["step"] == "a":
            raise RuntimeError("boom")
        return {"ok": True}
    plan = {"steps": [make_step("a", "t"), make_step("b", "t"),
                      make_step("c", "t", depends_on=["a"]), make_step("d", "t", depends_on=["b"])]}
    artifacts, _ = await execute_plan_dag(plan, tool_invokers={"t": tool}, agent_invokers={}, dry_run=False)
    assert artifacts["step_results"]["c"]["status_reason"] == "upstream_failed"
    assert artifacts["step_results"]["d"]["status_reason"] == "done"
    assert any(e["step_id"] == "a" for e in artifacts["errors"])


@pytest.mark.asyncio
async def test_legacy_parallel_group_plans_get_implicit_dependencies():
    order: list[str] = []
    async def tool(inputs):
        order.append(inputs["step"]); return {}
    steps = [dict(make_step("a", "t"), parallel_group="g1"),
             dict(make_step("b", "t"), parallel_group="g1"),
             dict(make_step("c", "t"), parallel_group="g2")]
    for s in steps: s["depends_on"] = []
    await execute_plan_dag({"steps": steps}, tool_invokers={"t": tool}, agent_invokers={}, dry_run=False)
    assert order.index("c") > order.index("a") and order.index("c") > order.index("b")
```

- [ ] **Step 2: 确认失败** → ImportError。

- [ ] **Step 3: 实现 `dag_executor.py`**

调度核心（完整给出，事件发射/缓存/心跳直接复用旧 executor 的 `_run_step`——将旧 `execute_plan` 内的 `_run_step` 及其依赖 helper 提为模块级函数 `run_single_step(step, ctx)` 供两个执行器共用，`ctx` 打包 async_tools/async_agents/cache/artifacts/exec_events/cancel/emit）：

```python
async def _schedule(steps: list[dict], ctx: StepContext) -> None:
    by_id = {str(s["id"]): s for s in steps}
    deps: dict[str, set[str]] = {sid: set(map(str, s.get("depends_on") or [])) for sid, s in by_id.items()}
    if not any(deps.values()):
        deps = _implicit_deps_from_groups(steps)   # 旧 parallel_group 语义推导
    dependents: dict[str, set[str]] = defaultdict(set)
    for sid, ups in deps.items():
        for up in ups:
            dependents[up].add(sid)
    done: set[str] = set()
    failed: set[str] = set()
    running: dict[asyncio.Task, str] = {}

    def _ready() -> list[str]:
        return [sid for sid in by_id
                if sid not in done and sid not in failed
                and sid not in running.values() and deps[sid] <= done]

    def _mark_skipped_closure(root: str) -> None:
        stack = [root]
        while stack:
            cur = stack.pop()
            for nxt in dependents.get(cur, ()):  # 传递闭包
                if nxt in failed or nxt in done:
                    continue
                failed.add(nxt)
                ctx.record_skipped(by_id[nxt], reason="upstream_failed")
                stack.append(nxt)

    while len(done) + len(failed) < len(by_id):
        for sid in _ready():
            task = asyncio.create_task(run_single_step(by_id[sid], ctx))
            running[task] = sid
        if not running:
            break  # 环或全部失败——环检测：剩余节点计入 errors(reason="dependency_cycle")
        finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
        for task in finished:
            sid = running.pop(task)
            step = by_id[sid]
            exc = task.exception()
            if exc is None or bool(step.get("optional")):
                done.add(sid)
            else:
                failed.add(sid)
                _mark_skipped_closure(sid)
```

（`record_skipped` 写 `step_results[sid] = {"output": {"skipped": True, "reason": "upstream_failed"}, "status_reason": "upstream_failed", …}` 并发 `step_done(skipped=True)` 事件——事件字段与旧契约一致。）

- [ ] **Step 4: 接线**：`backend/graph/nodes/execute_plan_stub.py` 中调用点按 flag 分发：

```python
if os.getenv("FINSIGHT_DAG_EXECUTOR", "off").strip().lower() == "on":
    artifacts, exec_events = await execute_plan_dag(plan_ir, ..., context_bus=context_bus)
else:
    artifacts, exec_events = await execute_plan(plan_ir, ...)
```

- [ ] **Step 5: 验证**：新测试 + 金样（off 零 diff；on 模式下步骤集合不变、只有并发时序差异——金样切片不含时序所以应零 diff）。

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(executor): dependency-DAG scheduler behind FINSIGHT_DAG_EXECUTOR; legacy group plans get implicit deps"
```

---

### Task 6: AgentBrief 注入（ORC-03 / D4，含 BE-04 签名统一）

**Files:**
- Modify: `backend/agents/base_agent.py`（research 签名）、`backend/agents/{price,news,fundamental,technical,macro,risk,deep_search}_agent.py`（若各自覆写 research/初始化，统一收编到基类签名）、`backend/graph/adapters/agent_adapter.py`、`backend/graph/nodes/planner_stub.py`（steps 携带 brief 字段）
- Test: `backend/tests/test_agent_brief.py`

**Interfaces:**
- Produces: `BaseFinancialAgent.research(self, query: str, ticker: str, on_event=None, brief: AgentBrief | None = None) -> AgentOutput`；planner 的 agent step `inputs` 增加键：`objective/required_evidence/time_scope/output_mode`（planner_stub 的 `_append_agent_step` 一处改动即可覆盖全部 agent step——锚点 `planner_stub.py:227`）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_brief.py
import pytest
from backend.graph.intent.frame import AgentBrief


@pytest.mark.asyncio
async def test_brief_reaches_llm_analyze_prompt(monkeypatch):
    """brief.context_digest 与 objective 必须出现在 _llm_analyze 的 prompt <context> 中。"""
    from backend.agents.base_agent import BaseFinancialAgent
    captured = {}

    class FakeLLM:
        model_name = "fake"
        async def ainvoke(self, messages, **kw):
            captured["prompt"] = messages[0].content
            class R: content = "x" * 100
            return R()

    agent = BaseFinancialAgent(FakeLLM(), cache=None)
    monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", "true")
    agent._current_brief = AgentBrief(query="q", ticker="AAPL", objective="earnings_impact",
                                      context_digest="price_agent: AAPL $200, +3% on earnings beat")
    await agent._llm_analyze("data summary", role="analyst", focus="f")
    assert "earnings_impact" in captured["prompt"]
    assert "price_agent: AAPL $200" in captured["prompt"]


@pytest.mark.asyncio
async def test_adapter_builds_brief_from_step_inputs():
    from backend.graph.adapters.agent_adapter import brief_from_inputs
    inputs = {"query": "q", "ticker": "AAPL", "objective": "compare",
              "required_evidence": ["price_snapshot"], "__context_digest": "news_agent: ..."}
    brief = brief_from_inputs(inputs, default_query="q", default_ticker="AAPL", output_mode="chat")
    assert brief.objective == "compare"
    assert brief.context_digest.startswith("news_agent")
```

- [ ] **Step 2: 实现**

2a. `base_agent.py`：`research` 增加 `brief` 形参（默认 None，完全向后兼容），入口处 `self._current_brief = brief`；`_llm_analyze` 的 prompt `<context>` 块扩为：

```python
<context>
<query>{query}</query>
<ticker>{ticker}</ticker>
<objective>{(self._current_brief.objective if self._current_brief else "")}</objective>
<required_evidence>{", ".join(self._current_brief.required_evidence) if self._current_brief else ""}</required_evidence>
<peers_findings>
{(self._current_brief.context_digest if self._current_brief else "")[:1200]}
</peers_findings>
</context>
```

反思循环的"下一步工具决策" prompt（`grep -n "_decide_next\|reflection" base_agent.py` 找到构造处）同样注入 objective 与 peers_findings。
2b. BE-04：检查 4 个 agent 的自定义 `__init__(self, llm, cache, tools_module, circuit_breaker=None)`——基类改为同签名（`tools_module` 参数上提，基类 `self.tools = tools_module`），删除子类中与基类逐字相同的 `__init__/_format_output/_get_tool_registry`（仅删完全相同的；有差异的保留 override）。
2c. `agent_adapter.py`：新增 `brief_from_inputs(...)`（按测试签名），`_invoke` 内：

```python
brief = brief_from_inputs(inputs, default_query=default_query, default_ticker=default_ticker,
                          output_mode=str(state.get("output_mode") or "chat"))
use_brief = os.getenv("FINSIGHT_AGENT_BRIEF", "off").strip().lower() == "on"
result = await asyncio.wait_for(
    _agent.research(query=query or "N/A", ticker=ticker, brief=brief if use_brief else None),
    timeout=invoke_timeout,
)
```

2d. `planner_stub.py` `_append_agent_step`（:227）：inputs 组装处并入 `{"objective": operation_name, "required_evidence": task.get("required_evidence") or [], "time_scope": task.get("params", {}).get("time_scope") or {}}`。

- [ ] **Step 3: 验证**：新测试 + 全量 + 金样（brief flag off → 零 diff；on → plan_steps 切片含新 inputs 键？金样切片只取 kind/name/group，零 diff）。

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(agents): AgentBrief carries objective/required-evidence/peer-digest into agent research & prompts"
```

---

### Task 7: 证据黑板（ORC-05 / D5）

**Files:**
- Modify: `backend/graph/dag_executor.py`（agent step 完成后写 bus、启动前注入）
- Create: `backend/graph/context_bus.py`
- Test: `backend/tests/test_context_bus.py`

**Interfaces:**
- Produces:

```python
# context_bus.py
def digest_agent_output(agent_name: str, output: dict) -> str:
    """一条 ≤300 字符的单行摘要：'{agent}: {summary截断} | evidence: {前2条标题}'。
    output 非 dict 或无 summary → 返回 ''。"""

def render_bus(bus: dict[str, str], *, exclude: str, limit_chars: int = 1200) -> str:
    """按写入顺序拼接（排除自己），超限从最旧开始丢弃。"""
```

- 执行器契约：`run_single_step` 中 `kind == "agent"` 的 step：启动前 `inputs["__context_digest"] = render_bus(bus, exclude=name)`；成功后 `bus[name] = digest_agent_output(name, output)`。**注意**：注入发生在 cache key 计算**之后**（`__context_digest` 不参与 cache key，否则前序结果不同永远 miss）——实现方式：`step_cache_key` 调用处对 inputs 做 `{k: v for k, v in inputs.items() if not k.startswith("__")}` 过滤（旧执行器同样适用，`__escalation_stage/__force_run` 本就该排除——**该过滤对旧 executor 是行为变更，必须核对**：`grep -n "__escalation_stage\|__force_run\|__run_if" backend/graph` 确认这些键当前是否进 cache key；若是，旧执行器保持原样，只在 dag_executor 中过滤）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_context_bus.py
import pytest
from backend.graph.context_bus import digest_agent_output, render_bus
from backend.graph.dag_executor import execute_plan_dag


def test_digest_truncates_and_formats():
    d = digest_agent_output("price_agent", {"summary": "AAPL " + "x" * 500, "evidence": [{"title": "Q3 beat"}]})
    assert d.startswith("price_agent: AAPL")
    assert len(d) <= 300


@pytest.mark.asyncio
async def test_later_agent_sees_earlier_agent_digest():
    seen = {}
    async def price_agent(inputs):
        return {"summary": "AAPL at $200 after earnings beat", "evidence": []}
    async def risk_agent(inputs):
        seen["digest"] = inputs.get("__context_digest", "")
        return {"summary": "risk ok", "evidence": []}
    plan = {"steps": [
        {"id": "s1", "kind": "agent", "name": "price_agent", "inputs": {"query": "q", "ticker": "AAPL"}, "depends_on": []},
        {"id": "s2", "kind": "agent", "name": "risk_agent", "inputs": {"query": "q", "ticker": "AAPL"}, "depends_on": ["s1"]},
    ]}
    await execute_plan_dag(plan, tool_invokers={}, agent_invokers={"price_agent": price_agent, "risk_agent": risk_agent},
                           dry_run=False, context_bus={})
    assert "price_agent: AAPL at $200" in seen["digest"]
```

- [ ] **Step 2: 实现**（按契约；bus 默认 None=不启用，`FINSIGHT_EVIDENCE_BUS=on` 时 execute_plan_stub 传入 `{}`）。

- [ ] **Step 3: 验证 + Commit**

```bash
git commit -am "feat(executor): evidence digest bus — later agents read earlier agents' findings"
```

---

### Task 8: 图拓扑诚实化（ORC-07 / D6）

**Files:**
- Modify: `backend/graph/runner.py`
- Modify: `backend/tests/` 中引用被删节点的测试（`grep -rln "resolve_subject\|add_node(\"clarify\"\|parse_operation" backend/tests`）

- [ ] **Step 1:** `runner.py` 删除节点注册与边：`resolve_subject`、`clarify`、`parse_operation` 三个 `add_node` 行、`graph.add_edge("resolve_subject", "clarify")`、`_route_after_clarify`、`_route_after_parse_operation` 及对应 `add_conditional_edges`。（函数本体不删——`parse_operation` 仍被 understand 内部当纯函数调用，物理搬家在 WP3。）
- [ ] **Step 2:** 引用这些节点做单测的文件：改为直接 import 函数测试（不经图）。
- [ ] **Step 3:** 快照守护：`python -m pytest tests/golden backend/tests -x -q` 全绿。
- [ ] **Step 4: Commit**

```bash
git commit -am "refactor(graph): unregister legacy nodes not on the runtime path — topology now matches execution"
```

---

### Task 9: 双 planner 边界具名化（ORC-08）

**Files:**
- Modify: `backend/graph/nodes/planner.py`
- Create: `backend/graph/planning/__init__.py`、`backend/graph/planning/lane_selector.py`
- Test: `backend/tests/test_planner_lane.py`

**Interfaces:**
- Produces:

```python
# lane_selector.py
SIMPLE_TASK_GRAPH_OPS: frozenset[str]   # 从 planner.py:117-124 逐字搬运
ROUTER_EVIDENCE_OPS: frozenset[str]     # :162-166
PLANNABLE_SUBJECT_TYPES: frozenset[str] # :138-152（三处重复的集合合并为一处）
def select_planner_lane(state: GraphState, ready_tasks: list[dict]) -> Literal["rule", "llm"]:
    """语义与 _should_use_task_graph_planner 完全一致，True→'rule' False→'llm'。"""
```

- [ ] **Step 1:** 测试：用 3 组代表性 state（纯 price 任务→rule；deep_research→llm；混合 URL 证据图→rule）断言 lane。
- [ ] **Step 2:** 搬运实现；`planner.py` 原函数改为 `return select_planner_lane(state, ready_tasks) == "rule"` 的一行壳。
- [ ] **Step 3:** 金样零 diff + Commit

```bash
git commit -am "refactor(planner): named lane selector with single source op/subject sets"
```

---

### Task 10: 多问题分节渲染（ORC-11 / D8）

**Files:**
- Modify: `backend/graph/nodes/chat_renderer.py`（`render_chat_markdown` 入口，锚点 `grep -n "def render_chat_markdown" chat_renderer.py`，基线 2275）
- Test: `backend/tests/test_multi_task_sections.py`

**Interfaces:**
- Produces: `def render_task_sections(state: GraphState) -> str | None` —— 条件：`understanding.tasks` ≥2 个**不同 subject_label** 且 `artifacts.task_results` 非空；输出：按 task priority 升序，每个 task 渲染 `## {subject_label} · {OPERATION_LABELS[operation]}` 小节，小节内容 = 该 task 关联 steps 的现有渲染（复用 chat_renderer 现有的按-state 渲染函数，把过滤后的 task 级 state 切片传入）；不满足条件返回 None（走旧路径）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_multi_task_sections.py
from backend.graph.nodes.chat_renderer import render_task_sections


def test_two_subject_tasks_render_two_sections():
    state = {
        "understanding": {"tasks": [
            {"id": "t1", "subject_label": "AAPL, MSFT", "subject_type": "company",
             "operation": {"name": "compare"}, "priority": 20},
            {"id": "t2", "subject_label": "美联储议息", "subject_type": "macro",
             "operation": {"name": "macro_brief"}, "priority": 30},
        ]},
        "artifacts": {"task_results": {
            "t1": {"task_id": "t1", "step_ids": ["s1"], "results": {"s1": {"output": {"summary": "估值对比…"}}}, "errors": []},
            "t2": {"task_id": "t2", "step_ids": ["s2"], "results": {"s2": {"output": {"summary": "下次 FOMC…"}}}, "errors": []},
        }},
        "query": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候",
    }
    md = render_task_sections(state)
    assert md is not None
    first = md.index("AAPL, MSFT")
    second = md.index("美联储议息")
    assert first < second                      # priority 顺序
    assert md.count("\n## ") >= 2 or md.startswith("## ")


def test_single_task_returns_none():
    state = {"understanding": {"tasks": [{"id": "t1", "subject_label": "AAPL", "operation": {"name": "price"}, "priority": 25}]},
             "artifacts": {"task_results": {}}}
    assert render_task_sections(state) is None
```

- [ ] **Step 2: 实现**：`render_task_sections` 按契约实现（`OPERATION_LABELS` 中文标签表新建在 chat_renderer 顶部：`{"compare": "对比", "price": "价格", "macro_brief": "宏观", "fetch": "资讯", "investment_opinion": "投资观点", "technical": "技术面", "earnings_impact": "财报影响", "news_impact": "新闻影响", "qa": "问答"}`，未知 operation 用原名）；`render_chat_markdown` 入口第一段加：

```python
sectioned = render_task_sections(state)
if sectioned is not None:
    return _with_existing_prefixes(sectioned, state)   # 保留现有社交前缀/假设声明的包装逻辑
```

- [ ] **Step 3: 验证**：新测试 + 金样（multi_question 快照在 on 模式下出现两个小节——重录 v2 快照并审读）。

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(render): multi-question replies render one section per task, ordered by priority"
```

---

### Task 11: 灰度切换与收尾

- [ ] **Step 1:** `.env.server.example` 登记四个 flag 并注释含义；线上灰度顺序：`INTENT_FRAME=shadow`（观察 trace 对拍 3 天）→ `on` → `DAG_EXECUTOR=on` → `AGENT_BRIEF=on` → `EVIDENCE_BUS=on`。
- [ ] **Step 2:** 全部 on 稳定后：金样 v2 目录转正为唯一快照（删旧 snapshots，重命名 v2），`KNOWN_QUIRKS.md` 中已修复项打勾。
- [ ] **Step 3:** Commit

```bash
git commit -am "chore(rollout): document orchestration flags; promote v2 golden snapshots"
```

---

## WP2 完成门禁

- [ ] 四个 flag 全 on 时：`python -m pytest backend/tests tests/golden -x -q` 全绿
- [ ] 手工验收清单：
  - "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候" → 回答分两节，宏观节不缺失
  - "PE 是什么意思" → direct 秒回，不触发 agent
  - 断网 LLM router（改错 key）→ 仍能走规则 fallback 出研究结果，trace 标 `source=rules_fallback`
  - 投研报告模式：risk_agent 的分析文本中能看到引用前序 agent 发现的痕迹（黑板生效）
  - 执行指挥台瀑布图仍正常渲染（SSE 契约未破坏）
