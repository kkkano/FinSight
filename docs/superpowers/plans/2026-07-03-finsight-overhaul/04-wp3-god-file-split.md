# WP3 巨型文件机械拆分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把六个巨型文件（`planner_stub.py` 2480 / `understand_request.py` 3405 / `synthesize.py` 3202 / `chat_renderer.py` 2611 / `report_builder.py` 2693 / `api/main.py` 1356）拆成注册表 + 小模块，并把撒谎的 `*_stub` 命名全部改掉。**全程零行为变更。**

**Architecture:** 每个任务 = "建目标包 → 剪切函数 → 旧文件留兼容 shim → 金样零 diff"。统一模式是注册表分发（dict/list 查表）替代 if/elif 串。任务间无依赖，可乱序，但建议按体量从小到大练手。

**Tech Stack:** 纯 Python 重排，无新依赖。

## Global Constraints

- **[MECHANICAL] 全部任务零行为变更**：每个任务结束时 `python -m pytest backend/tests tests/golden -x -q` 必须全绿且金样零 diff（不允许 GOLDEN_UPDATE）。
- 剪切函数时**逐字搬运**，只允许改：import 路径、模块级常量引用。发现顺手想修的 bug → 记入 `notes-found-bugs.md`，另开任务，不在本 WP 修。
- 每个旧文件保留 shim（`from new.module import *  # noqa` + `__all__`）至少一个发布周期，WP3 最后一个任务统一删 shim 并全局改 import。
- 新文件 ≤400 行；一个函数一个家，禁止复制两份。

---

### Task 1: chat_renderer → renderers 注册表

**Files:**
- Create: `backend/graph/renderers/__init__.py`、`backend/graph/renderers/registry.py`、`backend/graph/renderers/{price,news,holdings,earnings,valuation,opinion,portfolio,compare,macro,url_fetch,misc}.py`
- Modify: `backend/graph/nodes/chat_renderer.py`（变 shim + 入口）

**Interfaces:**
- Produces:

```python
# registry.py
Renderer = Callable[[GraphState, dict[str, Any]], str | None]   # (state, ctx) -> markdown 片段或 None
RENDERERS: list[tuple[str, Renderer]] = [
    # ("price_line", price.render_price_line), ...  ← 顺序 = 原 render_chat_markdown 的拼接顺序，逐条对应
]
def render_chat_markdown(state: GraphState) -> str:
    parts = []
    ctx = build_render_ctx(state)      # 原函数开头的公共变量提取
    for name, renderer in RENDERERS:
        fragment = renderer(state, ctx)
        if fragment:
            parts.append(fragment)
    return join_fragments(parts, state)  # 原函数结尾的拼接/前缀逻辑
```

- [x] **Step 1: 画迁移地图**

Run: `grep -n "^def \|^async def " backend/graph/nodes/chat_renderer.py > /tmp/cr_functions.txt`
按功能域给 ~110 个函数分桶（价格/新闻/持仓/财报/估值/观点/组合/对比/宏观/URL/杂项），写入 `docs/superpowers/plans/2026-07-03-finsight-overhaul/notes-chat-renderer-map.md`：每行 `函数名 → 目标文件`。`render_chat_markdown` 主体中每个 `if …: parts.append(xxx())` 分支按出现顺序编号——这个顺序表就是 `RENDERERS` 列表。

- [x] **Step 2: 建包并逐桶剪切**（一桶一次小 commit，桶内函数连同其私有 helper 一起走；跨桶共用的 helper 进 `renderers/shared.py`）。

- [x] **Step 3: 主入口改写**：`render_chat_markdown` 按上面契约改为查表循环；分支条件进各 renderer 内部（renderer 自己判断"该不该出场"，不出场返回 None）。

- [x] **Step 4: shim**：`chat_renderer.py` 结尾保留 `from backend.graph.renderers.registry import render_chat_markdown  # noqa: F401`，旧测试不改路径也能跑。

- [x] **Step 5: 验证**：`python -m pytest backend/tests tests/golden -x -q` 全绿零 diff。

- [x] **Step 6: Commit**

```bash
git commit -am "refactor(render): split chat_renderer into renderers/ registry (mechanical, zero behavior change)"
```

---

### Task 2: planner_stub → planning/builders 注册表 + 改名

**Files:**
- Create: `backend/graph/planning/rule_planner.py`、`backend/graph/planning/steps.py`、`backend/graph/planning/builders/{company,macro,portfolio,holdings,theme,url_docs,earnings,valuation,selection}.py`
- Modify: `backend/graph/nodes/planner_stub.py`（变 shim）、`backend/graph/nodes/planner.py`（import 改指新家）

**Interfaces:**
- Produces:

