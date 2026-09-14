# 10 Agent 原生化（Agent-Native）Implementation Plan

> **For agentic workers:** 按 Task 顺序执行，每个 Task 一次 commit。标注【盘点】的先跑盘点步骤再按分支执行。本文档与 WP2（编排力学）互补：WP2 让 agent **能**协作，本文档让 agent **像一个团队**并让用户**感知到**。

**基线 commit:** `4a1c055`
**Goal:** 把"7 个智能体"从聊天管线里的匿名执行单元，提升为产品的一等公民：有组织（分工/质询/委托）、有身份（档案/记忆/战绩）、有存在感（tab 驻场、署名、随处可召唤）。

**Architecture:** 三层递进——组织学（后端协作协议，Part 1）→ 身份系统（档案/记忆/锚定预测/战绩与成本，Part 2）→ 感知层（评分器合一、驻场、署名，Part 3）。Part 1 依赖 WP2 的 DAG 执行器与证据黑板；Part 2 在 09 D-0 的最小 prediction contract/store/submit 上扩展，不反向阻塞 09；Part 3 消费前两层。Kansoku 只提供「submit 校验、锚点、确定性对账、成本归档」的闭环范式，运行时仍采用现有 FastAPI + LangGraph + PostgreSQL，图表消费端仍为 ECharts。

**Kansoku 适配硬边界:** 不引入 Longbridge、`pi-agent-core`、单用户 SQLite 新表、Fastify 内嵌 Vite 或 `lightweight-charts`。模型不生成行情、不直接写数据库；所有 prediction 经服务端 Pydantic + 业务规则校验后，由受信任服务写入带 `user_id` 的 PostgreSQL 表。

---

## 诊断：三层孤岛（每条有实锤）

**① 组织学孤岛——有管道，没有团队结构。**
- WP2 落地后 agent 能读到彼此摘要（黑板），但 7 个 agent 依然平级各写各的：`capability_registry.select_agents_for_request` 只做"评分选人"（capability_registry.py:222-274），选出的名单没有 lead/support 结构；`synthesize` 事后缝合是唯一汇合点。
- `research_debate`（research_debate.py:16）默认关闭，开了也是确定性规则拼"正反清单"，没有任何 agent 质询 agent 的行为。
- agent 缺数据只能自己 `search` 兜底（base_agent.py:129-155 的 tool registry），不能请求队友：price_agent.py 里 12 处 TODO 自述"缺同行发现工具/缺事件归因工具"——这些恰恰是 news_agent/deep_search_agent 的本职。

**② 身份孤岛——agent 没有"人格连续性"。**
- 每次调用即抛弃：`agent_adapter.build_agent_invokers` 每个请求重新实例化 agent（agent_adapter.py:315-330），对同一 ticker 的历史观点零记忆——上周说"AAPL 超买"，本周涨了 8% 也不会说"验证了/打脸了"。
- agent 的"人设"分散三处且不一致：`agents_router._AGENT_DISPLAY_META`（中文展示名）、`base_agent._llm_analyze` 的 role 参数（各 agent 自己传）、`capability_registry.AGENT_CAPABILITIES`（能力权重）——没有单一档案。
- 没有战绩：报告给出观点后无人回头验证，用户没有"这个分析师靠不靠谱"的依据。

**③ 感知孤岛——用户看不见团队（主人"tab 跟 agent 关系不大"的真相）。**
- **桥其实已经建了**：`backend/dashboard/agent_bridge.py` 定义了完整的 Tab→Agent 深挖协议（`_TAB_AGENTS` 映射、每 tab 的 agent 指令与默认问题），前端 5 个 tab + `useDashboardDeepDive` hook 都已接线。**但用户依然无感**，因为：
  - 日常看到的"AI 洞察卡"来自另一套系统——`insights_scorer.py` 的确定性打分 + `insights_prompts.py` 的单次 LLM 快评（README 自述"非自主智能体，不在研究管线内"），**与 7 个 agent 无人格关联**：同一个"技术面"，洞察卡是无名评分器，深挖是 technical_agent，用户以为是两个东西（实际上产品希望它们是一个"技术面分析师"）。
  - 深挖入口藏在洞察卡里（AiInsightCard 内），没有"驻场分析师"的叙事。
  - 报告/晨报/监控发现全部匿名——`chat_renderer` 渲染的报告章节不署名，monitor findings 不说是谁发现的。

