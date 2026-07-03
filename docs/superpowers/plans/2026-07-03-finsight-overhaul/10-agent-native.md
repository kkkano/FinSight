# 10 Agent 原生化（Agent-Native）Implementation Plan

> **For agentic workers:** 按 Task 顺序执行，每个 Task 一次 commit。标注【盘点】的先跑盘点步骤再按分支执行。本文档与 WP2（编排力学）互补：WP2 让 agent **能**协作，本文档让 agent **像一个团队**并让用户**感知到**。

**基线 commit:** `4a1c055`
**Goal:** 把"7 个智能体"从聊天管线里的匿名执行单元，提升为产品的一等公民：有组织（分工/质询/委托）、有身份（档案/记忆/战绩）、有存在感（tab 驻场、署名、随处可召唤）。

**Architecture:** 三层递进——组织学（后端协作协议，Part 1）→ 身份系统（档案/记忆/战绩，Part 2）→ 感知层（评分器合一、驻场、署名，Part 3）。Part 1 依赖 WP2 的 DAG 执行器与证据黑板；Part 2/3 可与 WP2 并行。

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

- [ ] Step 1: TDD——7 个 profile 完整性断言（key 集合 == REPORT_AGENT_CANDIDATES；scorer_key 与 `backend/dashboard/insights_scorer.py` 的 score_* 函数名集合互相覆盖；dashboard_tabs 与 `agent_bridge._TAB_AGENTS` 一致性断言）。
- [ ] Step 2: 实现 profiles.py；`agents_router` 的 `_AGENT_DISPLAY_META` 删除、改由 profiles 生成（对外 JSON 结构不变，加 `glyph/color_token/mandate` 字段）。
- [ ] Step 3: 启动一致性断言（WP3 T8 的模式）：profiles ↔ capability_registry ↔ agent_bridge 三方 key 对齐。
- [ ] Commit: `feat(agents): single AgentProfile registry — identity, mandate, glyph, scorer & tab bindings`

### Task 2: Lead/Support 结构 + 报告署名

**Files:**
- Modify: `backend/graph/nodes/planner_stub.py`（或 WP3 后的 `planning/rule_planner.py`）：agent step 的 inputs 增加 `"role": "lead" | "support"`（由 `lead_agent_for_operation(task.operation)` 决定；lead 不在选中名单时名单头部者为 lead）
- Modify: `backend/graph/report_builder.py`（或 WP3 后的 `report/` 包）：报告各 agent 小节标题带署名 `### 技术面 · 技术面分析师`；结论段由 lead 的 summary 领衔
- Modify: `backend/graph/nodes/chat_renderer.py`：`_agent_summary` 类渲染同样带 `profile(name).name_zh` 署名
- Test: `backend/tests/test_lead_agent_attribution.py`（构造两 agent 输出的 state → 断言报告 markdown 含署名与 lead 领衔顺序）

- [ ] Step 1: TDD → 实现 → 金样零 diff 确认（署名属于渲染文本变化，金样切片不含 markdown 正文则零 diff；若含，重录并在 commit 说明）。
- [ ] Commit: `feat(report): lead/support roles and analyst attribution in reports and chat summaries`

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

- [ ] Step 1: TDD（mock LLM 返回两条质询 → 断言 artifacts 结构与报告小节渲染；LLM 失败 → 报告正常无小节）。
- [ ] Step 2: 实现（`build_debate_artifact` 改造为上述协议；prompt 写进 `backend/prompts/` 现有目录，要求输出 JSON、引用具体数字、不允许空泛质疑）。
- [ ] Step 3: `.env.server.example` 更新 `DEBATE_GRAPH_ENABLED=true` 默认与说明。
- [ ] Commit: `feat(debate): risk-agent challenge round produces attributed structured objections in reports`

### Task 4: 委托机制——agent 可请求补证据（受控版）

**Files:**
- Modify: `backend/agents/base_agent.py`（AgentOutput 增加 `requests: list[dict]` 字段，反思循环允许产出 `{"type": "delegate", "evidence": "peer_tickers", "reason": …}`）
- Modify: `backend/graph/dag_executor.py`（WP2 产物）：agent step 完成后若 output.requests 非空且 `FINSIGHT_AGENT_DELEGATION=on` → 查 `DELEGATION_CATALOG` 追加**最多 1 个**动态 tool step（depends_on 空，产出写黑板供后续 agent 与 synthesize 读取）
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

- [ ] Step 1: TDD（agent 输出 requests → executor 追加白名单内 step 且全局不超 2 个；白名单外忽略并记 trace）。
- [ ] Step 2: 实现（flag 默认 off；executor 侧改动 ≤40 行——只是"读 requests → 查表 → append step"，DAG 调度器天然支持动态加节点则直接加，否则在组间隙插入）。
- [ ] Commit: `feat(agents): bounded delegation — agents may request whitelisted supplementary evidence steps`

---