```python
# steps.py —— 原 _append_tool_step / _append_agent_step 提为 StepFactory 类
class StepFactory:
    def __init__(self, ready_task_id_set: set[str]): ...
    def tool_step(self, name, inputs, *, task_ids=(), parallel_group=None, optional=False, depends_on=()) -> dict: ...
    def agent_step(self, name, inputs, *, task_ids=(), parallel_group=None, optional=False, depends_on=()) -> dict: ...

# builders/*.py —— 每个 subject_type 一个 builder
def build_steps(task: dict, ctx: PlanContext) -> list[dict]:
    """ctx 打包原巨型函数闭包里读的一切：query/output_mode/state 切片/StepFactory/env 快照。"""

# rule_planner.py
TASK_BUILDERS: dict[str, Builder] = {
    "company": company.build_steps, "index": company.build_steps, "crypto": company.build_steps,
    "fund": company.build_steps, "macro": macro.build_steps, "portfolio": portfolio.build_steps,
    "theme": theme.build_steps, "news_item": company.build_steps, "news_set": company.build_steps,
    "research_doc": url_docs.build_steps, "filing": url_docs.build_steps, "unknown": company.build_steps,
}
def rule_based_planner(state: GraphState) -> dict:
    """原 planner_stub() 的调度壳（<200 行）：遍历 ready tasks → 查表 → 汇 steps →
    组装 PlanIR（goal/budget/synthesis 的组装逻辑逐字搬运原函数尾部）。"""
```

- [ ] **Step 1: 画迁移地图**：原函数内 `_append_company_task_steps(:863)/_append_macro_task_steps(:1143)/_append_portfolio_task_steps(:1182)/_append_holdings_task_steps(:1221)/_append_theme_task_steps(:1304)`、earnings/valuation 专用（:511/:593/:643）、evidence steps（:302）等 → 对应 builder 文件；闭包工具函数（`_task_id/_task_tickers/_plan_task_summary` 等）→ `planning/util.py`。写入 `notes-planner-map.md`。
- [ ] **Step 2: 逐 builder 剪切**（闭包变量改经 `PlanContext` 传入；一 builder 一小 commit）。
- [ ] **Step 3: 改名**：`planner_stub` 函数改名 `rule_based_planner`；`planner_stub.py` 变 shim：

```python
# -*- coding: utf-8 -*-
"""DEPRECATED shim: rule-based planner moved to backend.graph.planning.rule_planner.
它从来不是 stub——是规则式生产 planner。保留到 WP3 Task 8 统一删除。"""
from backend.graph.planning.rule_planner import rule_based_planner as planner_stub  # noqa: F401
```

`planner.py:22` 改 `from backend.graph.planning.rule_planner import rule_based_planner`（fallback 调用点同步改名）。
- [ ] **Step 4: 验证**：全量 + 金样零 diff（金样覆盖 rule planner 的全部 subject_type 路径——若 `notes-planner-map.md` 发现金样没覆盖的 builder，先补一条金样 query 再动那个 builder）。
- [ ] **Step 5: Commit**

```bash
git commit -am "refactor(planner): rule planner split into builders registry; retire misleading *_stub name"
```

---

### Task 3: understand_request 物理归位 intent/ 包

**前置**：WP2 Task 3 已把主逻辑迁到 `intent/pipeline.py` + `intent/fallback_rules.py`，本任务只处理残余。

**Files:**
- Create: `backend/graph/intent/task_builders.py`（`_add_task/_add_per_ticker_company_tasks/_add_router_task_hints/_add_router_task_hints_contract/_add_holdings_intent_tasks/_add_explicit_url_tasks/_add_context_bound_research_task/_add_unbound_research_task` 及其 helper）、`backend/graph/intent/direct_reply.py`（`_direct_conversation_result/_sanitize_direct_chat_reply/_ensure_direct_reply_names_bound_tickers/_natural_clarify_question`）、`backend/graph/intent/operations.py`（`_operation/_company_operations/_macro_operation/_domain_intent_operation` 等 operation 构造器）
- Modify: `backend/graph/nodes/understand_request.py` → 变薄壳（目标 ≤200 行：flag 分发 + `_legacy_understand_request` 删除——legacy 路径在 WP2 Task 11 灰度完成后不再需要）
- Modify: `backend/graph/nodes/conversation_router.py` → `route_conversation/generate_contextual_reply/ConversationDecision` 迁到 `backend/graph/intent/router.py`，原文件变 shim