**结论:** WP2 修力学、08 修皮肤、09 修联动，都没修"**Agent 是产品的什么**"。本文档回答它：FinSight 的差异化叙事应当是"**你的 7 人分析师团队**"，下面每个 Task 都在把这句话变成可感知的实现。

---

## Part 1: 组织学——团队协作协议（依赖 WP2 T5/T6/T7 已合入）

### Task 1: Agent 档案单一注册表（后续一切的地基）

**Files:**
- Create: `backend/agents/profiles.py`
- Modify: `backend/api/agents_router.py`（`_AGENT_DISPLAY_META` 改读 profiles）、`backend/graph/capability_registry.py`（capability 并入 profile 或互相引用）
- Test: `backend/tests/test_agent_profiles.py`

**Interfaces（后续 Task 全部依赖，签名逐字用）:**

```python
# backend/agents/profiles.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class AgentProfile:
    key: str                    # "technical_agent"
    name_zh: str                # "技术面分析师"
    short_zh: str               # "技术面"（≤4字，用于 tab/chip）
    glyph: str                  # 单字符标识，终端风: "T"（价格P/新闻N/基本面F/技术T/宏观M/风险R/深搜D）
    color_token: str            # "t-info" 等 08 文档色 token 名（前端据此上色，禁止另配色）
    mandate_zh: str             # 一句话职责（"趋势、动量、关键价位与量价结构"）
    tools: tuple[str, ...]      # 本职工具名（与 _get_tool_registry 对齐）
    scorer_key: str | None      # 对应 dashboard 评分器（"technical"），无则 None
    dashboard_tabs: tuple[str, ...] = ()   # 驻场 tab（对齐 agent_bridge._TAB_AGENTS 反查）

AGENT_PROFILES: dict[str, AgentProfile] = { ... 7 个 agent 逐一定义 ... }

def profile(key: str) -> AgentProfile: ...          # 未知 key 抛 KeyError
def profile_for_scorer(scorer_key: str) -> AgentProfile | None: ...
def lead_agent_for_operation(operation: str) -> str:
    """operation → lead agent 映射（写死表）:
    investment_opinion/generate_report→fundamental_agent; technical→technical_agent;
    price→price_agent; fetch/news_impact→news_agent; analyze_impact→news_agent;
    earnings_*→fundamental_agent; compare→fundamental_agent; macro_*→macro_agent;
    portfolio_*/rebalance_check→risk_agent; qa→deep_search_agent; 其余→fundamental_agent"""
```

- [x] Step 1: TDD——7 个 profile 完整性断言（key 集合 == REPORT_AGENT_CANDIDATES；scorer_key 与 `backend/dashboard/insights_scorer.py` 的 score_* 函数名集合互相覆盖；dashboard_tabs 与 `agent_bridge._TAB_AGENTS` 一致性断言）。
- [x] Step 2: 实现 profiles.py；`agents_router` 的 `_AGENT_DISPLAY_META` 删除、改由 profiles 生成（对外 JSON 结构不变，加 `glyph/color_token/mandate` 字段）。
- [x] Step 3: 启动一致性断言（WP3 T8 的模式）：profiles ↔ capability_registry ↔ agent_bridge 三方 key 对齐。
- [x] Commit: `feat(agents): single AgentProfile registry — identity, mandate, glyph, scorer & tab bindings`

### Task 2: Lead/Support 结构 + 报告署名

