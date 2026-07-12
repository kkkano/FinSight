# docs 协作规则

本目录只在根层保留当前有效的架构、契约、评估和运维文档。

## 目录边界

- `archive/`：已完成计划、历史 QA/发布证据、ADR、旧说明和源笔记；不作为当前事实源。
- `design/`：设计资产和方案说明；不作为运行架构事实源。
- `reports/`：仍有参考价值的评估报告，不承担架构规范职责。

## 当前事实源

- 架构：`01_ARCHITECTURE.md`
- LangGraph：`LANGGRAPH_FLOW.md`、`LANGGRAPH_PIPELINE_DEEP_DIVE.md`、`06a_LANGGRAPH_DESIGN_SPEC.md`
- Agent：`AGENTS_GUIDE.md`
- RAG：`05_RAG_ARCHITECTURE.md`、`rag-evaluation-guide.md`
- 契约：`execution-event-contract.md`、`REPORT_CHART_SPEC.md`、`HALLUCINATION_MITIGATION.md`
- 运维：`11_PRODUCTION_RUNBOOK.md`
- 总索引：`DOCS_INDEX.md`

## 修改规则

- 代码和测试优先；冲突时先核实实现，再在同一变更中校准文档。
- 不新建同主题的第二份当前规范；直接更新事实源。
- 已完成计划和一次性证据归档到带 README 的日期批次。
- README、Mermaid、规格勾选和代码必须同步。
- 不记录真实密钥、token、Cookie、服务器私密配置或个人信息。
- 面向人的文档使用中文；代码标识符保持英文。