**Steps:**
- [ ] Step 1: 确认 WP2 Task 11 已完成（`FINSIGHT_INTENT_FRAME=on` 为默认）。未完成则本任务顺延。
- [ ] Step 2: 按 Files 清单逐模块剪切（一模块一 commit），`understand_request.py` 最终只剩节点函数壳 + shim import。
- [ ] Step 3: `graph/nodes/conversation_router.py` 变 shim 后，`api/conversation_router.py` 的命名冲突（BE-12）自然消解——grep 全仓确认没有模块把两者搞混：`grep -rn "from backend.graph.nodes.conversation_router import" backend | grep -v test`。
- [ ] Step 4: 全量 + 金样零 diff；Commit：

```bash
git commit -am "refactor(intent): understand_request internals relocated into backend/graph/intent package"
```

---

### Task 4: synthesize 拆分（render_vars + verifier）

**Files:**
- Create: `backend/graph/render_vars/__init__.py`、`backend/graph/render_vars/{overview,price,news,technical,valuation,risks,portfolio,macro,morning_brief}.py`、`backend/report/verifier.py`
- Modify: `backend/graph/nodes/synthesize.py`

**Interfaces:**

```python
# render_vars/__init__.py
def build_render_vars(state: GraphState) -> dict[str, Any]:
    """原 _stub_render_vars(724-1942) 的外壳：公共前置提取 + 逐板块调用 + 合并 dict。
    每个板块模块暴露 build(state, ctx) -> dict[str, Any]，键集 = 原函数中该板块写入的键，
    迁移时先在 notes-synthesize-map.md 登记每个板块写入的完整键清单，拆完 assert 并集不变。"""

# report/verifier.py —— 原 synthesize.py:372-560 的 claim 验证/redaction 整体搬入
def verify_and_redact_claims(draft: str, evidence_ledger: dict, *, config: VerifierConfig) -> VerifiedDraft: ...
```

**Steps:**
- [ ] Step 1: 键清单登记：读 `_stub_render_vars`，把 `vars["xxx"] = …` 的全部键按板块分组写入 `notes-synthesize-map.md`。
- [ ] Step 2: 建守护测试 `backend/tests/test_render_vars_keys.py`：对 2 个有代表性的 state fixture（从金样 run 中 dump），断言 `set(build_render_vars(state)) == set(_stub_render_vars_legacy(state))` 且逐键 `==`（拆分期间 legacy 副本临时保留为 `_stub_render_vars_legacy` 供对拍，拆完删除）。
- [ ] Step 3: 逐板块剪切（一板块一 commit）→ verifier 搬家 → `synthesize()` 内改调 `build_render_vars` / `verify_and_redact_claims`。
- [ ] Step 4: `_generate_narrative_draft`（~360 行）留在 synthesize.py（单一职责尚可）；`synthesize.py` 目标 ≤900 行。
- [ ] Step 5: 全量 + 金样零 diff + 对拍测试绿；Commit：

```bash
git commit -am "refactor(synthesize): render vars per-section modules + report verifier extraction (parity-tested)"
```

---

### Task 5: report_builder 拆分 + agent 格式化注册表

**Files:**
- Create: `backend/report/citations.py`、`backend/report/grounding.py`、`backend/report/quality_hints.py`、`backend/report/agent_formatters.py`
- Modify: `backend/graph/report_builder.py`（保留 payload 组装壳 + shim）

**Interfaces:**

```python
# agent_formatters.py —— 消灭"新增 agent 要来 report_builder 加格式化"的隐藏改动点
AgentClaimFormatter = Callable[[dict], list[str]]
AGENT_CLAIM_FORMATTERS: dict[str, AgentClaimFormatter] = {
    "price_agent": format_price_agent_claims,   # 原 _format_price_agent_claims 逐字搬入
    # …grep -n "_format_.*_agent" report_builder.py 找齐全部专属格式化函数
}
def format_agent_claims(agent_name: str, output: dict) -> list[str]:
    formatter = AGENT_CLAIM_FORMATTERS.get(agent_name)
    return formatter(output) if formatter else default_claim_format(output)
```

**Steps:**
- [ ] Step 1: 迁移地图（citations 域=`_build_citations`+URL 规范化；grounding 域=:1877-2044；quality 域=:1736 起；formatter 域=`_format_*_agent*`）→ `notes-report-builder-map.md`。
- [ ] Step 2: 逐域剪切（一域一 commit），report_builder 主入口改查表。
- [ ] Step 3: 全量 + 金样零 diff；Commit：

```bash
git commit -am "refactor(report): citations/grounding/quality-hints modules + agent claim formatter registry"
```

---

### Task 6: api/main.py 拆分 + execute_plan_stub 改名