**Files:**
- Modify: `backend/graph/nodes/planner_stub.py`（或 WP3 后的 `planning/rule_planner.py`）：agent step 的 inputs 增加 `"role": "lead" | "support"`（由 `lead_agent_for_operation(task.operation)` 决定；lead 不在选中名单时名单头部者为 lead）
- Modify: `backend/graph/report_builder.py`（或 WP3 后的 `report/` 包）：报告各 agent 小节标题带署名 `### 技术面 · 技术面分析师`；结论段由 lead 的 summary 领衔
- Modify: `backend/graph/nodes/chat_renderer.py`：`_agent_summary` 类渲染同样带 `profile(name).name_zh` 署名
- Test: `backend/tests/test_lead_agent_attribution.py`（构造两 agent 输出的 state → 断言报告 markdown 含署名与 lead 领衔顺序）

- [x] Step 1: TDD → 实现 → 金样零 diff 确认（署名属于渲染文本变化，金样切片不含 markdown 正文则零 diff；若含，重录并在 commit 说明）。
- [x] Commit: `feat(report): lead/support roles and analyst attribution in reports and chat summaries`

### Task 3: 挑战轮——复活 research_debate 为真质询

**Files:**
- Modify: `backend/research/debate.py`、`backend/graph/nodes/research_debate.py`
- Test: `backend/tests/test_challenge_round.py`

**协议（写死，不搞开放式多轮）:**

```
条件: output_mode == "investment_report" 且 ≥3 个 agent 产出 且 DEBATE_GRAPH_ENABLED=true（默认改 true）
流程: risk_agent 作为固定质询者，输入 = 各 agent 的 summary + 关键 evidence 标题（黑板已有），
      单次 LLM 调用产出结构化质询: [{target_agent, challenge_zh(≤80字), severity: low|med|high}]（≤3条）
落点: artifacts["debate"]["challenges"]；report_builder 渲染为「风险质询」小节
      （每条: ⚠ 对{name_zh}: {challenge_zh}）；synthesize 的冲突检测输入合并 challenges。
超时/失败: 整轮跳过（现有 try/except 结构保留），报告无该小节，不阻塞主链路。
```

- [x] Step 1: TDD（mock LLM 返回两条质询 → 断言 artifacts 结构与报告小节渲染；LLM 失败 → 报告正常无小节）。
- [x] Step 2: 实现（`build_debate_artifact` 改造为上述协议；prompt 写进 `backend/prompts/` 现有目录，要求输出 JSON、引用具体数字、不允许空泛质疑）。
- [x] Step 3: `.env.server.example` 更新 `DEBATE_GRAPH_ENABLED=true` 默认与说明。
- [x] Commit: `feat(debate): risk-agent challenge round produces attributed structured objections in reports`

### Task 4: 委托机制——agent 可请求补证据（受控版）

**Files:**
- Modify: `backend/agents/base_agent.py`（AgentOutput 增加 `requests: list[dict]` 字段，反思循环允许产出 `{"type": "delegate", "evidence": "peer_tickers", "reason": …}`）
- Modify: `backend/graph/dag_executor.py`（WP2 产物）：agent step 完成后若 output.requests 非空且 `FINSIGHT_AGENT_DELEGATION=on` → 查 `DELEGATION_CATALOG` 追加**最多 1 个**动态 tool step；动态 step 必须 `depends_on=[requesting_agent_step_id]`、继承其 `task_ids`，同 task 的后续 agent/synthesize barrier 必须等待该 step，产出只写对应 task 黑板。
- Create: `backend/graph/planning/delegation.py`：

```python
DELEGATION_CATALOG: dict[str, dict] = {
    # 白名单：可被委托补充的证据类型 → 具体 tool step 模板（kind/name/inputs 构造器）
    "peer_tickers": {...},        # 同行清单（price_agent 的 TODO 痛点）
    "event_context": {...},       # 价格异动新闻检索
    "macro_snapshot": {...},
}
LIMITS = {"max_dynamic_steps_per_run": 2}
```

- [x] Step 1: TDD（agent 输出 requests → executor 追加白名单内 step 且全局不超 2 个；断言 depends_on/requesting task_ids/barrier 正确，另一 task 看不到其证据；白名单外忽略并记 trace）。
- [x] Step 2: 实现（flag 默认 off；在当前调度批次结束后、同 task 下一阶段前插入受控 step，不允许运行中追加无依赖 root）。
- [x] Commit: `feat(agents): bounded delegation — agents may request whitelisted supplementary evidence steps`

