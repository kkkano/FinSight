# FinSight-audit 项目边界

## 当前架构

- `backend/agent_runtime/`：唯一研究运行时，主研究员与专业角色共用原生工具调用循环；工具信封、资料引用、预算、权限、计算与交付各有明确边界。
- `backend/api/execution_router.py`：唯一研究 SSE 入口，负责运行身份、追加要求、操作确认与续研；仅调用 `backend/agent_runtime`，不保留旧运行时选择开关。
- `backend/agent_runtime/registry.py`、`envelope.py`、`adapters/`：实际工具 schema、权限与统一结果信封；失败判定不扫描自然语言。
- `backend/agent_runtime/verifier.py`、`finalize.py`：只读核查、结构化 coverage、一次追加或保留版本的报告修订；已显示正文不被规则改写。
- `backend/agent_runtime/events.py`：正文、产物、review 块与 checkpoint 水位；终态和前端恢复遵循同一事件合同。
- `tests/agent_eval/reference/`：已退役图/Agent 的评测参考，排除在生产镜像外；manifest 中 27 个 protected_files 是冻结预测依赖，不属于删除范围。
- `backend/research/news_event_quality.py`：新闻时效、主体、出处和报道/线索合同；网关、执行、合成和前端必须保留其语义。
- `backend/services/research_run_store.py`：服务器权威消息、已提交 blocks/checkpoint、运行终态与幂等恢复；保存成功后才交付 `done`，旧快照不能覆盖最终回答。
- `backend/analysis_worker/`：可选独立计算 dispatcher/job；`finsight.py` 提供回撤、连续下跌、均线、统计和比较函数，开放代码不进入 Web 进程。
- `backend/rag/`：memory / working set / knowledge base 的摄取、检索与观测。
- `backend/rag/worker.py`：可选私网重型推理进程；默认词法检索，托管 API 与 `local-ml` 显式启用，API 不加载本地模型。
- `frontend/src/`：用户交互、状态和诊断界面；后端契约变化必须同步类型与测试。

## 修改规则

- 先确认请求属于原生研究、独立用户 Prediction 还是冻结 US20；旧图仅供历史评测，不恢复生产路由或隐藏后处理。
- 不恢复已迁移的 `*_stub.py` 或旧节点实现；需要兼容时使用薄适配层。
- 不把历史变更日志继续追加到本文件；历史说明已归档到 `docs/archive/2026-07-overhaul-closeout/superseded/agents-architecture-history.md`。
- 保留用户未提交改动，不执行无关格式化、批量重命名或顺手重构。
- 面向人的注释、文档和日志使用中文；代码标识符使用英文。

## 验证

- Python 改动先运行受影响的定向 pytest；跨层契约再运行对应集成测试。
- 前端改动先运行相关单测；涉及交互时再使用 Playwright 验证关键路径。
- 同一失败命令最多原样重试一次；失败后根据错误定位根因。
- 未经用户明确要求，不提交、推送或重置 Git。
