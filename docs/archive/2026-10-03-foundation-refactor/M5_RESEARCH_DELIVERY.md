# M5 研究运行与回复持久化实施记录

本文件记录 2026-10-03 基座重构的迁移与验收证据；当前 API 规范以 `docs/execution-event-contract.md` 为准。

## 变更目的

此前聊天最终正文由浏览器整份消息快照保存。服务器执行完成、浏览器刷新、旧标签页快照晚到这三个事件没有共同事务边界，可能产生只剩提问或完整答案被旧正文覆盖的会话。

新增的 `research_runs` 持有运行终态，`conversation_messages` 持有服务器权威消息。会话 JSON 保留为兼容视图，新增 `conversation_threads.version`。所有已有消息和报告均保留，不做历史回填或改写。

## 写入与恢复

1. 登录用户通过 `/api/execute` 发起请求。模型预检通过后，服务器先在短事务内保存运行、用户消息和包含 `run_id` 的助手占位，再启动研究。
2. 请求可携带 `client_user_message_id`、`client_assistant_message_id`。相同 owner/run 重复提交仅恢复原运行；不同查询不能重用运行 ID。
3. 终态保存先锁会话、再锁运行，更新权威助手消息、兼容快照及运行终态后提交。提交返回后才发送 `done` 和完成阶段事件。外部模型/行情调用不占用此事务。
4. 明确重新生成使用新运行和助手消息 ID，复用用户消息 ID。运行审计保留所有结果；兼容会话按 `reply_to` 和数据库生成的 `run_sequence` 展示最新回复，迟到旧运行不能覆盖新回复。
5. 旧客户端的整份快照只能合并补充消息，服务器权威正文优先。携带过期 `expected_version` 的客户端收到 HTTP 409 `conversation_version_conflict`，应读回最新会话。
6. `/api/execute/runs/{run_id}` 返回 owner 隔离的运行状态与结果。SSE 内存缓冲过期或进程重启后，`/events` 回放持久化终态，标注 `recovered=true`，不重新调用模型。
7. 每 25 秒续期、90 秒租约到期且被读取时，将失联 `running` 原子转为 `interrupted`，保存可重试说明。恢复本身不自动重新生成。
8. 保存失败时保留当前响应预览，并返回 `persistence_status=failed`、`publishable=false`、`conversation_persistence_failed`。数据库完全不可写时，不能承诺失败预览可跨进程恢复；界面必须提示用户保留当前内容。

匿名运行及无 PostgreSQL 的非生产测试使用 `persistence_status=ephemeral`，不声明具备跨进程恢复能力。生产启动仍要求有效 PostgreSQL 及正确 revision。

## 数据库约束与部署

- `20261003_0005_research_delivery` 的父 revision 为 `20260716_0004`；M6 的 `20261003_0006` 在其后。
- 运行主键为 `(user_id,run_id)`，会话消息主键为 `(user_id,session_id,message_id)`；同一运行每个角色仅一条权威消息。同一用户在同一会话内不能把助手消息 ID 用于另一运行。
- 外键包含 owner，删除会话级联清除其运行和权威消息。新增表启用并强制 RLS，事务内以 `set_config(..., true)` 绑定 owner；连接返回池后不保留租户设置。
- 外键和恢复查询均有匹配索引；锁等待 5 秒、语句 15 秒。研究运行连接池为 3 个常驻及最多 2 个临时连接，不随模型推理时长占住数据库连接。
- 部署前备份数据库并在隔离库验证升级，再执行 `alembic upgrade head`。迁移只能前进；回滚应用时不删除新用户数据。
- **旧镜像的严格 revision 门禁不能直接读取新 head。** 兼容回滚镜像应在旧业务代码上增加 `migrations/versions/20261003_0005_research_delivery.py` 与 `20261003_0006_rag_lexical.py`，保留已有 `0001–0004`、`env.py`、`alembic.ini`。`database.py` 只从迁移文件计算 head，没有额外硬编码版本或 ORM metadata 依赖。

## 验收

本地已通过 36 项定向后端测试，包括消息幂等、旧快照合并、恢复前不做模型预检、内存状态丢失后的终态回放、owner 隔离、保存失败预览、聊天质量门禁、取消和已有会话/报告链路。

真实数据库测试入口为 `backend/tests/test_research_run_postgres.py`，仅接受显式 `FINSIGHT_TEST_POSTGRES_DSN`，且数据库名必须为 `finsight_test_*`。每项使用随机独立 schema，应用精确的 `0005` 迁移，验证历史保留、最终事务、重复提交竞态、失败回滚、重试顺序、租约恢复、删除级联与 RLS。测试从不读取生产 DSN。

2026-10-03 已在隔离 PostgreSQL 中使用非 superuser 数据库 owner 完成 `0001 → 0006` 全链迁移。8 项研究运行事务/RLS 验收全部通过；与 4 项 pgvector 模型身份隔离、NULL 向量词法检索、未知身份旧向量排除、故障时保留旧有效向量测试合并运行，结果为 **12 passed**。这是真实数据库验证，不是 SQL 编译或事务替身。

临时数据库、角色和容器已清理，生产业务数据库尚未执行本次迁移。线上发布、真实 worker 推理与登录浏览器验收仍由后续发布记录补充。
