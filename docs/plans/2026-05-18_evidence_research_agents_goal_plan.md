# Evidence Research Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for implementation when splitting tasks, or `superpowers:executing-plans` for inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 FinSight 从“多 Agent 金融分析平台”升级为“证据驱动、可辩论、可追踪持仓、协议就绪的金融研究 Agent 平台”。

**Architecture:** 本计划不先做 A2A/MCP 外壳。先在现有 LangGraph 主链路中引入统一 Evidence Ledger 和 query coverage，再把 DeepSearch、多空辩论、13F/Form 4 持仓研究接入同一证据合同。协议层只暴露已经稳定的研究任务和只读工具。

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, Pydantic 2, existing `backend/graph` pipeline, existing `backend/agents`, existing `backend/rag` 三层 collection, React 19 + Vite, Vitest, Playwright, pytest.

---

## Goal Runner Prompt

把下面这段作为 `/goal` 目标即可直接开跑：

```text
在 E:\FinSight 的 feature/evidence-research-agents 分支执行 docs/plans/2026-05-18_evidence_research_agents_goal_plan.md。按 Task 0 到 Task 14 顺序推进，遵守 TDD：每个任务先写或更新测试，再实现最小代码，再运行任务指定验证命令。每个任务完成后更新复核记录；不要跳过 README 大小写核查、Evidence Ledger 合同、query coverage、DeepSearch 工作集、debate node、SEC 13F/Form 4 工具、前端证据展示和 MCP/A2A 只读暴露的验收门槛。
```

---

## Current Code Map

- `backend/agents/base_agent.py` 已有 `EvidenceItem`、`ConflictClaim`、`AgentOutput` dataclass，是 Agent 层事实来源的起点。
- `backend/graph/request_task_contract.py` 已有 lightweight `EvidenceItem` TypedDict 和 `ToolError`，是 routing/execution/rendering 之间的现有 UX 合同。
- `backend/graph/nodes/execute_plan_stub.py` 已经把 selection、tool output、agent output 汇总成 `artifacts.evidence_pool`，并写入 RAG working set / memory / kb 检索链。
- `backend/graph/nodes/synthesize.py` 已有闭卷合成、未来事件 scrub、deep verifier、conflict disclosure 逻辑。
- `backend/graph/report_builder.py` 已有 citations、grounding rate、report quality、verifier gap、agent diagnostics、conflict tags。
- `backend/agents/deep_search_agent.py` 已有 Self-RAG loop、SearchConvergence、文档抓取、SSRF 防护，但仍有 legacy `session:deepsearch:*` collection。
- `backend/tools/sec.py` 只有 10-K/10-Q/8-K、risk factors、companyfacts；没有 13F holdings / Form 4 insider transaction extraction。
- `backend/graph/runner.py` 当前主链路是 `understand_request -> policy_gate -> planner -> confirmation_gate -> execute_plan -> synthesize -> render`。
- `frontend/src/components/report/ReportView.tsx`、`frontend/src/components/execution/*`、`frontend/src/pages/RagInspectorPage.tsx` 是证据、运行进度和报告可解释性的前端落点。

## Non-Goals

- 不做自动交易、真实下单、券商账户接入。
- 不把 13F 或 Form 4 当实时买卖信号；13F 明确有季度延迟，Form 4 也只表示公开披露交易，不等同投资建议。
- 不把 MCP/A2A 做成核心能力的替代品；协议层只读、无副作用、默认 feature flag 关闭。
- 不重写整个 LangGraph 主链路；只在现有边界增加合同、节点和适配器。

## Feature Flags

新增能力全部受 feature flag 控制：

```text
RESEARCH_LEDGER_ENABLED=true
QUERY_COVERAGE_ENABLED=true
DEBATE_GRAPH_ENABLED=false
SEC_HOLDINGS_ENABLED=false
MCP_SERVER_ENABLED=false
A2A_SERVER_ENABLED=false
```

默认执行策略：P0/P1 的 ledger 和 coverage 可以默认启用；P2 之后的 debate、holdings、protocol server 默认关闭，测试和 demo 显式打开。

---

## Task 0: Branch Hygiene and README Casing Check

**Files:**
- Inspect: `README.md`, `readme_cn.md`, `.gitattributes`
- Modify: `docs/11_PRODUCTION_RUNBOOK.md` and `CHANGELOG.md` only if they still reference lowercase `readme.md`
- Modify: `docs/DOCS_INDEX.md` only if a docs entry changes

- [x] **Step 0.1: Verify branch and tracked README files**

Run:

```powershell
git status --short --branch
git ls-files README.md readme.md readme_cn.md
```

Expected:

```text
## feature/evidence-research-agents
README.md
readme_cn.md
```

- [x] **Step 0.2: Confirm there is no tracked lowercase duplicate**

Run:

```powershell
git ls-files --stage -- README.md readme.md readme_cn.md .gitattributes
git show HEAD:readme.md
```

Expected:

- `README.md`, `readme_cn.md`, and `.gitattributes` are tracked.
- `git show HEAD:readme.md` fails with `path 'readme.md' exists on disk, but not in 'HEAD'`.
- On Windows, `Test-Path .\readme.md` may still return true because the filesystem is case-insensitive; do not treat that as a tracked lowercase file.

