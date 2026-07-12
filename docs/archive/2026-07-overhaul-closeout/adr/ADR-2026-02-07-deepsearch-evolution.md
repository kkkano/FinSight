# ADR-2026-02-07｜DeepSearch 能力演进（外部方案吸收）

> **状态**: Accepted  
> **日期**: 2026-02-07  
> **参考**:  
> - `https://github.com/stay-leave/DeepSearchAcademic`  
> - `https://github.com/666ghj/BettaFish`  
> - `https://github.com/666ghj/DeepSearchAgent-Demo`

---

## 1. 背景

FinSight 现有深搜能力可用，但在多轮检索、证据冲突标注、引用一致性方面仍有提升空间。

---

## 2. 决策

1. 吸收外部方案“方法”，不复制其工程结构。
2. 保持 FinSight 的单入口编排（LangGraph）不变。
3. 采用四步演进：
   - 多轮检索（query expansion）
   - 轻量重排（rerank）
   - 证据冲突标注（consensus/conflict）
   - 引用一致性校验（answer-citation coverage）

---

## 3. 落地方式

1. 在 `deep_search_agent` 增加“多轮检索模板”与证据质量字段。
2. 在执行层补 rerank hook（不新开入口服务）。
3. 在评测集中增加 deepsearch hard cases（跨来源冲突、时间冲突）。
4. 在 CI 中纳入引用覆盖率门禁，防止“有答案无证据”。

---

## 4. 后果

### 正向

- 深搜结论更可解释、可复核。
- 与现有 PlanIR/Executor 架构兼容，改动可控。

### 代价

- 评测和标注工作量上升。
- 深搜链路延迟上升，需要与 budget 联动控制。

