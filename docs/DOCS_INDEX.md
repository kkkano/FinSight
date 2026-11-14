# FinSight 当前文档索引

更新：2026-11-13。当前规范已按原生运行时校准；模型为用户指定的 APIKL gpt-6.1-terra，完整评测、上线验收与发布状态集中在运行手册，历史数字不代表本次成绩。

本页区分当前规范、当前实施与历史证据。历史计划、QA、ADR 和被替代规范位于 archive；reports 保留原日期的实施/验收记录；design 保存视觉资料。历史发布、测试数量和数据快照不能替代当前源码或本次上线证据。

## 设计资料与本轮实施

- [自主研究与对话目标设计合同](../DESIGN.md)：Claude 七画板的视觉方向、真实状态、thinking 分层、模型准入与操作确认；实现状态以代码及下方验收记录为准。
- [设计画板快照与来源](design/2026-11-06_claude_agent_chat/README.md)：七画板、canvas索引与源文件SHA-256。原型数据仅作样式演示。
- [唯一 Agentic 实施计划](plans/2026-11-10_agent_runtime_agentic_rebuild.md)是本次任务指定的工作树计划；保留原始设计和 48 项验收文本，追加可验证实施进度；计划、默认开启和候选文件不能替代已验收/已发布证据。
- [评测入口](../tests/agent_eval/README.md)与[退役/冻结范围清单](../tests/agent_eval/reference/manifest.json)用于固定题集、历史对照及 27 个 protected_files 核对，排除在生产镜像之外。
- [2026-11-07 Agent 运行时实施与验收记录](reports/2026-11-07_agent_runtime_implementation.md)：保留后端8b/前端9c原发布、OAuth入口与当时计算容量快照，不代表后续修复全部已发布。
- [自然回答与隔离计算复验](reports/2026-11-07_natural_response_compute/README.md)：保存当时主应用8f/compute a0发布、真实8题与worker重放、公网及401边界；受保护生产会话canary未执行，不代表新运行时状态。
- [冻结的真实多会话 before](reports/2026-11-07_natural_response_compute/BEFORE.md)：42次模型调用、8个原样问题仅1个完整通过，独立于当前after。
- [封面、看板与战绩设计对照](reports/2026-11-07_page_design_alignment/PAGES_COMPARISON.md)：逐区块实现位置、亮暗/移动截图及真实数据边界。
- [对话、历史与单列右栏设计对照](reports/2026-11-07_chat_design_alignment/README.md)：68张布局截图和逐区块差异；布局fixtures不作为金融数据验收。
- [真实图表渲染验收](reports/2026-11-07_chat_design_alignment/REAL_CHARTS.md)：三例真实模型产物逐点/悬停核验，SOXX区间端点与前一期基准重绘；核心图表通过不代表候选全文可靠。
- [结果、过程与图标验收](reports/2026-11-07_chat_design_alignment/RESULT_PROCESS_ICONS.md)：三种前端fixture视口与真实case6 artifact数值核对分开记录；不冒充后端多会话验收。

- [贡献指南](../CONTRIBUTING.md)与[前端开发说明](../frontend/README.md)：当前环境、原生协议测试、状态拆分与构建入口。
- [本次文档审查](reports/2026-11-13_documentation_refresh/README.md)：当前规范清单、链接/UTF-8/Mermaid 检查和归档记录。
- [2026-11-13 文档归档](archive/2026-11-13_documentation_refresh/README.md)：旧贡献/前端/Token/历史研究图说明的原路径、替代入口及原因。

- [2026-11-13 CI E2E 收口](reports/2026-11-13_ci_e2e/README.md)：当前受控截图、真实图表原件与字节清单；旧日期截图保持原件，完整 CI 及线上结论分别记录。

## 建议阅读顺序

1. [`../README.md`](../README.md)：产品能力、快速启动、当前路由、系统与部署拓扑。
2. [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md)：代码边界、数据边界和主运行时。
3. [`AGENTS_GUIDE.md`](AGENTS_GUIDE.md)：默认主/专业角色、真实技能、私有思考、资料TTL与权限，以及独立预测边界。
4. [`execution-event-contract.md`](execution-event-contract.md)：answer.completed、只读 review、逐字 quote、追加/保留版本修订与 blocks/终态恢复。
5. [`05_RAG_ARCHITECTURE.md`](05_RAG_ARCHITECTURE.md)：按需知识工具、词法/托管API、可选私网worker、向量身份与真实迁移/回读证据。
6. [`LANGGRAPH_FLOW.md`](archive/2026-11-13_documentation_refresh/LANGGRAPH_FLOW.md)：六节点历史定位；不提供生产启用开关，不作为当前主链。
7. [`11_PRODUCTION_RUNBOOK.md`](11_PRODUCTION_RUNBOOK.md)：部署、验证、冒烟和回滚。