## Part 2: 身份系统——记忆与战绩

### Task 5: Agent 观点档案（stance ledger）

**Files:**
- Create: `backend/services/stance_store.py`、`backend/tests/test_stance_store.py`
- Modify: `backend/graph/report_builder.py`（报告落库时同步写观点）、`backend/graph/adapters/agent_adapter.py`（AgentBrief.context_digest 注入历史观点）

**存储（SQLite，模式对齐 portfolio_store；WP5 后自带 user_id）:**

```sql
CREATE TABLE IF NOT EXISTS agent_stances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT NOT NULL,            -- "technical_agent"
  ticker TEXT NOT NULL,
  stance TEXT NOT NULL,           -- bullish | bearish | neutral
  confidence REAL,
  thesis TEXT NOT NULL,           -- ≤200字 观点摘要
  price_at_stance REAL,           -- 表态时价格（评估战绩用）
  report_id TEXT,
  created_at TEXT NOT NULL,
  user_id TEXT NOT NULL DEFAULT 'public'
);
CREATE INDEX IF NOT EXISTS idx_stances_agent_ticker ON agent_stances(agent, ticker, created_at);
```

**接口:**

```python
def record_stance(*, agent: str, ticker: str, stance: str, confidence: float | None,
                  thesis: str, price_at_stance: float | None, report_id: str | None,
                  user_id: str = "public") -> None
def latest_stances(*, ticker: str, limit_per_agent: int = 1, user_id: str = "public") -> list[dict]
def stance_history(*, agent: str, ticker: str, limit: int = 5, user_id: str = "public") -> list[dict]
```

**提取来源:** 报告构建时各 agent 的 summary 已含方向性判断——`grep -n "stance\|bullish\|看多\|看空" backend/graph/report_builder.py backend/graph/nodes/synthesize.py` 找现有 stance 字段（架构报告确认 report 有 stance 概念）；若 agent 级 stance 不存在，则用确定性规则从 summary 提取（关键词表：看多/买入/bullish→bullish 等），提取不出记 neutral。

- [ ] Step 1: TDD（record→latest 读回；同 agent 同 ticker 多条按时间取最新；隔离 user_id）。
- [ ] Step 2: 实现 store + report_builder 落库钩子（investment_report 完成时逐 agent 写一条）。
- [ ] Step 3: 回忆注入——agent_adapter 构造 AgentBrief 时（WP2 T6 产物）：`stance_history(agent, ticker, limit=1)` 非空则在 context_digest 前追加一行 `你上次({date})对{ticker}的判断: {stance}({thesis前60字})，当时价格 {price}，现价 {now}`。**这一行就是"上次说超买，现在回调了"的来源**——agent 的 LLM 分析自然会呼应它。
- [ ] Commit: `feat(agents): stance ledger — agents remember and revisit their own prior calls`

### Task 6: 战绩追踪（事后验证，纯确定性）

**Files:**
- Create: `backend/services/stance_scoreboard.py`、`backend/tests/test_stance_scoreboard.py`
- Modify: `backend/api/agents_router.py`（GET /api/agents 响应附带战绩摘要）
- Modify: 调度器装配（`grep -n "start_interval_scheduler" backend/api/main.py`）加一个日更任务

**规则（写死，不搞花活）:**

```
每日一次: 对 30 天内的 bullish/bearish stance，取现价与 price_at_stance 比较:
  bullish 且涨幅 > +3% → hit；bearish 且跌幅 < -3% → hit；反向越阈 → miss；±3% 内且不满 14 天 → pending
agent 战绩 = 近 90 天 hit / (hit + miss)，样本 < 5 时显示"样本不足"而非百分比。
存储: agent_stances 加列 outcome TEXT (pending|hit|miss)、evaluated_at TEXT（ensure_column 幂等迁移）。
```

- [ ] Step 1: TDD（构造已知价格路径 → 断言 hit/miss/pending 三态；样本不足逻辑）。
- [ ] Step 2: 实现评估函数 + 日更调度（价格取现有 `fetch_price_snapshot` 通道，失败跳过当日）；agents_router 响应加 `{"track_record": {"window_days": 90, "hits": 7, "misses": 3, "hit_rate": 0.7}}`。
- [ ] Commit: `feat(agents): deterministic track record — daily outcome evaluation of past stances`

---

## Part 3: 感知层——让用户看见团队

### Task 7: 评分器与 agent 人格合一（"两套系统"的根治）

**Files:**
- Modify: `backend/dashboard/insights_prompts.py`、`backend/dashboard/insights_engine.py`
- Modify: `frontend/src/components/dashboard/tabs/shared/AiInsightCard.tsx`