---

## Part 2: 身份系统——记忆与战绩

### Task 5: Agent 观点与预测锚点档案（stance + prediction ledger）

**Files:**
- Modify: `backend/agents/prediction_contract.py`、`backend/services/agent_prediction_store.py`（09 D-0 产物）
- Test: `backend/tests/test_prediction_contract.py`、`backend/tests/test_agent_prediction_store.py`
- Modify: `backend/graph/report_builder.py`（报告落库时同步写已校验观点）、`backend/graph/adapters/agent_adapter.py`（AgentBrief.context_digest 注入历史观点）

**Pydantic 合同（行情与判断分离）:** 以下在 09 D-0 的既有 `PredictionDraft → AgentPrediction` 单一合同上扩展。为保持已上线 overlay/逐 bar 计算兼容，锚点时间/价位及价位字段继续使用 D-0 的 ISO 字符串 + 有限正浮点表示；服务端身份、状态、`report_id` 仍只存在于 `AgentPrediction`。

```python
class PredictionAnchor(BaseModel):
    timeframe: str
    time: str
    price: float

class PredictionScenario(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    probability: int = Field(ge=0, le=100)
    invalidation: str = Field(min_length=1, max_length=200)

class AgentPrediction(BaseModel):
    symbol: str
    agent: str
    direction: Literal["long", "short", "neutral"]
    confidence: float = Field(ge=0, le=1)
    thesis: str = Field(min_length=1, max_length=400)
    anchor: PredictionAnchor
    entry_type: Literal["market", "limit", "stop"] | None = None
    entry: float | None = None
    stop: float | None = None
    target1: float | None = None
    target2: float | None = None
    invalidation_price: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    scenarios: list[PredictionScenario] = Field(min_length=2, max_length=4)
```

`AgentPrediction` 只表达判断和价位，不允许 `bars/candles/series/ohlc` 字段（`extra="forbid"`）。long/short 必须有 entry_type/entry/stop/target1/invalidation_price；neutral 必须无 entry/stop/target 且有 range_low/range_high。anchor 的最终时间和价格由服务端用现有真实 quote/K 线校准，不接受模型伪造行情。逐 bar 入场/跳空/同 bar 冲突规则沿用 09 D-0，不在 10 另造第二套语义。

**PostgreSQL 存储（新表不落 SQLite）:**

```sql
CREATE TABLE IF NOT EXISTS agent_predictions (
  id UUID PRIMARY KEY,
  user_id TEXT NOT NULL,
  agent TEXT NOT NULL,            -- "technical_agent"
  symbol TEXT NOT NULL,
  direction TEXT NOT NULL,        -- long | short | neutral
  confidence DOUBLE PRECISION NOT NULL,
  thesis TEXT NOT NULL,
  anchor_timeframe TEXT NOT NULL,
  anchor_time TEXT NOT NULL,
  anchor_price DOUBLE PRECISION NOT NULL,
  entry_type TEXT,
  entry DOUBLE PRECISION,
  stop DOUBLE PRECISION,
  target1 DOUBLE PRECISION,
  target2 DOUBLE PRECISION,
  invalidation_price DOUBLE PRECISION,
  range_low DOUBLE PRECISION,
  range_high DOUBLE PRECISION,
  scenarios JSONB NOT NULL,
  report_id TEXT,
  run_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (direction IN ('long', 'short', 'neutral')),
  UNIQUE (id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_predictions_owner_ticker
  ON agent_predictions(user_id, symbol, created_at DESC);
```

**接口:**

```python
def record_prediction(*, prediction: AgentPrediction, user_id: str,
                      run_id: str, report_id: str | None) -> UUID: ...
def latest_predictions(*, ticker: str, user_id: str,
                       limit_per_agent: int = 1) -> list[dict]: ...
def prediction_history(*, agent: str, ticker: str, user_id: str,
                       limit: int = 5) -> list[dict]: ...
```