**Files:**
- Create: `backend/api/app_factory.py`（`create_app() -> FastAPI`：CORS/中间件/router 装配，router 注册改列表驱动）、`backend/api/lifespan.py`（lifespan handler + `_schedulers` 生命周期）、`backend/api/security_gate.py`（`security_gate` 中间件 + 限流器/并发限制器 + `_resolve_client_ip` 等，整体搬运）
- Modify: `backend/api/main.py` → 目标 ≤120 行：`app = create_app()` + uvicorn 兼容入口
- Modify: `backend/graph/nodes/execute_plan_stub.py` → 函数改名 `execute_plan_node`，文件改名 `execute_plan_node.py`，原路径留 shim；`runner.py` 的 import 与 `add_node("execute_plan", …)` 改指新名；RAG ingestion helper（文件前 400 行）剪切到 `backend/rag/ingestion.py`
- Modify: `backend/graph/nodes/synthesize.py` 等处对 `render_stub` 的引用 → `render_node`（同模式改名）

**Steps:**
- [ ] Step 1: router 注册列表驱动：

```python
# app_factory.py
ROUTER_FACTORIES: list[Callable[[AppDeps], APIRouter]] = [ …24 个工厂按 main.py:1330-1353 现有顺序… ]
for factory in ROUTER_FACTORIES:
    app.include_router(factory(deps))
```

- [ ] Step 2: 逐块剪切（security_gate → lifespan → 装配 → 改名），每块一 commit；`python -c "import backend.api.main"` + `uvicorn backend.api.main:app` 冒烟每块必跑。
- [ ] Step 3: 全量 + 金样 + `/health` 冒烟；Commit：

```bash
git commit -am "refactor(api): main.py split into app_factory/lifespan/security_gate; execute_plan & render nodes renamed off *_stub"
```

---

### Task 7: rebalance schema 下沉（BE-07）

**Files:**
- Create: `backend/services/rebalance/schemas.py`（原 `backend/api/rebalance_schemas.py` 整体搬入）
- Modify: `backend/api/rebalance_schemas.py`（变 shim）、`backend/services/rebalance_engine.py:23`、`backend/services/rebalance_llm_enhancer.py:19`、`backend/api/rebalance_router.py`（import 改指 services）

**Steps:**
- [ ] Step 1: 搬家 + shim + 三处 import 反转（api → services 方向恢复正确）。
- [ ] Step 2: 守护：`grep -rn "from backend.api" backend/services backend/graph backend/agents backend/tools --include="*.py"` 结果必须为空（新增架构测试 `backend/tests/test_layering.py` 固化该断言）：

```python
# backend/tests/test_layering.py
import pathlib, re

FORBIDDEN = re.compile(r"from backend\.api|import backend\.api")

def test_lower_layers_never_import_api():
    for pkg in ("services", "graph", "agents", "tools", "rag"):
        for path in pathlib.Path(f"backend/{pkg}").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not FORBIDDEN.search(text), f"{path} imports backend.api (layering violation)"
```

- [ ] Step 3: Commit

```bash
git commit -am "refactor(layering): rebalance schemas moved under services; add import-direction guard test"
```

---

### Task 8: 收尾——删 shim、合并 agents router、全局卫生

**Files:**
- Modify: 全部 WP3 shim 文件删除 + 全仓 import 改指新路径（`grep -rln "planner_stub\|execute_plan_stub\|chat_renderer import\|rebalance_schemas" backend tests`）
- Modify: `backend/api/agents_router.py` 吸收 `agent_router.py` 的 preferences 端点（BE-12：`agent_router.py` 删除，`main.py` 装配列表去掉一项）；`_AGENT_DISPLAY_META` 与 `REPORT_AGENT_CANDIDATES` 加启动一致性断言：

```python
_missing = set(REPORT_AGENT_CANDIDATES) - set(_AGENT_DISPLAY_META)
assert not _missing, f"agents missing display meta: {_missing}"
```

- Modify: 顺手治理 BE-03 中"本 WP 碰过的文件"里的 `except: pass` → 全部补 `logger.debug(..., exc_info=True)`（只加日志，不改控制流）。

**Steps:**
- [ ] Step 1-3: 依次执行上述三组；每组全量 + 金样验证。
- [ ] Step 4: Commit

```bash
git commit -am "refactor(cleanup): remove WP3 shims, merge agents routers, annotate silent excepts in touched files"
```

---

## WP3 完成门禁

- [ ] `python -m pytest backend/tests tests/golden -x -q` 全绿，金样全程零 diff
- [ ] `wc -l` 抽查：`nodes/` 与 `api/main.py` 无 >900 行文件；仓库不再有 `*_stub` 命名的生产模块
- [ ] `python -m pytest backend/tests/test_layering.py -x -q` 绿（依赖方向守护生效）
- [ ] 新增 agent 演练（文档验证）：按 `docs/AGENTS_GUIDE.md` 走一遍"加一个假 agent"，确认改动点 ≤3 处（capability_registry + adapter 映射 + display meta 同文件）——把演练结果写进 PR 描述
