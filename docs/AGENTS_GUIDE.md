# FinSight AI 角色与 Collector 指南

更新时间：2026-07-16

## 1. 用户可感知角色

系统只有两个业务 LLM 角色：

| 角色 | 输入 | 输出 | 调用预算 |
|---|---|---|---|
| `PredictionAnalyst` | trusted Kline、服务端指标、新闻摘要、已有 Prediction | 严格 Prediction JSON | 一个逻辑任务，最多一次纠错 |
| `ResearchAnalyst` | 已验证的结构化 evidence | Chat 答案或报告草稿 | 普通研究最多一次；长报告可追加一次 verifier |

PredictionAnalyst 的 anchor 由服务端覆盖，方向、概率、止损、目标和 RR 由服务端校验。ResearchAnalyst 不直接取数，也不能引用 evidence pool 外的确定性数字。

## 2. 内部 Collector

`backend/agents/profiles.py` 描述 Price、News、Fundamental、Technical、Macro、Risk 与 Deep Search 的工具归属和展示元数据。这些 profile 是内部 evidence collector，不是用户选择的独立人格，也不代表七次 LLM 调用。

`backend/graph/adapters/collector_adapter.py` 使用 `llm=None` 构造 collector；`BaseFinancialAgent` 仅为兼容既有构造签名接收该参数并立即丢弃。collector 的职责只有：

- 调用许可范围内的工具；
- 规范化来源、时间、质量和失败语义；
- 生成 `AgentOutput`、evidence 与候选 Claim；
- 把工具错误作为 diagnostics 返回。

collector 不执行 LLM analysis、reflection、debate 或隐式 Prediction。

## 3. 公共合同

- 工具失败进入 diagnostics，不生成假 evidence。
- 每条 Claim 必须引用 evidence id。
- provider、`as_of`、freshness、quality 必须跨层保留。
- `quality != trusted` 的 Kline 不能进入 Prediction 或 Outcome。
- collector 只按 capability registry、policy 和 PlanIR 执行。
- 新 collector 必须复用公共 TaskOutcome、Claim、引用和错误合同，不得自建协议。
- 用户可见角色、collector 名称和 LLM usage attribution 必须区分，避免把工具采集误报成模型判断。

## 4. 修改检查

调整 collector 时至少同步：

1. `backend/agents/profiles.py` 的职责与工具集合；
2. capability registry、policy allowlist 和规则 planner；
3. collector adapter 的结构化输出与 evidence gate；
4. 定向单测和至少一个跨层执行测试；
5. 本指南及受影响的观测字段。

只有当输出合同、失败语义和调用预算与两个现有角色都根本不同，才讨论新增业务 LLM 角色。这属于架构变更，必须同步 usage 归因、评测、预算和生产门禁。