- [x] Step 1: 在 09 D-0 测试上扩展 scenarios/历史合同：long/short 缺 entry_type/entry/stop/target1/invalidation_price 拒绝；neutral 带 entry 或 range 不含 anchor 拒绝；scenario 概率和不在 90-110 拒绝。
- [x] Step 2: 用项目 PostgreSQL 连接/迁移机制实现 store；user_id 只从服务端身份传入，所有读写 SQL 必须同时约束 user_id。事务隔离的真实 PostgreSQL fixture 已通过，不以临时 SQLite 代替。
- [x] Step 3: 报告完成时仅归档通过 Task 5A 校验的 prediction；没有结构化 prediction 时保留原报告但不从 summary 关键词猜价位、不伪造 anchor，并记录 `prediction_missing` 诊断。
- [x] Step 4: 回忆注入——agent_adapter 构造 AgentBrief 时读取同 user/agent/ticker 最近一条 prediction，在 context_digest 前追加 `你上次({anchor_time})对{ticker}判断 {direction}：{thesis前60字}；锚点 {anchor_price}，entry/stop/T1={...}，当前 outcome={...}`。历史观点只作上下文，不自动继承为本轮结论。
- [x] 验收: 每条可计分观点都有可信 anchor 与 entry/stop/target（neutral 为 range）；数据库无 `user_id='public'` 默认；AI payload 无法写入任何行情 series。
- [x] Commit: `feat(agents): postgres prediction ledger with trusted anchors and actionable levels`（`6e47ff5`）

### Task 5A: `submit_prediction` 工具 + 服务端校验回路

**Files:**
- Extend: `backend/agents/prediction_submit.py`（09 D-0 已创建）
- Modify: `backend/graph/adapters/agent_adapter.py`（Agent 主摘要后执行服务端管理的终结提交；DAG 继续透传结构化 output）
- Test: `backend/tests/test_prediction_submit.py`、`backend/tests/test_agent_adapter_resilience.py`

**协议:** 扩展 09 D-0 的 `submit_prediction`。仅 `prediction_eligible=true`（concrete ticker + `investment_opinion/technical/earnings_impact/report_generation` + price/fundamental/technical/risk 可计分 agent）的 LangGraph agent step 在主摘要后进入服务端管理的终结提交，并要求恰好一次**成功的**提交；macro/news/qa/document/无 ticker step 不进入提交回路且允许零提交。首次非法提交允许纠正一次。服务端先读取最新完整 bar，把可信 time/close 提供给终结提交，再做 Pydantic 与领域校验并覆盖 symbol/agent/user/run/anchor：long 为 `stop < entry < target1`、short 为 `target1 < entry < stop`、T1 风险收益比 `abs(target1-entry) / abs(entry-stop) >= 1`、target2 比 target1 更远、neutral range 包含 anchor、scenario 概率和 `100±10`。不得信任模型提供的 user_id、agent、run_id 或 anchor quote。

- [x] Step 1: TDD 构造「eligible step 第一次 stop 方向错误 → 工具返回 `{ok:false,issues:[...]}` → 同一 agent step 修正后第二次通过」；断言只有最终通过值落库；另测 macro/news/qa/无 ticker step 不暴露工具、不产生 `prediction_missing` 失败。
- [x] Step 2: 实现结构化 issues（字段、规则、当前值、期望关系），通过下一次受限终结提交 prompt 原样回送模型；每个 agent step 最多 2 次提交，第二次仍失败则返回 `prediction_validation_failed`，主摘要可继续但不得落档或计入战绩。
- [x] Step 3: 服务端覆盖 `symbol/agent/user_id/run_id`；模型 anchor time 必须等于最新完整 bar，anchor price 与服务端 bar close 偏差不得超过 0.5%，通过后以服务端 time/close 作为最终 anchor。行情不可用时 fail closed，不允许模型自报价格绕过。
- [x] Step 4: 记录 validation attempts、issues 和最终状态到 trace，但在用户输出/日志中脱敏；不引入 `pi-agent-core` 或开放式 agent loop。
- [x] 验收: 非法 RR、反向 stop、伪造 ticker/anchor、概率和错误都无法入库；一次纠错可成功；超过两次不会形成无限循环或重复计费。
- [x] Commit: `feat(agents): server-validated submit_prediction loop for LangGraph agents`

