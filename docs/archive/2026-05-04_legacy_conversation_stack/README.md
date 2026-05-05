# 旧 ConversationAgent 栈归档

归档时间：2026-05-04

## 原路径

- `backend/conversation/agent.py`
- `backend/conversation/router.py`
- `backend/conversation/schema_router.py`
- `backend/handlers/chat_handler.py`
- `backend/handlers/followup_handler.py`
- 相关 legacy 测试：`backend/tests/test_router_*`、`backend/tests/test_chat_*supervisor.py`、`tests/unit/test_schema_router.py`、`tests/regression/test_architecture_refactor.py` 等

## 归档原因

当前用户聊天主路径已经统一到 LangGraph：

`backend/api/chat_router.py -> backend.services.execution_service.run_graph_pipeline -> backend.graph.runner -> backend.graph.nodes.understand_request`

旧栈仍包含 `FOLLOWUP`、`followup_type` 和关键词型 `ConversationRouter` / `SchemaToolRouter`，会让后续维护者误以为系统有两套对话大脑。它不再参与 `/chat/supervisor` 或 `/chat/supervisor/stream` 的生产路径，因此从运行包导出和测试集合中移除。

## 当前替代

- 会话上下文：`backend/conversation/context.py` 仍保留并被 API session context 使用。
- 上下文路由：`backend/graph/nodes/conversation_router.py`
- 请求理解：`backend/graph/nodes/understand_request.py`
- 聊天渲染：`backend/graph/nodes/chat_renderer.py`

不要把本目录文件重新引回生产路径；如需恢复某个能力，应迁移到 LangGraph 节点和统一 context binding schema。
