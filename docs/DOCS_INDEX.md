# FinSight 当前文档索引

更新时间：2026-10-04

本页只索引当前有效的事实文档。历史计划、阶段报告、QA 证据、ADR 和被替代说明统一位于 [`archive/`](archive/)；设计提案位于 [`design/`](design/)，两者都不作为运行时事实源。

## 建议阅读顺序

1. [`../README.md`](../README.md)：产品能力、快速启动、当前路由、系统与部署拓扑。
2. [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md)：代码边界、数据边界和主运行时。
3. [`LANGGRAPH_FLOW.md`](LANGGRAPH_FLOW.md)：当前 LangGraph 节点与分支。
4. [`LANGGRAPH_PIPELINE_DEEP_DIVE.md`](LANGGRAPH_PIPELINE_DEEP_DIVE.md)：统一请求编译、逐任务覆盖、类型化 DAG、共享取数、研究结果与保存恢复。
5. [`AGENTS_GUIDE.md`](AGENTS_GUIDE.md)：两个业务 LLM 角色、内部 Collector 与公共质量合同。
6. [`05_RAG_ARCHITECTURE.md`](05_RAG_ARCHITECTURE.md)：PostgreSQL/pgvector、私网推理 worker、向量身份与词法降级。
7. [`11_PRODUCTION_RUNBOOK.md`](11_PRODUCTION_RUNBOOK.md)：部署、验证、冒烟和回滚。

## 契约与专项规范

| 文档 | 作用 |
|---|---|
| [`06a_LANGGRAPH_DESIGN_SPEC.md`](06a_LANGGRAPH_DESIGN_SPEC.md) | 当前六节点 LangGraph 设计约束与变更门禁 |
| [`execution-event-contract.md`](execution-event-contract.md) | 后端事件、质量/保存状态、消息 ID、持久运行恢复与前端消费边界 |
| [`REPORT_CHART_SPEC.md`](REPORT_CHART_SPEC.md) | 报告图表与 `chart_ref` 合同 |
| [`HALLUCINATION_MITIGATION.md`](HALLUCINATION_MITIGATION.md) | 证据、引用和降级治理 |
| [`rag-evaluation-guide.md`](rag-evaluation-guide.md) | RAG 质量评估方法与门禁 |
| [`MODEL_SELECTION.md`](MODEL_SELECTION.md) | 登录用户的模型切换、凭据与研究上下文边界 |
| [`PREDICTION_TRACK_RECORD.md`](PREDICTION_TRACK_RECORD.md) | 固定 US20 公开预测账本、冻结口径、结算与独立告警 |

## 本次基座重构

[`archive/2026-10-03-foundation-refactor/README.md`](archive/2026-10-03-foundation-refactor/README.md) 收录本次计划、实施记录和脱敏发布验收。当前规范已反映统一请求/证据/研究结果、单调质量门禁、服务器终态和独立 RAG 推理；是否已经完成真实 PostgreSQL、线上 canary 与真实 worker 推理，以该归档的实际证据为准。

文档更新不代表部署或外部验收通过。主代理在执行完成后同步计划勾选、发布 SHA 和各项验证状态，未完成项保持明确待补。

初始基座发布版本为 `94a0171a`；后续聊天交付修复为 `ec3a47db`，2026-10-04 请求/证据/完整性修复已发布 `cf700d2d`，见 [本次发布与真实账号交付](archive/2026-10-04-contract-quality-repair/RELEASE.md)。生产 schema 为 `0006`，就绪检查通过；语义 RAG 因内存限制使用明确的词法降级。早期发布历史和待补的 24 小时观察见 [发布记录](archive/2026-10-03-foundation-refactor/RELEASE.md)。

[2026-10-04 真实账号与独立新题验收](archive/2026-10-04-independent-acceptance/ACCEPTANCE.md) 已验证一条报价聊天及一份报告的正文、刷新、会话重开与报告归档。12 道人工策划边界题的首次结果为：意图完整约束 2/12、证据覆盖 10/29、完整回答 0/12。交付通过不代表研究质量通过；该小样本不能外推全站准确率。冻结口径、首次原文、逐维评分和下一步动作一并归档。

[请求、证据与完整性修复](archive/2026-10-04-contract-quality-repair/README.md) 记录后续定点修复、原题组合回归与第二批冻结问题。原题回归不能替代独立成绩；新题未满足的子任务、来源和计算口径继续列为缺口，具体分数及最终发布状态以该归档为准。

本轮新增的实时新闻/事件质量合同参见 [`HALLUCINATION_MITIGATION.md`](HALLUCINATION_MITIGATION.md) 和 [`AGENTS_GUIDE.md`](AGENTS_GUIDE.md)；[AIHOT 固定版本参考与取舍](archive/2026-10-03-foundation-refactor/NEWS_EVENT_QUALITY.md) 保存在归档中。

已完成的 2026-07 生产质量修复 Spec 与一次性发布证据已归档到 [`archive/2026-07-production-quality-remediation/`](archive/2026-07-production-quality-remediation/)，不再作为当前规范入口。

2026-01 的 Schema Router、Forum/Supervisor 与 Agent 优化草案已归档到 [`archive/2026-09-15-doc-reconcile/`](archive/2026-09-15-doc-reconcile/)。这些文件只保留历史决策背景，不代表六节点主图或当前产品路线。

## 维护规则

- 代码和测试是事实裁决源；架构变化必须在同一变更中更新本索引和对应文档。
- 一次性计划、验证证据和已完成 spec 不继续堆在当前目录，应归档并记录原路径。
- 文档不得包含真实密钥、token、Cookie 或生产凭据。
- 不新增同主题的第二份“当前架构”；优先修改已有事实源。