### Task 6: 确定性 Outcome / 战绩与成本归档

**Files:**
- Create: `backend/services/prediction_outcomes.py`、`backend/services/agent_run_archive.py`
- Test: `backend/tests/test_prediction_outcomes.py`、`backend/tests/test_agent_run_archive.py`
- Modify: `backend/api/agents_router.py`（GET /api/agents 响应附带战绩摘要）
- Modify: `backend/services/llm_usage.py`、调度器装配（`backend/api/lifespan.py`）

**规则（写死，不搞花活）:**

```
long/short: 从 anchor_time 后第一根完整 K 线开始扫描；先判 entry 是否触发，触发后按时间顺序判 target1/stop。
  同一根 OHLC 同时穿 target 与 stop 时采用保守规则 hit_stop，并记 resolution_reason=same_bar_conservative。
neutral: 固定 10 个交易日观察窗；窗口内收盘越出 range → broke_range，到期仍在 range → held_range。
未到终点: open；入场前穿越失效价: invalidated。Outcome 计算只读真实 K 线，零 LLM 调用，可重复执行且幂等。
agent 战绩: 近 90 天按 agent + direction 分桶；hit_target/held_range 算 hit，hit_stop/broke_range 算 miss；
  invalidated 单独展示、不混入命中率；有效样本 <5 显示"样本不足"。
```

**PostgreSQL 归档:** `agent_prediction_outcomes(prediction_id UUID, user_id TEXT, status TEXT, resolved_at TIMESTAMPTZ, pct_since_anchor DOUBLE PRECISION, resolution_reason TEXT, evaluated_through TIMESTAMPTZ, updated_at TIMESTAMPTZ, PRIMARY KEY(prediction_id, user_id), FOREIGN KEY(prediction_id,user_id) REFERENCES agent_predictions(id,user_id))`，索引 `(user_id, status, updated_at)`；`agent_run_archive(..., user_id TEXT, prediction_id UUID NULL, ..., FOREIGN KEY(prediction_id,user_id) REFERENCES agent_predictions(id,user_id))`，索引 `(user_id, agent, created_at)`。数据库层必须拒绝跨租户 prediction 关联；成本从现有 LLM usage/cost trace 归集，不再新建 agent SQLite 库。

- [x] Step 1: TDD 用固定 OHLC fixture 覆盖 waiting/triggered/hit_target/hit_stop/held_range/broke_range/invalidated/open，以及同 bar 双穿的保守判定；重复执行结果与数据库行完全一致。
- [x] Step 2: 实现纯函数 resolver + PostgreSQL upsert；日更调度批量评估未决 prediction，行情缺口只推进 `evaluated_through` 到最后可信 bar，不把缺数据判 miss。
- [x] Step 3: 把每次 agent/monitor commentator/analyst 调用的 token、成本、耗时、状态按 `run_id + agent + layer` 归档，并可关联 prediction_id；失败/校验重试同样记成本，避免只统计成功调用。
- [x] Step 4: `/api/agents` 增加 `track_record` 与 `cost_summary`：90 天 hits/misses/invalidated/hit_rate、样本数、最近评估时间，以及 7/30 天 tokens/cost/run_count。所有聚合限定当前 user；管理员全局聚合走独立权限端点。
- [x] Step 5: Agent 档案页展示方向分桶战绩与成本趋势；成本高但无有效 prediction 的 run 单独计为 `unscored_runs`，不粉饰命中率。
- [x] 验收: outcome resolver 在断网、无模型环境仍可全量运行；同 fixture 在任意时区/重复执行结果一致；用户只能看到自己的战绩与成本；数据库可从 prediction 追到 run/cost/outcome 完整链路。
- [x] Commit: `feat(agents): deterministic prediction outcomes with postgres track-record and cost archive`

---

## Part 3: 感知层——让用户看见团队

