# ADR-2026-02-07｜Agent 选路与升级策略

> **状态**: Accepted  
> **日期**: 2026-02-07  
> **SSOT 对齐**: `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（11.10 / 11.11 / 11.12）

---

## 1. 背景

研报模式若默认全挂载所有 Agent，会带来三类问题：

1. 成本和延迟上限过高。
2. 输出冗余，卡片信息重复。
3. 不同请求对 Agent 的需求差异被忽略。

---

## 2. 决策

1. 采用 `CapabilityRegistry` 评分选路，而非固定全挂载。
2. 在 `policy_gate` 产出 `allowed_agents`，Planner 只能在白名单内生成 agent steps。
3. report 模式保留 required agents 兜底，再按分数补齐到预算上限。
4. 后续升级为“逐级升级”：先低成本步骤，证据不足再升级高成本 Agent。

---

## 3. 实现落点

- 评分与 required 规则：`backend/graph/capability_registry.py`
- 策略门：`backend/graph/nodes/policy_gate.py`
- 计划约束与注入：`backend/graph/nodes/planner.py`、`backend/graph/nodes/planner_stub.py`

---

## 4. 后果

### 正向

- 研报可读性提升（减少重复卡片）。
- 平均执行成本和时延可控。
- 新 Agent 上线只需注册能力模型，不必重写主链路。

### 代价

- 评分规则需要持续校准（避免偏向某些 Agent）。
- 必须通过回归测试保障“关键场景保底 Agent”不被误裁剪。