**决定:** 不重写评分器（确定性打分逻辑保留），只做**人格归属**：
- 后端：`insights_engine.generate` 的响应每个洞察卡附 `analyst: {key, name_zh, glyph, color_token, mandate_zh}`（经 `profile_for_scorer(scorer_key)` 查 Task 1 注册表）；`insights_prompts.py` 各 tab 的 system prompt 开头统一改为 `你是{name_zh}，职责是{mandate_zh}。`——**与 agent 深挖时的 persona 同源**，一个"技术面分析师"只有一个人格。
- 前端：AiInsightCard 头部渲染 `[glyph] {name_zh}` 署名（glyph 用 08 规范的 Tag 样式 + color_token 上色）；卡底按钮文案从"深挖"改为 `请{short_zh}分析师深入分析 →`（点击走既有 useDashboardDeepDive，行为不变）。

- [ ] Step 1: 后端 TDD（insights 响应含 analyst 字段；prompt 含 name_zh——mock 断言）。
- [ ] Step 2: 前端接字段 + 文案（vitest：卡片渲染署名）。
- [ ] Step 3: 验收：技术 tab 的洞察卡和深挖结果都署名"技术面分析师"——用户眼里它们终于是同一个人。
- [ ] Commit: `feat(dashboard): insight cards and deep-dives share one analyst persona per domain`

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

- [ ] Step 1: 实现 + vitest（渲染 profile 与两按钮回调）。
- [ ] Step 2: 五 tab 挂入（overview 显示 lead=综合，其余按 `profile.dashboard_tabs` 反查首个驻场 agent）。
- [ ] Commit: `feat(dashboard): resident analyst bar on every tab — the team is visible where users live`

### Task 9: 全链路署名清扫

**Files:**
- Modify: `frontend/src/components/execution/AgentWorkLog.tsx`（08 T5 产物）：agent 名与 glyph/color_token 经 /api/agents profile 渲染（删除前端本地 AGENT_LABELS 硬编码，08 T3 引入的 `src/config/agentLabels.ts` 改为从 API 缓存生成）
- Modify: `frontend/src/components/workbench/FindingCard.tsx`：监控发现卡片标注来源 `由{name_zh}规则发现`（monitor_engine 的 finding 数据带上 agent/规则域字段——`grep -n "source\|rule" backend/services/monitor_engine.py` 对齐；若 finding 无 agent 概念则标注规则名，不硬凑）
- Modify: 晨报 `MorningBriefCard`：要点若来自某 agent 产出（morning_brief 后端组装时已知），附 short_zh chip

- [ ] Step 1【盘点】: monitor/morning_brief 数据结构里 agent 归属字段是否存在，写 notes；不存在的仅做规则名标注，不改后端。
- [ ] Step 2: 三处接线 + vitest。
- [ ] Commit: `feat(attribution): analyst signatures across work log, findings and morning brief`

### Task 10: "找专家"召唤统一（@agent 体验升级）

**Files:**
- Modify: `frontend/src/components/AgentMention.tsx`、`frontend/src/components/CommandPalette.tsx`

- [ ] Step 1: AgentMention 下拉项升级：`[glyph] name_zh — mandate_zh`（现状只有名字；数据源 /api/agents 已全）+ 战绩样本足够时附命中率。
- [ ] Step 2: CommandPalette 加 7 条命令「问技术面分析师…」→ /chat 预填 `@technical_agent `。
- [ ] Commit: `feat(mention): expert picker shows mandate and track record`

---

## 明确不做（YAGNI 边界，防止"agent 化"跑偏）

- **不做自由多轮 agent 对话/AutoGPT 式自主循环**——挑战轮固定单轮、委托封顶 2 步，成本与时延可控。
- **不做拟人化人设**（名字/头像照片/口头禅）——glyph + 职责 + 战绩就是金融产品该有的"人格"。
- **不做 agent 间私聊记忆**——黑板 + stance ledger 已覆盖需求；跨 agent 共享记忆等于回到全局状态泥潭。
- **不做用户自建 agent**——7 个专家是产品定义的一部分，不是平台功能。

---

## 10 完成门禁

- [ ] `python -m pytest backend/tests tests/golden -x -q` 全绿（金样按各 Task 说明处理署名 diff）
- [ ] 端到端叙事验收（模拟用户视角走一遍，录屏）：
  1. 打开技术 tab → 看到「技术面分析师 驻场 · 近90天命中率 xx%」→ 洞察卡署名同一人
  2. 点「深入分析」→ AgentWorkLog 里看到技术面分析师工作 → 结果署名一致
  3. 生成一份投资报告 → 各章节署名 + lead 领衔结论 + 「风险质询」小节（风险分析师对某家观点的具体质疑）
  4. 一周后再问同一只票 → 回答里出现"我上次判断…现在…"的观点回访
  5. GET /api/agents → 7 个 profile 完整（身份/职责/战绩），前后端无一处硬编码 agent 中文名
- [ ] 关键反例检查：关闭 `DEBATE_GRAPH_ENABLED` 与 `FINSIGHT_AGENT_DELEGATION` 后主链路行为与今日一致（全部增强可独立降级）