### Task 7: 评分器与 agent 人格合一（"两套系统"的根治）

**Files:**
- Modify: `backend/dashboard/insights_prompts.py`、`backend/dashboard/insights_engine.py`
- Modify: `frontend/src/components/dashboard/tabs/shared/AiInsightCard.tsx`

**决定:** 不重写评分器（确定性打分逻辑保留），只做**人格归属**：
- 后端：`insights_engine.generate` 的响应每个洞察卡附 `analyst: {key, name_zh, glyph, color_token, mandate_zh}`（经 `profile_for_scorer(scorer_key)` 查 Task 1 注册表）；`insights_prompts.py` 各 tab 的 system prompt 开头统一改为 `你是{name_zh}，职责是{mandate_zh}。`——**与 agent 深挖时的 persona 同源**，一个"技术面分析师"只有一个人格。
- 前端：AiInsightCard 头部渲染 `[glyph] {name_zh}` 署名（glyph 用 08 规范的 Tag 样式 + color_token 上色）；卡底按钮文案从"深挖"改为 `请{short_zh}分析师深入分析 →`（点击走既有 useDashboardDeepDive，行为不变）。

- [x] Step 1: 后端 TDD（insights 响应含 analyst 字段；prompt 含 name_zh——mock 断言）。
- [x] Step 2: 前端接字段 + 文案（vitest：卡片渲染署名）。
- [x] Step 3: 验收：技术 tab 的洞察卡和深挖结果都署名"技术面分析师"——用户眼里它们终于是同一个人。
- [x] Commit: `feat(dashboard): insight cards and deep-dives share one analyst persona per domain`

### Task 8: 深挖入口显性化——每个 tab 的"驻场分析师栏"

**Files:**
- Create: `frontend/src/components/dashboard/tabs/shared/ResidentAnalystBar.tsx`
- Modify: 五个 tab 组件（Overview/Financial/Technical/News/Peers）顶部挂入

**规格:**

```
┌ [T] 技术面分析师 驻场 · 趋势、动量、关键价位与量价结构      [问TA] [深入分析] ┐
```

- 数据：GET /api/agents 已含 profile 字段（Task 1）+ 战绩（Task 6，样本足够时附 `近90天命中率 70%`，`num` 类）；
- [问TA]：打开 MiniChat 预填 `@{agent} `（AgentMention 语法，走 agents_override 强制该 agent）；[深入分析]：现有 deep-dive。
- 类名走 08 规范（Tag/ghost Button）；一行高 40px，不抢内容。

- [x] Step 1: 实现 + vitest（渲染 profile 与两按钮回调）。
- [x] Step 2: 五 tab 挂入（overview 显示 lead=综合，其余按 `profile.dashboard_tabs` 反查首个驻场 agent）。
- [x] Commit: `feat(dashboard): resident analyst bar on every tab — the team is visible where users live`

### Task 9: 全链路署名清扫

**Files:**
- Modify: `frontend/src/components/execution/AgentWorkLog.tsx`（08 T5 产物）：agent 名与 glyph/color_token 经 /api/agents profile 渲染（删除前端本地 AGENT_LABELS 硬编码，08 T3 引入的 `src/config/agentLabels.ts` 改为从 API 缓存生成）
- Modify: `frontend/src/components/workbench/FindingCard.tsx`：监控发现卡片标注来源 `由{name_zh}规则发现`（monitor_engine 的 finding 数据带上 agent/规则域字段——`grep -n "source\|rule" backend/services/monitor_engine.py` 对齐；若 finding 无 agent 概念则标注规则名，不硬凑）
- Modify: 晨报 `MorningBriefCard`：要点若来自某 agent 产出（morning_brief 后端组装时已知），附 short_zh chip

- [x] Step 1【盘点】: monitor/morning_brief 数据结构里 agent 归属字段是否存在，写 notes；不存在的仅做规则名标注，不改后端。
- [x] Step 2: 三处接线 + vitest。
- [x] Commit: `feat(attribution): analyst signatures across work log, findings and morning brief`