- [x] **Step 0.3: Do not run duplicate-removal commands**

Do not run:

```text
git rm --cached readme.md
```

There is no lowercase README entry in the current index, so removal would be unnecessary and risky on a case-insensitive filesystem.

- [ ] **Step 0.4: Align current documentation references**

Update current documentation that still points to lowercase `readme.md`:

- `docs/11_PRODUCTION_RUNBOOK.md`: use `README.md` / `readme_cn.md`.
- `CHANGELOG.md` current Unreleased entry: use `README.md` / `readme_cn.md`.

Do not bulk-edit historical `docs/feature_logs`, archived changelogs, or old audit records unless they are being actively maintained.

- [ ] **Step 0.5: Keep `.gitattributes` as the casing guard**

`.gitattributes` should keep:

```gitattributes
* text=auto eol=lf

README.md text eol=lf
readme_cn.md text eol=lf

*.bat text eol=crlf
*.cmd text eol=crlf
- [ ] **Step 0.6: Validate**

Run:

```powershell
git status --short
git ls-files --stage -- README.md readme.md readme_cn.md .gitattributes
rg -n "`readme\.md`" docs\11_PRODUCTION_RUNBOOK.md CHANGELOG.md
```

Acceptance:

- `README.md` and `readme_cn.md` are tracked.
- `readme.md` is no longer tracked.
- `readme_cn.md` English link points to `./README.md`.
- Current docs do not instruct future agents to remove `readme.md`.

---

## Task 1: Evidence Ledger Contract

**Files:**
- Create: `backend/research/__init__.py`
- Create: `backend/research/evidence_ledger.py`
- Modify: `backend/agents/base_agent.py`
- Modify: `backend/graph/request_task_contract.py`
- Test: `backend/tests/test_evidence_ledger_contract.py`

- [ ] **Step 1.1: Write tests for claim-level evidence**

Create `backend/tests/test_evidence_ledger_contract.py` with coverage for:

- `ResearchClaim` rejects empty `claim`.
- `EvidenceLedger` keeps `claims`, `sources`, `uncertainties`, `contradictions`, `coverage_targets`.
- `from_agent_output()` converts existing `AgentOutput.evidence` into claim-linked ledger entries without changing current Agent output behavior.
- `to_prompt_context()` produces compact JSON with no raw trace or private diagnostics.

Test command:

```powershell
python -m pytest backend\tests\test_evidence_ledger_contract.py -q
```

Expected before implementation: import failure for `backend.research.evidence_ledger`.

- [ ] **Step 1.2: Implement the contract**

Create Pydantic models in `backend/research/evidence_ledger.py`:

```python
class SourceRef(BaseModel):
    source_id: str
    title: str = ""
    url: str | None = None
    source: str = "unknown"
    published_date: str | None = None
    as_of: str | None = None
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    freshness_hours: float | None = None
    layer: str | None = None
    collection: str | None = None

class ResearchClaim(BaseModel):
    claim_id: str
    claim: str = Field(min_length=1)
    stance: Literal["bull", "bear", "neutral", "risk", "unknown"] = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    agent_name: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

class EvidenceLedger(BaseModel):
    ledger_id: str
    query: str
    subject: dict[str, Any] = Field(default_factory=dict)
    claims: list[ResearchClaim] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    coverage_targets: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
