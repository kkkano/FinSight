# 发布记录

2026-10-03，运行版本 `94a0171ad426b816843b09aece65fe76a52b5289` 已部署至 https://finsight-ai.chat 。后续文档提交不改变该运行镜像版本。

## 提交与运行镜像

- `a4234a99`：统一请求、证据、质量、后端消息/运行持久化、RAG 隔离及新闻事件合同。
- `94a0171a`：报价来源、币种和行情时间完整链路修复；分析时间与源时间分开。
- 分支：`release/models-us20-20261002`，代码已推送。
- 后端镜像 ID：`sha256:09dbc1b85dc51add352753bd7e54079dcd223e695c3114cbe42891ec7eac1cc4`。
- 前端镜像 ID：`sha256:e6253ce5312bc0a508c9a0ca9a9c60e91ba928e3c0eb06dd76bcfdd42ec49cee`。
- backend、frontend、rag-inference、prediction-watchdog 均使用该 SHA；公开 HTML 的 Service Worker 版本已核对。

## 数据库与恢复保护

生产已完成 `20260716_0004 → 20261003_0005 → 20261003_0006` 升级，没有改写或删除既有用户会话与向量数据。

升级前备份大小 `149938704` 字节，SHA-256 为 `cc56336be306606967c47612e969f576268068535b4a0d33d0aab963ea0b90b1`。备份已实际恢复到独立临时数据库，确认原 revision 为 `20260716_0004`，随后清理该临时库。备份与服务端配置副本保留在服务器受限发布目录，不进入 Git。

保留 `94a0171ad426b816843b09aece65fe76a52b5289-rollback` 镜像：旧业务代码包含新增迁移元数据，实测 schema gate 能识别生产 `0006`。该检查证明 schema 兼容性，不等于已执行完整生产回滚。未执行 downgrade；回滚不得删除新消息、运行终态或词法文档。

## 发布后验证

- 后端本机与公开 `/readyz` 均返回 200、`ready=true`；认证、数据库、Graph、checkpoint、LLM 均正常。
- 生产数据库 canary 验证：最终消息保存成功、重复完成不能改写答案、旧浏览器快照不能覆盖权威消息、新连接恢复一致、跨 owner 不可读取。canary 已清理。
- 默认模型为 `step-5-preview`，端点 `system-stepfun`；前台输出上限 `65536`，整轮 token 预算 `0`（关闭限制）。`CONCURRENCY_LIMIT_ENABLED=false`、`PREDICTION_ENABLED=false` 保持不变。
- 公开 `/api/models` 返回 200，系统目录包含 `stepfun:step-5-preview`。
- 公开 AAPL quote 返回 200，价格为 `333.69`、来源 `twelve_data`、行情时间 `2026-10-02T00:00:00Z`、quality 为 trusted。该旧式公开 quote 数据体未提供 currency；未把缺省字段写成币种验证通过，完整工具/PriceAgent 币种透传由 52 项合同测试覆盖。
- 真实匿名浏览器访问 `/welcome` 和 `/track-record` 返回 200，路由保持正确，标题分别为 FinSight/登录和 US20 预测战绩，无 JavaScript 运行时错误。没有据此声称真实登录浏览器路径已验证。
- 完整供应商验证在开发机完成；AAPL 与 NVDA/AMD 报告均产出受支持内容、`publishable=true`，同时保留 `warn/partial`。详细边界见 [VALIDATION.md](VALIDATION.md)。

## RAG 与资源状态

worker 实测 `resource_limited`、`inference_verified=false`。API 明确返回 `semantic_ready=false`、`lexical_ready=true`、`reranker=disabled`，以 PostgreSQL 持久词法检索继续工作；未伪称 BGE 推理已通过。

发布前可用内存约 682 MiB，按预案只暂停旧 FinSight backend/watchdog，释放到约 1327 MiB 后执行备份与构建。上线后样本可用内存约 912 MiB。其他业务容器保持运行；所有本次 QA 容器、隔离库、角色和生产 canary 均已清理，验证记录保留。

SSH 管道发布脚本中的 Compose 一次性迁移命令最初消费了后续标准输入，导致迁移完成后没有继续启动服务；已显式接续启动并完成上述验证，脚本修正为 `run -T ... < /dev/null`。发布必须核对容器镜像、schema 和实际健康结果，不能只依赖脚本退出码。

24 小时运行观察尚未完成；真实语义 RAG 需足够内存后另行验收。没有发送额外测试告警邮件。

后续前端独立修复已发布 `4cd9e1c1`，后端继续运行 `94a0171a`。详情见 [聊天交付修复](CHAT_DELIVERY_FOLLOWUP.md)，两者版本差异是有意的独立发布。
