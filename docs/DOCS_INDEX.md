# FinSight 当前文档索引

更新时间：2026-07-14

本页只索引当前有效的事实文档。历史计划、阶段报告、QA 证据、ADR 和被替代说明统一位于 [`archive/`](archive/)；设计提案位于 [`design/`](design/)，两者都不作为运行时事实源。

## 建议阅读顺序

1. [`../README_CN.md`](../README_CN.md)：产品能力、快速启动、系统与部署拓扑。
2. [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md)：代码边界、数据边界和主运行时。
3. [`LANGGRAPH_FLOW.md`](LANGGRAPH_FLOW.md)：当前 LangGraph 节点与分支。
4. [`LANGGRAPH_PIPELINE_DEEP_DIVE.md`](LANGGRAPH_PIPELINE_DEEP_DIVE.md)：状态、规划、执行、证据与合成的实现细节。
5. [`AGENTS_GUIDE.md`](AGENTS_GUIDE.md)：7 个 Agent Profile 与公共质量合同。
6. [`05_RAG_ARCHITECTURE.md`](05_RAG_ARCHITECTURE.md)：PostgreSQL/pgvector RAG。
7. [`11_PRODUCTION_RUNBOOK.md`](11_PRODUCTION_RUNBOOK.md)：部署、验证、冒烟和回滚。

## 契约与专项规范

| 文档 | 作用 |
|---|---|
| [`06a_LANGGRAPH_DESIGN_SPEC.md`](06a_LANGGRAPH_DESIGN_SPEC.md) | 当前 LangGraph 设计约束与完成状态 |
| [`execution-event-contract.md`](execution-event-contract.md) | 后端事件、SSE 和前端消费边界 |
| [`REPORT_CHART_SPEC.md`](REPORT_CHART_SPEC.md) | 报告图表与 `chart_ref` 合同 |
| [`HALLUCINATION_MITIGATION.md`](HALLUCINATION_MITIGATION.md) | 证据、引用和降级治理 |
| [`rag-evaluation-guide.md`](rag-evaluation-guide.md) | RAG 质量评估方法与门禁 |
| [`12_PRODUCTION_QUALITY_REMEDIATION_SPEC.md`](12_PRODUCTION_QUALITY_REMEDIATION_SPEC.md) | 当前待实施的生产质量修复规范：代理隔离、LLM 韧性、请求/合成合同与前端收口 |
| [`reports/2026-05-03_request_understanding_query_results.md`](reports/2026-05-03_request_understanding_query_results.md) | 保留的请求理解评估报告 |

## 维护规则

- 代码和测试是事实裁决源；架构变化必须在同一变更中更新本索引和对应文档。
- 一次性计划、验证证据和已完成 spec 不继续堆在当前目录，应归档并记录原路径。
- 文档不得包含真实密钥、token、Cookie 或生产凭据。
- 不新增同主题的第二份“当前架构”；优先修改已有事实源。