### Task 10: "找专家"召唤统一（@agent 体验升级）

**Files:**
- Modify: `frontend/src/components/AgentMention.tsx`、`frontend/src/components/CommandPalette.tsx`

- [x] Step 1: AgentMention 下拉项升级：`[glyph] name_zh — mandate_zh`（现状只有名字；数据源 /api/agents 已全）+ 战绩样本足够时附命中率。
- [x] Step 2: CommandPalette 加 7 条命令「问技术面分析师…」→ /chat 预填 `@technical_agent `。
- [x] Commit: `feat(mention): expert picker shows mandate and track record`

---

## 明确不做（YAGNI 边界，防止"agent 化"跑偏）

- **不做自由多轮 agent 对话/AutoGPT 式自主循环**——挑战轮固定单轮、委托封顶 2 步，成本与时延可控。
- **不做拟人化人设**（名字/头像照片/口头禅）——glyph + 职责 + 战绩就是金融产品该有的"人格"。
- **不做 agent 间私聊记忆**——黑板 + prediction ledger 已覆盖需求；跨 agent 共享记忆等于回到全局状态泥潭。
- **不做用户自建 agent**——7 个专家是产品定义的一部分，不是平台功能。
- **不接 Longbridge，也不写死美股 ET 时段**——复用 FinSight 现有多市场行情与 market-hours 映射。
- **不引入 `pi-agent-core`**——submit 工具与纠错回路直接落在现有 LangGraph agent step。
- **不新增单用户 SQLite 档案库**——prediction/outcome/cost 全部使用带 user_id 的 PostgreSQL 表。
- **不换 `lightweight-charts`**——图表锚点与价位层由现有 ECharts `markPoint/markLine/markArea` 消费（具体落地见 09 A-4）。

---

## 10 完成门禁

- [x] `python -m pytest backend/tests tests/golden -x -q` 全绿（金样按各 Task 说明处理署名 diff）
- [x] Prediction 合同验收：long/short 每条可计分观点都有可信 anchor + entry/stop/T1，neutral 有包含 anchor 的 range；非法 submit 经服务端 issues 回路最多纠正一次，仍非法不入库
- [x] Outcome/归档验收：固定 OHLC 回放的 outcome 逐字节稳定；`prediction -> outcome -> run -> agent cost` 可在 PostgreSQL 按同一 user_id 完整追溯，跨用户查询为空
- [x] 端到端叙事验收（模拟用户视角走一遍；无 PR 视频托管环境，以 Chromium 截图与 JSON 证据留档）：
  1. 打开技术 tab → 看到「技术面分析师 驻场 · 近90天命中率 xx%」→ 洞察卡署名同一人
  2. 点「深入分析」→ AgentWorkLog 里看到技术面分析师工作 → 结果署名一致
  3. 生成一份投资报告 → 各章节署名 + lead 领衔结论 + 「风险质询」小节（风险分析师对某家观点的具体质疑）
  4. 一周后再问同一只票 → 回答里出现"我上次判断…现在…"的观点回访
  5. 点一条历史 prediction → ECharts 定位到 anchor，并显示 entry/stop/target；战绩 outcome 与同一段真实 K 线一致
  6. GET /api/agents → 7 个 profile 完整（身份/职责/战绩/成本），前后端无一处硬编码 agent 中文名
- [x] 关键反例检查：关闭 `DEBATE_GRAPH_ENABLED` 与 `FINSIGHT_AGENT_DELEGATION` 后主链路行为与今日一致（全部增强可独立降级）
- [x] 技术栈反例检查：依赖与 lockfile 无 Longbridge、`pi-agent-core`、`lightweight-charts`；仓库未新增 agent/prediction/outcome SQLite 文件

最终证据：真实 PostgreSQL 集成 `1 passed`，覆盖 prediction→outcome→run/cost、跨租户空查询和复合外键拒绝伪造租户；Linux 后端分片全量 `2119 passed / 9 skipped`，golden `12 passed`，debate/delegation 关闭反例 `56 passed`；生产 `/api/agents` 返回 7 个完整 profile。