## 契约与专项规范

| 文档 | 作用 |
|---|---|
| [`execution-event-contract.md`](execution-event-contract.md) | 后端事件、质量/保存状态、消息 ID、持久运行恢复与前端消费边界 |
| [`REPORT_CHART_SPEC.md`](REPORT_CHART_SPEC.md) | 真实句柄图表/表格、报告核查、版本关系与历史格式展示 |
| [`HALLUCINATION_MITIGATION.md`](HALLUCINATION_MITIGATION.md) | 三层事实治理、只读核查、注错/误报评测与发布边界 |
| [`rag-evaluation-guide.md`](rag-evaluation-guide.md) | RAG 质量评估方法与门禁 |
| [`MODEL_SELECTION.md`](MODEL_SELECTION.md) | 登录用户的模型切换、凭据与研究上下文边界 |
| [`PREDICTION_TRACK_RECORD.md`](PREDICTION_TRACK_RECORD.md) | 固定 US20 公开预测账本、冻结口径、结算与独立告警 |

## 历史基座与验收记录

[2026-11-07 Agent runtime/设计收口归档](archive/2026-11-07_agent-runtime-design-closeout/README.md) 保存被现行规范替代的旧LangGraph深入说明与生产设计硬约束；默认研究规范集中在架构、Agent、执行事件和RAG文档，不将归档当作当前权限或模型循环规则。

[`archive/2026-10-03-foundation-refactor/README.md`](archive/2026-10-03-foundation-refactor/README.md) 收录本次计划、实施记录和脱敏发布验收。该归档保存当时统一请求/证据/研究结果、质量门禁和独立 RAG 的实现；真实 PostgreSQL、当时 canary 与 worker 推理的完成范围以原证据为准，当前主链以本索引上方规范为准。

文档更新不代表部署或外部验收通过。执行方记录本次发布 SHA 和各项验证状态，未完成项明确待补；原始验收文本保留，实施进度与发布身份在计划追加节和运行手册中更新。

初始基座发布版本为 `94a0171a`；后续聊天交付修复为 `ec3a47db`，2026-10-04 请求/证据/完整性修复已发布 `cf700d2d`，见 [本次发布与真实账号交付](archive/2026-10-04-contract-quality-repair/RELEASE.md)。生产 schema 为 `0006`，就绪检查通过；语义 RAG 因内存限制使用明确的词法降级。早期发布历史和待补的 24 小时观察见 [发布记录](archive/2026-10-03-foundation-refactor/RELEASE.md)。

[2026-10-04 真实账号与独立新题验收](archive/2026-10-04-independent-acceptance/ACCEPTANCE.md) 已验证一条报价聊天及一份报告的正文、刷新、会话重开与报告归档。12 道人工策划边界题的首次结果为：意图完整约束 2/12、证据覆盖 10/29、完整回答 0/12。交付通过不代表研究质量通过；该小样本不能外推全站准确率。冻结口径、首次原文、逐维评分和下一步动作一并归档。

[请求、证据与完整性修复](archive/2026-10-04-contract-quality-repair/README.md) 记录后续定点修复、原题组合回归与第二批冻结问题。原题回归不能替代独立成绩；新题未满足的子任务、来源和计算口径继续列为缺口，具体分数及最终发布状态以该归档为准。

历史实时新闻/事件质量设计与 [AIHOT 固定版本参考](archive/2026-10-03-foundation-refactor/NEWS_EVENT_QUALITY.md) 保存在归档中；当前数据规范与核查边界见上方事实治理和 Agent 指南。

已完成的 2026-07 生产质量修复 Spec 与一次性发布证据已归档到 [`archive/2026-07-production-quality-remediation/`](archive/2026-07-production-quality-remediation/)，不再作为当前规范入口。

2026-01 的 Schema Router、Forum/Supervisor 与 Agent 优化草案已归档到 [`archive/2026-09-15-doc-reconcile/`](archive/2026-09-15-doc-reconcile/)。这些文件只保留历史决策背景，不代表六节点主图或当前产品路线。

## 维护规则

- 代码和测试是事实裁决源；架构变化必须在同一变更中更新本索引和对应文档。
- 一次性计划、验证证据和已完成 spec 不继续堆在当前目录，应归档并记录原路径。
- 文档不得包含真实密钥、token、Cookie 或生产凭据。
- 不新增同主题的第二份“当前架构”；优先修改已有事实源。
