# 聊天与研究报告的模型选择

登录用户可从聊天输入区的模型按钮或设置页选择系统内置模型、自带 OpenAI 兼容服务，并恢复系统默认。选择只作用于后续 `/api/execute` 与 `/api/execute/resume` 请求；个股异步 Prediction 和固定公开账本使用各自系统策略。已开始的回答使用开始时的选择，重连不更换模型。

## 系统内置模型

首个内置模型为 Step 5 Preview，服务端从 `STEPFUN_API_KEY` 读取凭据。模型目录只返回 ID、可用性、官方图标及 effort，系统 key 不下发。系统选择不能覆盖 URL 或 key；没有其它默认端点时 StepFun 配置可作为服务端默认。

- [官方模型能力](https://platform.stepfun.com/docs/zh/guides/models/step-5-preview)：`reasoning_effort` 为 low、medium、high，界面显式选择 medium。
- [官方 Step Plan 接入](https://platform.stepfun.com/docs/zh/step-plan/integrations/reasoning-api)：base URL 为 `https://api.stepfun.com/step_plan/v1`。
- 图标使用官方文档 favicon 的本地副本。未知自定义模型不猜测 effort 档位，采用供应商默认。

## 自定义服务与数据边界

用户填写公共 HTTPS API 地址、自己的 key 和模型 ID，测试成功后应用。应用前必须确认：外部服务会收到完整研究上下文，包括请求、系统提示词、RAG 检索结果和付费数据源内容。后端要求 `context_acknowledged: true`。地址、模型或 key 改变后须重新测试与确认；连接测试仅发送固定测试消息。

密钥和选择仅保存在页面内存，刷新、退出或切换账号会清除；同一账号刷新 token 不清除。不会写入 localStorage、sessionStorage、数据库或服务端端点池。

完整 `/chat/completions` 地址去掉终点后缀，纯域名补 `/v1`，StepFun `/step_plan` 补 `/step_plan/v1`，其它完整兼容路径保留。只允许公共 HTTPS 443，拒绝内网和共享地址空间，不跟随 HTTP 重定向。DNS 检查与连接的时间窗尚未采用 IP 固定连接。

## 认证、预算与隔离

`/api/models`、`/api/models/capabilities` 公开且受普通限流；显式选择与 `/api/models/test` 要求服务端验证的非匿名 Supabase 身份，内部 API key 可用于受信任管理请求。连接测试每个已验证用户每分钟最多 3 次，并占用生成并发槽。供应商认证、限流、网络及格式错误统一返回安全提示，不回显供应商错误正文。

`X-FinSight-Model` 只随聊天/报告的生成请求发送；数据读取、测试、目录、取消和重放请求不携带模型密钥。base64 不是加密，生产必须使用 HTTPS。Axios 错误对象中的模型头及连接测试请求体会清除，避免客户端日志泄露。

模型选择通过 ContextVar 进入当前 LLM 调用链，使用单独端点管理器，不能修改全局轮换池或回退到别人的模型。显式选择只允许一次供应商尝试；自定义 SDK 超时不超过 60 秒，整次请求及可重连后台生成任务的硬上限均为 120 秒。任务持有并关闭自己的 HTTP 客户端。

现有执行链已经停用全站共享报告缓存，本次保持这一行为；报告仍按用户归档。公开账本采集显式清除用户模型选择，不能使用用户自带服务或 key。

## 验证入口

后端模型选择测试覆盖真实应用鉴权接线、单独端点池、当前调用链、超时、流式后台任务、凭据隔离与公开路由顺序。前端单测和浏览器流程覆盖登录、effort、完整上下文确认、凭据生命周期、请求头范围及恢复默认。测试只使用占位凭据。
