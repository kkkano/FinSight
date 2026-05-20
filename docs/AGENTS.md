# docs 协作规则

本目录承载项目的长期架构记忆、运行手册、计划 spec、历史日志和设计资产。新增或移动文档时，优先让读者 30 秒内判断“当前该读什么、历史在哪里、计划是否仍有效”。

## 目录边界

- 根目录只保留当前有效的架构、运行、契约和产品规范文档。
- `plans/` 放尚未完成或仍可执行的计划、spec、todolist。
- `feature_logs/` 仅作历史兼容目录；新验证报告优先放 `reports/`，发布演练和收口证据放 `release_evidence/`，旧流水记录见 `archive/feature_logs/`。
- `Thinking/` 放 ADR、探索草稿、问题分析；默认保留，但不作为当前事实源。
- `archive/` 放过期计划、旧路线图、临时报表和被当前规范取代的文档。
- `design/`、`prototype/` 放视觉方案、原型和静态资产，不作为运行架构事实源。

## 修改规则

- 新增当前有效文档后，必须同步更新 `DOCS_INDEX.md`。
- 归档不删除：优先移动到 `archive/<yyyy-mm-topic>/`，并在该目录 `README.md` 记录原路径和归档原因。
- 不把密钥、真实 token、个人凭据写入文档。
- 面向人的说明使用中文；文件名可以使用英文，便于搜索和跨平台路径处理。
- 如果文档与代码冲突，以代码和测试为准，并在文档中标记需要校准的地方。

## 当前事实源

- 架构入口：`01_ARCHITECTURE.md`、`06a_LANGGRAPH_DESIGN_SPEC.md`
- 请求理解实现 spec：`plans/2026-05-03_request_understanding_task_graph_spec.md`
- 请求理解查询矩阵：`reports/2026-05-03_request_understanding_query_results.md`
- 当前聊天 UX 验收：`qa/chat-router-100-final100-current-state.md` / `.json`（`tests/eval/chat_router_100.json`，100/100 PASS）；旧 40-query 回归证据见 `qa/chat-ux-40-query-final40-post-context-binding.md`
- 当前聊天主路径：`backend/graph/runner.py` 中的 `build_initial_state -> reset_turn_state -> prepare_context -> chat_respond -> understand_request`
- 当前对话路由：`backend/graph/nodes/conversation_router.py`；URL/网页读取通过 planner/agent 工具 `fetch_url_content`
- 会话生命周期：`backend/api/conversation_router.py`、`backend/services/conversation_store.py` 与 `plans/2026-05-03_request_understanding_task_graph_spec.md`
- 停止生成：`backend/services/execution_service.py`、`backend/graph/cancellation.py`、`backend/graph/executor.py`
- 执行链路参考：`LANGGRAPH_FLOW.md`、`LANGGRAPH_PIPELINE_DEEP_DIVE.md`
- Agent/Tool：`AGENTS_GUIDE.md`
- 事件契约：`execution-event-contract.md`
- RAG：`05_RAG_ARCHITECTURE.md`、`08_RAG_ARCHITECTURE.md`
- 运维：`11_PRODUCTION_RUNBOOK.md`

## 过期文档判断

符合以下任一条件时，文档不应继续留在根目录作为当前事实源：

- 仍描述 `ConversationRouter` / `SchemaRouter` 作为主聊天入口。
- 把旧节点顺序当作目标架构，而不是历史/兼容 helper；当前主路径必须以 `prepare_context -> chat_respond(pure social only) -> understand_request` 为准。
- 是已完成阶段的 todolist、hotfix 报告、一次性测试报告。
- 与 `backend/graph/runner.py`、`backend/graph/state.py`、测试结果冲突。