```

Also implement:

- `stable_id(prefix: str, *parts: Any) -> str`
- `source_from_evidence_item(item, agent_name, index) -> SourceRef`
- `claim_from_summary(summary, source_ids, agent_name, confidence, task_ids) -> ResearchClaim`
- `from_agent_output(output, query, subject, task_ids) -> EvidenceLedger`
- `merge_ledgers(query, subject, ledgers) -> EvidenceLedger`
- `to_prompt_context(ledger, max_claims=24, max_sources=24) -> dict`

- [ ] **Step 1.3: Preserve dataclass compatibility**

Modify `backend/agents/base_agent.py`:

- Keep existing `EvidenceItem`, `ConflictClaim`, `AgentOutput`.
- Add optional `claims: list[dict[str, Any]] = field(default_factory=list)` to `AgentOutput`.
- Add optional `ledger: dict[str, Any] | None = None` to `AgentOutput`.

Reason: current tests and adapters expect dataclasses; avoid forcing all 7 agents to change immediately.

- [ ] **Step 1.4: Extend lightweight TypedDict contract**

Modify `backend/graph/request_task_contract.py` `EvidenceItem` with optional fields:

```python
claim_id: str
source_id: str
stance: str
as_of: str | None
reliability: float
layer: str
collection: str
limitations: list[str]
```

- [ ] **Step 1.5: Validate**

Run:

```powershell
python -m pytest backend\tests\test_evidence_ledger_contract.py backend\tests\test_agents.py backend\tests\test_agent_adapter_resilience.py -q
```

Commit:

```powershell
git add backend\research backend\agents\base_agent.py backend\graph\request_task_contract.py backend\tests\test_evidence_ledger_contract.py
git commit -m "feat: add evidence ledger contract"
```

---

## Task 2: Build Ledger from Execution Artifacts

**Files:**
- Create: `backend/research/ledger_builder.py`
- Modify: `backend/graph/nodes/execute_plan_stub.py`
- Modify: `backend/graph/state.py`
- Test: `backend/tests/test_evidence_ledger_execute_plan.py`

- [ ] **Step 2.1: Write tests for artifact conversion**

Create tests that construct a `GraphState` with:

- `artifacts.step_results` containing one successful `price_agent` output.
- `artifacts.evidence_pool` containing one URL-backed source.
- `artifacts.rag_context` containing one hit with `layer`, `collection`, `chunk_id`.

Expected:

- `execute_plan_stub()` returns `artifacts.evidence_ledger`.
- Ledger contains deduped source IDs.
- Agent output evidence is not duplicated when the same URL appears in `evidence_pool`.
- RAG hit metadata is preserved in `sources[].layer` and `sources[].collection`.

Run:

```powershell
python -m pytest backend\tests\test_evidence_ledger_execute_plan.py -q
```

- [ ] **Step 2.2: Implement ledger builder**

`backend/research/ledger_builder.py` responsibilities:

- `build_ledger_from_artifacts(state, artifacts) -> dict[str, Any]`
- `extract_agent_ledgers(step_results, query, subject) -> list[EvidenceLedger]`
- `extract_pool_sources(evidence_pool) -> list[SourceRef]`
- `extract_rag_sources(rag_context) -> list[SourceRef]`
- `attach_pool_sources_to_claims(ledger, pool_sources) -> EvidenceLedger`

Dedup key:

```text
normalized_url if url exists else sha1(title|source|snippet|published_date)
```

- [ ] **Step 2.3: Attach ledger in execute_plan_stub**

Modify `backend/graph/nodes/execute_plan_stub.py` after `artifacts["evidence_pool"] = deduped` and after `rag_context` is set:

```python
if os.getenv("RESEARCH_LEDGER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
    from backend.research.ledger_builder import build_ledger_from_artifacts
    artifacts["evidence_ledger"] = build_ledger_from_artifacts(state, artifacts)
```

The import stays local to avoid startup coupling.

- [ ] **Step 2.4: Extend GraphState artifacts typing**

Modify `backend/graph/state.py`:

```python
class Artifacts(TypedDict, total=False):
    evidence_pool: list[dict]
    evidence_ledger: dict
    ...
```

- [ ] **Step 2.5: Validate**

Run:

```powershell
python -m pytest backend\tests\test_evidence_ledger_execute_plan.py backend\tests\test_live_tools_evidence.py backend\tests\test_rag_observability_execute_plan.py -q
```

Commit:

```powershell
git add backend\research\ledger_builder.py backend\graph\nodes\execute_plan_stub.py backend\graph\state.py backend\tests\test_evidence_ledger_execute_plan.py
git commit -m "feat: build evidence ledger from execution artifacts"
```

---

## Task 3: Query Coverage Contract

**Files:**
- Create: `backend/research/query_coverage.py`
- Modify: `backend/graph/nodes/synthesize.py`
- Modify: `backend/graph/report_builder.py`
- Test: `backend/tests/test_query_coverage_contract.py`

- [ ] **Step 3.1: Write tests for answer targets**

Test inputs:

- `state.tasks[]` with operations `generate_report`, `analyze_impact`, `technical`.
- `state.reply_contract` with `continuation_target`.
- `state.query` asking “估值、风险、未来三个月看什么”.

Expected:

- `build_answer_targets(state)` returns target IDs and labels.
- `evaluate_coverage(ledger, targets)` marks covered targets when claims mention matching dimensions.
- Missing targets are returned as `unanswered_targets`.

Run:

```powershell
python -m pytest backend\tests\test_query_coverage_contract.py -q
```

- [ ] **Step 3.2: Implement deterministic coverage**

`backend/research/query_coverage.py`:

- `build_answer_targets(state) -> list[dict[str, Any]]`
- `evaluate_coverage(ledger, targets) -> dict[str, Any]`
- `coverage_warning_text(coverage) -> str`

Target dimensions:

```text
valuation, risk, catalyst, technical, fundamental, macro, price, news, portfolio, holdings, direct_answer
```

Use deterministic keyword matching first. No LLM call in P1.

- [ ] **Step 3.3: Feed coverage into synthesize**

Modify `backend/graph/nodes/synthesize.py`:

- Include `evidence_ledger` compact context in the prompt.
- Include `query_coverage` in `artifacts`.
- Add prompt rule: first section must answer all `answer_targets`; missing targets must be disclosed.

- [ ] **Step 3.4: Feed coverage into report payload**

Modify `backend/graph/report_builder.py`:

- Add `query_coverage` to `report_hints`.
- Add top-level `query_coverage` to validated report.
- If `unanswered_targets` is non-empty, add `query_coverage_gap` tag and reduce confidence no lower than existing verifier/grounding penalties.

- [ ] **Step 3.5: Validate**

Run:

```powershell
python -m pytest backend\tests\test_query_coverage_contract.py backend\tests\test_synthesize_node.py backend\tests\test_report_builder_quality_gate.py -q
```

Commit:

```powershell
git add backend\research\query_coverage.py backend\graph\nodes\synthesize.py backend\graph\report_builder.py backend\tests\test_query_coverage_contract.py
git commit -m "feat: add query coverage contract"
```

---

## Task 4: Agent Claim Extraction Adapter

**Files:**
- Create: `backend/research/claim_extractor.py`
- Modify: `backend/graph/adapters/agent_adapter.py`
- Test: `backend/tests/test_agent_claim_extractor.py`

- [ ] **Step 4.1: Write tests for agent outputs**

Test cases:

- Summary with bullish terms produces `stance="bull"`.
- Summary with risk/downside terms produces `stance="bear"` or `stance="risk"`.
- Existing `conflicting_claims` from `technical_agent`, `macro_agent`, `fundamental_agent` are copied to ledger contradictions.
- Adapter still returns old keys: `summary`, `evidence`, `confidence`, `data_sources`.

- [ ] **Step 4.2: Implement deterministic claim extractor**

`backend/research/claim_extractor.py`:

- `extract_claims_from_agent_output(output: dict, query: str, ticker: str) -> list[dict]`
- `infer_stance(text: str, risks: list[str]) -> str`
- `extract_limitations(output: dict) -> list[str]`
- `conflicts_to_contradictions(output: dict) -> list[dict]`

No LLM call in this task.

- [ ] **Step 4.3: Attach claims in agent adapter**

Modify `_normalize_agent_output()` in `backend/graph/adapters/agent_adapter.py`:

- After evidence normalization, call extractor.
- Set `payload["claims"]`.
- Preserve existing `conflicting_claims` fields if present.

- [ ] **Step 4.4: Validate**

Run:

```powershell
python -m pytest backend\tests\test_agent_claim_extractor.py backend\tests\test_agent_adapter_resilience.py backend\tests\test_technical_fundamental_agents.py backend\tests\test_risk_agent.py -q
```

Commit:

```powershell
git add backend\research\claim_extractor.py backend\graph\adapters\agent_adapter.py backend\tests\test_agent_claim_extractor.py
git commit -m "feat: extract claim metadata from agent outputs"
```

---

## Task 5: DeepSearch Working Set and Subgraph Facade

**Files:**
- Create: `backend/research/deep_research_flow.py`
- Modify: `backend/agents/deep_search_agent.py`
- Modify: `backend/rag/layering.py` only if a helper is missing
- Test: `backend/tests/test_deep_research_flow.py`
- Test: `backend/tests/test_deep_research.py`

- [ ] **Step 5.1: Write flow tests**

Test deterministic flow stages:

```text
plan_search -> fetch_sources -> extract_claims -> gap_check -> targeted_followup -> ledger_write
```

Expected:

- Flow emits stage records with `stage`, `query`, `source_count`, `claim_count`.
- Flow writes collection names using `ws:deepsearch:*` through existing `build_thread_working_set_collection()` helpers.
- Flow does not create `session:deepsearch:*` for new writes.
- Unsafe URLs are rejected before fetch.

- [ ] **Step 5.2: Extract flow orchestration**

Create `backend/research/deep_research_flow.py`:

- `DeepResearchStageResult`
- `DeepResearchFlowResult`
- `run_deep_research_flow(agent, query, ticker, on_event=None) -> DeepResearchFlowResult`

This facade can call existing `DeepSearchAgent` private helpers in the first implementation, but stage names and return payload must be stable.

- [ ] **Step 5.3: Replace legacy collection naming**

Modify `DeepSearchAgent._build_rag_collection()`:

- Use `build_thread_working_set_collection()` where `thread_id` is available.
- When `thread_id` is absent inside legacy direct agent tests, use `ws:deepsearch:{ticker}:{digest}` instead of `session:deepsearch:{ticker}:{digest}`.

- [ ] **Step 5.4: Attach ledger output**

Modify `DeepSearchAgent._format_output()`:

- Fill `AgentOutput.claims`.
- Fill `AgentOutput.ledger` with compact `EvidenceLedger.model_dump()`.

- [ ] **Step 5.5: Validate**

Run:

```powershell
python -m pytest backend\tests\test_deep_research_flow.py backend\tests\test_deep_research.py backend\tests\test_deep_search_ssrf.py backend\tests\test_search_convergence.py -q
```

Commit:

```powershell
git add backend\research\deep_research_flow.py backend\agents\deep_search_agent.py backend\tests\test_deep_research_flow.py
git commit -m "feat: structure deep research flow around evidence ledger"
```

---

## Task 6: Bull/Bear/Judge Debate Node

**Files:**
- Create: `backend/research/debate.py`
- Create: `backend/graph/nodes/research_debate.py`
- Modify: `backend/graph/runner.py`
- Modify: `backend/graph/nodes/__init__.py`
- Test: `backend/tests/test_research_debate.py`
- Test: `backend/tests/test_graph_node_order.py`

- [ ] **Step 6.1: Write debate engine tests**

Input: an `EvidenceLedger` with 2 bull claims, 2 bear/risk claims, 1 neutral claim.

Expected debate artifact:

```json
{
  "bull_thesis": {"claims": [...]},
  "bear_thesis": {"claims": [...]},
  "cross_examination": [...],
  "judge_scorecard": {
    "bull_score": 0.0,
    "bear_score": 0.0,
    "evidence_balance": "mixed",
    "key_disagreements": [...]
  },
  "consensus": "...",
  "open_questions": [...]
}
```

- [ ] **Step 6.2: Implement deterministic debate engine**

`backend/research/debate.py`:

- `build_bull_thesis(ledger)`
- `build_bear_thesis(ledger)`
- `cross_examine(bull, bear)`
- `judge_debate(ledger, bull, bear)`
- `build_debate_artifact(ledger, query)`

No LLM dependency in first pass. The artifact must be useful when LLM is offline.

- [ ] **Step 6.3: Add LangGraph node**

`backend/graph/nodes/research_debate.py`:

- If `DEBATE_GRAPH_ENABLED` is false, return state unchanged.
- If `artifacts.evidence_ledger` is missing, add `artifacts.debate = {"enabled": true, "status": "skipped", "reason": "missing_evidence_ledger"}`.
- If present, add `artifacts.debate` and trace event.

- [ ] **Step 6.4: Wire node into graph**

Modify `backend/graph/runner.py`:

```python
graph.add_node("research_debate", with_node_trace("research_debate", research_debate))
graph.add_edge("execute_plan", "research_debate")
graph.add_edge("research_debate", "synthesize")
```

Remove the direct `execute_plan -> synthesize` edge.

- [ ] **Step 6.5: Surface debate in synthesis/report**

Modify `backend/graph/nodes/synthesize.py` and `backend/graph/report_builder.py`:

- Include `artifacts.debate.judge_scorecard` in prompt context.
- Add report hint `has_debate=true`.
- Add report tag `debate` when scorecard exists.

- [ ] **Step 6.6: Validate**

Run:

```powershell
python -m pytest backend\tests\test_research_debate.py backend\tests\test_graph_node_order.py backend\tests\test_synthesize_node.py backend\tests\test_report_builder_synthesis_report.py -q
```

Commit:

```powershell
git add backend\research\debate.py backend\graph\nodes\research_debate.py backend\graph\runner.py backend\graph\nodes\__init__.py backend\tests\test_research_debate.py
git commit -m "feat: add evidence-based research debate node"
```

---

## Task 7: SEC 13F and Form 4 Holdings Tools

**Files:**
- Create: `backend/tools/sec_holdings.py`
- Modify: `backend/tools/__init__.py`
- Modify: `backend/tools/manifest.py`
- Modify: `backend/langchain_tools.py`
- Test: `backend/tests/test_sec_holdings_tools.py`
- Test: `backend/tests/test_tool_manifest.py`
- Test: `backend/tests/test_tools_capabilities_api.py`

- [ ] **Step 7.1: Write SEC holdings tests with mocked HTTP**

Tests:

- `get_institutional_holdings()` rejects non-US use with explicit `supported_market="US"`.
- Missing `SEC_USER_AGENT` returns `missing_sec_user_agent`.
- A mocked `13F-HR` filing with `infotable.xml` returns holdings rows.
- A mocked Form 4 XML returns insider transactions with transaction code, acquired/disposed flag, shares, price, direct/indirect ownership.
- `get_holdings_overlap()` compares institution holdings against user portfolio tickers.

Regulatory facts to encode in tool metadata:

- SEC Form 13F is due within 45 days after each calendar quarter end.
- In most cases, Form 4 is filed within two business days following the transaction date.

Sources:

- SEC Form 13F FAQ: `https://www.sec.gov/divisions/investment/13ffaq.htm`
- SEC Form 13F Data Sets: `https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets`
- SEC Investor Bulletin on Forms 3, 4, 5: `https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-69`

- [ ] **Step 7.2: Implement SEC holdings module**

`backend/tools/sec_holdings.py` functions:

- `get_institutional_holdings(cik_or_name: str, quarter: str | None = None, limit: int = 100) -> dict`
- `get_institution_holdings_by_ticker(ticker: str, limit: int = 50) -> dict`
- `get_insider_transactions(ticker: str, days: int = 180, limit: int = 50) -> dict`
- `get_holdings_overlap(positions: list[dict], holder_cik_or_name: str, quarter: str | None = None) -> dict`

Use existing helpers from `backend/tools/sec.py`:

- `_resolve_user_agent`
- `_is_valid_user_agent`
- `_sec_headers`
- `_load_ticker_map`
- `_fetch_submissions`
- `_build_filing_url`
- `_detect_market`
- `_error_payload`

Parsing rules:

- 13F: find recent forms `13F-HR` and `13F-HR/A`, fetch filing index or primary XML, parse `<infoTable>` rows.
- Form 4: find recent forms `4` and `4/A`, fetch XML primary document, parse `nonDerivativeTransaction` and `derivativeTransaction`.
- Never infer hidden intent. Return raw transaction codes and a plain-English `interpretation_note`.

- [ ] **Step 7.3: Register tools**

Add manifest entries:

```python
ToolManifestEntry(
    name="get_institutional_holdings",
    group="regulatory",
    markets=("US",),
    operations=("holdings", "qa", "generate_report", "analyze_impact"),
    depths=("report", "deep_research"),
    risk_level="low",
    timeout_ms=20000,
    cache_ttl_s=3600,
    requires_env=("SEC_USER_AGENT",),
)
```

Also register:

- `get_institution_holdings_by_ticker`
- `get_insider_transactions`
- `get_holdings_overlap`

Add wrappers in `backend/langchain_tools.py` with Pydantic input models.

- [ ] **Step 7.4: Validate**

Run:

```powershell
python -m pytest backend\tests\test_sec_holdings_tools.py backend\tests\test_sec_tools.py backend\tests\test_tool_manifest.py backend\tests\test_tools_capabilities_api.py -q
```

Commit:

```powershell
git add backend\tools\sec_holdings.py backend\tools\__init__.py backend\tools\manifest.py backend\langchain_tools.py backend\tests\test_sec_holdings_tools.py
git commit -m "feat: add SEC holdings and insider transaction tools"
```

---

## Task 8: Holdings-Aware Planning and Portfolio Overlap

**Files:**
- Modify: `backend/graph/nodes/understand_request.py`
- Modify: `backend/graph/nodes/policy_gate.py`
- Modify: `backend/graph/nodes/planner_stub.py`
- Modify: `backend/graph/planner_prompt.py`
- Test: `backend/tests/test_holdings_planning.py`
- Test: `backend/tests/test_policy_planner_query_regression.py`

- [ ] **Step 8.1: Add holdings intent tests**

Queries:

- “巴菲特最近持仓变化和我的 NVDA/AAPL 组合有什么重叠？”
- “AAPL 最近 insider 买卖有没有异常？”
- “哪些机构最近加仓了 MSFT？”

Expected:

- `understand_request` produces operation `holdings` or `analyze_impact` with `subject_type` `company` or `portfolio`.
- `policy_gate` allowlists new SEC holdings tools for US market only.
- `planner_stub` emits holdings tool steps under `SEC_HOLDINGS_ENABLED=true`.

- [ ] **Step 8.2: Update request understanding deterministic hints**

Add holdings hints:

```text
13f, form 4, insider, institutional holdings, superinvestor, buffett, berkshire, 名义持仓, 机构持仓, 名人持仓, 内部人交易, 增持, 减持
```

Do not classify “insider information” as Form 4. Existing safety boundary for private insider information must remain `chat_answer` with refusal/clarification.

- [ ] **Step 8.3: Update policy and planner**

`policy_gate.py`:

- Add holdings operation support.
- Add US-only allowlist.
- Do not include holdings tools when `ui_context.market` is `CN` or `HK`.

`planner_stub.py`:

- Add `_append_holdings_task_steps()`.
- For portfolio tasks with positions, call `get_holdings_overlap`.
- For company tasks, call `get_insider_transactions` and `get_institution_holdings_by_ticker`.

- [ ] **Step 8.4: Validate**

Run:

```powershell
python -m pytest backend\tests\test_holdings_planning.py backend\tests\test_policy_planner_query_regression.py backend\tests\test_understand_request.py backend\tests\test_chat_response_contract.py -q
```

Commit:

```powershell
git add backend\graph\nodes\understand_request.py backend\graph\nodes\policy_gate.py backend\graph\nodes\planner_stub.py backend\graph\planner_prompt.py backend\tests\test_holdings_planning.py backend\tests\test_policy_planner_query_regression.py
git commit -m "feat: plan holdings-aware research tasks"
```

---

## Task 9: Frontend Evidence, Debate, and Holdings Display

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/components/report/EvidenceLedgerPanel.tsx`
- Create: `frontend/src/components/report/DebateScorecard.tsx`
- Create: `frontend/src/components/report/HoldingsWatchPanel.tsx`
- Modify: `frontend/src/components/report/ReportView.tsx`
- Test: `frontend/src/components/report/EvidenceLedgerPanel.test.tsx`
- Test: `frontend/src/components/report/DebateScorecard.test.tsx`

- [ ] **Step 9.1: Write UI tests**

Tests:

- Evidence panel renders source title, source domain, `as_of`, confidence, layer badge.
- Debate scorecard renders bull score, bear score, key disagreements, open questions.
- Holdings panel renders 13F delay note and Form 4 transaction rows.
- Missing ledger shows compact empty state, not raw JSON.

- [ ] **Step 9.2: Add frontend types**

Add TypeScript interfaces:

- `EvidenceLedger`
- `ResearchClaim`
- `SourceRef`
- `DebateArtifact`
- `HoldingsInsight`
- `QueryCoverage`

- [ ] **Step 9.3: Add report sections**

Modify `ReportView.tsx`:

- Show query coverage warning near the top when `report.query_coverage.unanswered_targets.length > 0`.
- Add tabs or collapsible sections for Evidence, Debate, Holdings.
- Keep dense workbench/report style; no landing-page visuals.

- [ ] **Step 9.4: Validate**

Run:

```powershell
npm --prefix frontend run test:unit -- src/components/report/EvidenceLedgerPanel.test.tsx src/components/report/DebateScorecard.test.tsx
npm --prefix frontend run build
```

Commit:

```powershell
git add frontend\src\types\index.ts frontend\src\api\client.ts frontend\src\components\report
git commit -m "feat: show evidence ledger and debate scorecard"
```

---

## Task 10: Read-Only Research API Surface

**Files:**
- Create: `backend/api/research_router.py`
- Modify: `backend/api/main.py`
- Test: `backend/tests/test_research_router.py`

- [ ] **Step 10.1: Write API tests**

Endpoints:

- `GET /api/research/ledger/{report_id}`
- `GET /api/research/debate/{report_id}`
- `GET /api/research/holdings/{ticker}`
- `POST /api/research/run-debate`

Expected:

- Read endpoints require the same report/session access rules as report replay.
- `run-debate` is side-effect-free; it accepts a ledger payload and returns an artifact without starting a graph run.

- [ ] **Step 10.2: Implement router**

Use existing `backend/services/report_index.py` where possible. Do not create a new DB until report replay cannot provide required artifacts.

- [ ] **Step 10.3: Validate**

Run:

```powershell
python -m pytest backend\tests\test_research_router.py backend\tests\test_report_index_api.py backend\tests\test_security_gate_auth_rate_limit.py -q
```

Commit:

```powershell
git add backend\api\research_router.py backend\api\main.py backend\tests\test_research_router.py
git commit -m "feat: expose read-only research artifacts"
```

---

## Task 11: MCP Server for Stable Tools

**Files:**
- Create: `backend/protocols/__init__.py`
- Create: `backend/protocols/mcp_server.py`
- Create: `backend/tests/test_mcp_server_contract.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `.env.server.example`

- [ ] **Step 11.1: Write contract tests**

Tools exposed:

- `research_company`
- `get_evidence_ledger`
- `run_debate`
- `track_institutional_holdings`
- `get_insider_transactions`

Expected:

- Tools are read-only.
- Disabled when `MCP_SERVER_ENABLED` is false.
- Tool schemas do not expose internal trace payloads or secrets.

- [ ] **Step 11.2: Implement minimal MCP server**

Use the official MCP Python package only if already present or accepted as a dependency. If adding dependency, use a narrowly scoped requirement and document it.

Server module responsibilities:

- Map MCP tool calls to existing read-only API/service functions.
- Return JSON-serializable artifacts.
- Never execute portfolio writes, alerts, rebalance writes, or delete operations.

- [ ] **Step 11.3: Validate**

Run:

```powershell
python -m pytest backend\tests\test_mcp_server_contract.py -q
python -m compileall backend
```

Commit:

```powershell
git add backend\protocols\mcp_server.py backend\tests\test_mcp_server_contract.py requirements.txt .env.example .env.server.example
git commit -m "feat: add read-only MCP protocol server"
```

---

## Task 12: A2A Agent Card and Long-Task Adapter

**Files:**
- Create: `backend/protocols/a2a_server.py`
- Create: `backend/protocols/a2a_models.py`
- Create: `backend/tests/test_a2a_contract.py`
- Modify: `.env.example`
- Modify: `.env.server.example`

- [ ] **Step 12.1: Write A2A contract tests**

Capabilities:

- Agent card describes FinSight research skills: company deep research, portfolio diagnosis, holdings change investigation.
- Long task adapter maps to existing `/api/execute` service.
- Streaming emits task state and final artifacts.
- Disabled when `A2A_SERVER_ENABLED` is false.

- [ ] **Step 12.2: Implement minimal adapter**

Implementation shape:

- `build_agent_card() -> dict`
- `submit_task(payload) -> run_id`
- `stream_task(run_id) -> iterator`
- `get_task_artifacts(run_id) -> dict`

Do not implement cross-vendor ChatGPT/Gemini/Claude delegation in this milestone.

- [ ] **Step 12.3: Validate**

Run:

```powershell
python -m pytest backend\tests\test_a2a_contract.py backend\tests\test_execution_stage_events.py backend\tests\test_streaming_sse.py -q
```

Commit:

```powershell
git add backend\protocols\a2a_server.py backend\protocols\a2a_models.py backend\tests\test_a2a_contract.py .env.example .env.server.example
git commit -m "feat: add protocol-ready A2A adapter"
```

---

## Task 13: Evaluation Gates

**Files:**
- Create: `tests/eval/evidence_research_cases.json`
- Create: `scripts/evidence_research_eval.py`
- Test: `backend/tests/test_evidence_research_eval_smoke.py`
- Modify: `tests/rag_qualityV2/REPORT.md` only after a real run

- [ ] **Step 13.1: Add eval cases**

Minimum 8 cases:

1. AAPL deep report with filing evidence.
2. NVDA bull/bear debate.
3. MSFT risk-focused report.
4. TSLA insider/Form 4 question.
5. Berkshire 13F overlap with AAPL.
6. Portfolio overlap with NVDA/MSFT/AAPL.
7. CN ticker rejects SEC holdings tools.
8. “insider information” safety boundary remains non-tool refusal/clarification.

- [ ] **Step 13.2: Implement eval script**

Metrics:

- `ledger_claim_count`
- `source_count`
- `query_coverage_rate`
- `grounding_rate`
- `verifier_unresolved_count`
- `debate_artifact_present`
- `holdings_latency_disclosed`
- `unsafe_insider_request_blocked`

- [ ] **Step 13.3: Validate**

Run:

```powershell
python -m pytest backend\tests\test_evidence_research_eval_smoke.py -q
python scripts\evidence_research_eval.py --dataset tests\eval\evidence_research_cases.json --run-id local-evidence
```

Commit:

```powershell
git add tests\eval\evidence_research_cases.json scripts\evidence_research_eval.py backend\tests\test_evidence_research_eval_smoke.py
git commit -m "test: add evidence research evaluation gate"
```

---

## Task 14: Documentation, Release Evidence, and Final Regression

**Files:**
- Modify: `docs/DOCS_INDEX.md`
- Modify: `docs/AGENTS_GUIDE.md`
- Create: `docs/release_evidence/2026-05-18_evidence_research_agents.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 14.1: Update docs**

Document:

- Evidence Ledger contract and artifact shape.
- Debate artifact shape.
- Holdings limitations: US-only first version; 13F delayed; Form 4 transaction data is disclosure, not a trading recommendation.
- MCP/A2A flags and run commands.

- [ ] **Step 14.2: Run targeted backend regression**

Run:

```powershell
python -m pytest backend\tests\test_evidence_ledger_contract.py backend\tests\test_evidence_ledger_execute_plan.py backend\tests\test_query_coverage_contract.py backend\tests\test_agent_claim_extractor.py backend\tests\test_deep_research_flow.py backend\tests\test_research_debate.py backend\tests\test_sec_holdings_tools.py backend\tests\test_holdings_planning.py backend\tests\test_research_router.py -q
```

- [ ] **Step 14.3: Run existing quality gates**

Run:

```powershell
python -m pytest backend\tests\test_understand_request.py backend\tests\test_langgraph_skeleton.py backend\tests\test_policy_gate.py backend\tests\test_reply_contract_lanes.py backend\tests\test_evidence_diagnostics_gate.py -q
python scripts\chat_ux_router_eval.py --dataset tests\eval\chat_router_100.json --run-id evidence-branch
python -m pytest tests\rag_qualityV2\test_gate_v2.py -q
npm --prefix frontend run test:unit
npm --prefix frontend run build
```

- [ ] **Step 14.4: Record release evidence**

Create `docs/release_evidence/2026-05-18_evidence_research_agents.md` with:

- Branch name.
- Commit range.
- Commands run.
- Pass/fail output summary.
- Known disabled feature flags.
- Residual risks.

Commit:

```powershell
git add docs\DOCS_INDEX.md docs\AGENTS_GUIDE.md docs\release_evidence\2026-05-18_evidence_research_agents.md CHANGELOG.md
git commit -m "docs: record evidence research rollout"
```

---

## Rollout Order

1. P0: Task 0.
2. P1 core: Tasks 1, 2, 3, 4.
3. P1 deep research: Task 5.
4. P2 orchestration: Task 6.
5. P2 holdings: Tasks 7, 8.
6. P3 UI and APIs: Tasks 9, 10.
7. P4 protocol: Tasks 11, 12.
8. P5 quality and docs: Tasks 13, 14.

Review gate after P1:

```powershell
python -m pytest backend\tests\test_evidence_ledger_contract.py backend\tests\test_evidence_ledger_execute_plan.py backend\tests\test_query_coverage_contract.py backend\tests\test_agent_claim_extractor.py -q
```

Review gate after P2:

```powershell
python -m pytest backend\tests\test_deep_research_flow.py backend\tests\test_research_debate.py backend\tests\test_sec_holdings_tools.py backend\tests\test_holdings_planning.py -q
```

Full ship gate:

```powershell
python -m pytest backend\tests -q
python scripts\chat_ux_router_eval.py --dataset tests\eval\chat_router_100.json --run-id evidence-final
python -m pytest tests\rag_qualityV2\test_gate_v2.py -q
npm --prefix frontend run test:unit
npm --prefix frontend run build
```

---

## Residual Risks

- 13F coverage depends on SEC filing structure and may require parsing both primary XML and information table attachments.
- Form 4 interpretation is easy to overstate; UI and reports must show transaction codes and caveats.
- Debate artifacts can look impressive while merely rearranging weak evidence; judge score must penalize low source count and low grounding.
- Adding a node to `runner.py` changes graph order; `test_graph_node_order.py` must lock the new path.
- MCP/A2A dependencies may add package friction; keep protocol tasks isolated and feature-flagged.

## Completion Definition

The branch is complete when:

- Evidence Ledger exists in report artifacts for normal research runs.
- Reports show query coverage and source-grounded confidence.
- DeepSearch no longer writes new `session:deepsearch:*` collections.
- Debate scorecard is generated from ledger claims when enabled.
- SEC holdings tools return mocked 13F/Form 4 results with tests.
- Holdings planning is US-only and safety-boundary compliant.
- Frontend renders evidence/debate/holdings without raw trace exposure.
- MCP/A2A protocol adapters are read-only and disabled by default.
- Targeted backend tests, chat router eval, RAG gate, frontend unit tests, and frontend build pass.
