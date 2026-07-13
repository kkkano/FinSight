# LangGraph 生产设计规范

状态：当前实现已完成并投入生产　更新时间：2026-07-13

本规范描述现有不变量，不再作为待办流水账。历史 overhaul 计划、逐任务勾选和验证证据已完整归档到 [`archive/2026-07-overhaul-closeout/`](archive/2026-07-overhaul-closeout/)。

## 完成状态

- [x] 单一 LangGraph 主入口与明确分支。
- [x] 结构化请求理解、任务合同和 context binding。
- [x] planning、policy、execution、synthesis、rendering 分层。
- [x] PlanIR 校验、规则回退和确认门。
- [x] 工具诊断与证据池隔离。
- [x] 7 个统一 Agent Profile 和公共质量合同。
- [x] research debate、引用与幻觉治理。
- [x] PostgreSQL checkpointer 与 pgvector RAG。
- [x] SSE 执行事件、前端观测与停止生成。
- [x] 多用户作用域、成本约束和生产部署门禁。
- [x] checkpoint 优先的多轮历史恢复、匿名 thread 长期记忆隔离与已验证 ticker 焦点。
- [x] 会话 LLM 独立超时、单端点瞬态连接重试、多端点轮换和前后端显式降级契约。
- [x] IntentFrame、DAG executor、AgentBrief 与 evidence bus 默认走当前生产路径，保留显式 `off` 回滚。
- [x] 价格语义图只消费真实行情并按价格单位渲染，不把收益率或模型数组伪装成金额。
- [x] 估值比较降级回答逐标的展示实际倍数；证据不足时明确拒绝排序，不用方法模板冒充结论。
- [x] 跨标的 compare 合同优先于通用 task 分节，避免拆成多份单股模板而丢失横向结论。

## 强制设计约束

1. `backend/graph/runner.py` 是图节点/边事实源。
2. `understand_request` 之后只传结构化合同；下游不得重复按 query 关键词猜模式。
3. 规划只能选择能力注册表允许的工具/Agent，LLM 输出必须验证。
4. 规则回退属于 `backend/graph/planning/`，不得恢复 `planner_stub.py`。
5. 执行属于 `backend/graph/execution/`，不得恢复 `execute_plan_stub.py`。
6. failed/timeout/empty/refused 结果进入 diagnostics，不进入 evidence pool。
7. synthesis 和 renderer 不调用工具、不制造未取证数字。
8. 事件、证据、记忆和业务数据必须遵守 user/thread/run scope。
9. 后端合同变更必须同步前端类型、消费逻辑和测试。
10. 规格、README、Mermaid 与代码必须在同一变更中同步。
11. 客户端历史只可在当前 thread 的 checkpoint 无消息时恢复，不得覆盖或重复 checkpoint 历史。
12. LLM 回退必须通过 `degraded` 事件与终态字段披露；前端必须显示降级状态。
13. 单端点的连接中断、超时和临时 5xx 必须复用当前端点重试；认证/配置错误不得在同一端点盲目重试。
14. 比较型 renderer 必须回答比较维度；“采用了什么证据/方法”不构成比较结论。
15. 价格图标题、单位和数值语义必须一致；价格语义不得使用模型生成时间序列。
16. `render_intent.shape=compare` 且要求逐标的证据时，必须先生成整体比较，再考虑通用 task 分节。
17. LLM intent pipeline 生成的 `intent_contract(s)` / `request_frame(s)` 必须投影到顶层 GraphState，不得只留在 task params。

## 输出与证据策略

| 回答形态 | 行为 |
|---|---|
| 自然对话/直答 | 不强制外部取证；明确区分通用解释与实时事实 |
| source-grounded | 必须引用可用来源，或明确披露无法获取 |
| investment report | 使用完整报告结构、证据覆盖和限制披露 |
| alert/action | 独立分支；高影响操作按 confirmation policy 暂停 |

## 完成定义

任何后续改动只有在以下项目全部满足时才算完成：

- [x] 代码边界与上述约束一致。
- [x] 定向测试通过，跨层变化有集成测试。
- [x] 前端 schema/store/交互已同步（如受影响）。
- [x] 当前文档与 Mermaid 已同步。
- [x] 不含密钥、临时调试代码或未解释的兼容分支。
