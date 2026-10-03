# “100%但聊天无正文”后续修复

## 实际证据

用户在刷新后重新提问英特尔四维研究，界面显示流程完成、100%，但仍转圈且聊天区没有答案。生产数据库确认该运行已经完成，最终事件为 `done`、保存状态为 `saved`，最终正文及权威 assistant message 都有 **4759 字**。无需重新生成或修改用户历史。

本次三个运行/消息 ID 都由服务器生成，说明请求没有携带新客户端通常发送的稳定 ID。已排除当前 API facade 裁剪字段。该事实提示实际客户端与当前发布合同不一致，但无法仅凭它认定用户没有刷新，也未取得用户标签页的 bundle/network 证据；用户明确说明刷新过。旧 Service Worker 的导航缓存是需要修正的可能路径。

## 已复现的前端问题

使用实际状态存储可复现：当本轮 assistant 槽位丢失，正文更新静默返回，但全局执行预览仍接收 token；随后 pipeline 完成事件推进到 100%，run 仍在 waiting for terminal 状态。另有 SSE 最终事件已收到、HTTP 未关闭时读取不结束的缺口。

## 修复

后续用户带地址栏截图确认访问的就是正确线上域名，因此“入口地址错误”已排除。新增真实问题：生产历史有13条，旧问题后存在两组服务器生成ID的完整问答。原恢复代码要求旧问题后立刻是assistant，遇到补建的canonical user就退出；这使新页面也可能跳过已保存答案。新增精确锚点后的多组完整问答恢复，保留两轮真实答案、不改生产历史；对应50项store测试通过。

新增独立 `/api/client-recovery` 修复页与真实 Service Worker 浏览器fixture：旧导航缓存仍控制页面时也能进入修复页，点击后加载新界面；登录Cookie、模型设置和聊天localStorage均保留，无关缓存保留。新legacy浏览器fixture直接覆盖13条历史中的两组canonical答案，验证恢复后无写入、无重复生成。

- running 进度不超过99%；pipeline完成阶段显示交付中，真正最终事件才显示100%。
- 同 owner/session/user message/run/controller 的本轮正文可以恢复丢失占位；删除、清空、换账号、撤销或新运行接管均禁止旧回复复活。
- 流挂住或中断时读取同 run 的服务器终态，应用已经保存的正文并收尾，不重复付费调用。
- SSE收到done/error后立即退出读取；恢复后关闭连接不发送业务cancel。旧run的finally不能清掉新run状态。
- 导航改NetworkFirst；新增不可缓存的app-version.json和新版本提示。不会强制刷新生成中页面或丢掉未发送输入。

## 验证与部署

67项聚焦unit通过；6项会话浏览器测试通过，包括“回复槽丢失+SSE挂住+99%交付+服务器正文恢复”；新版本提示浏览器测试通过。TypeScript使用512MB串行通过，受影响ESLint通过。所有浏览器用例使用fixture，不重发用户问题或产生供应商费用。

已提交、push 并独立发布前端版本 `4cd9e1c1159778e1ba0185bf4fb0e99ce39ba76f`，镜像 ID 为 `sha256:cf4c93c3ea44e6929050fcdb66b5cb59d50516b68e9d2292198eec517a0c4b8e`。后端仍运行 `94a0171a`，没有重启或重新调用模型。

旧执行面板 E2E 补齐点击真实“执行详情”展开操作后，2 项失败用例重跑通过；本轮合计 10 个不同浏览器用例通过。发布后 `/app-version.json` 版本匹配并带 `no-cache, no-store, must-revalidate`，公开 `/chat` HTML 版本匹配，生成 Service Worker 包含 NetworkFirst 导航，`/readyz` 返回 ready；欢迎页与公开战绩页均 200 且无 JavaScript 运行时错误。当前用户页面需要一次强制刷新加载本次修复；未自动操作其浏览器或修改其历史记录。
