# 2026-09-15 发布验证记录

状态：代码发布候选已推送；生产切换因依赖就绪门禁失败而停止，旧镜像已恢复。本文不表示生产已完成升级。

## 目标

- 分支：`refactor/finsight-research-workbench-20260915`
- 目标提交：`c18b147c`
- 旧稳定提交：`7eeb3455`
- 数据库 head：`20260716_0004`

## 已通过

- 固定后端依赖全量：`1524 passed, 2 skipped`。
- OpenAPI 快照：`1 passed`；生成类型无漂移。
- 前端 lint、构建、177 个单测、19 个 Playwright E2E 通过。
- `npm audit --omit=dev`：生产依赖 0 个已知漏洞。
- 生产 PostgreSQL `pg_dump` 已写入受限备份目录，并实际恢复到临时数据库。
- 13 张关键业务表逐表行数与源库一致；临时恢复库已删除。
- Alembic 临时库演练完成：`upgrade head -> downgrade 20260716_0003 -> upgrade head`，最终为 `20260716_0004`。
- 目标后端镜像构建成功，并在隔离运行容器中验证 PostgreSQL RAG 与 `bge-m3` 1024 维编码。

## 阻断与处置

目标后端启动后，`/readyz` 持续返回 503，组件状态为：

- `authentication`: `auth_verifier_unavailable`。生产 Supabase 项目域名在目标机解析失败，环境中没有可替代的 `SUPABASE_JWT_SECRET`。
- `rag`: `rag_embedding_degraded`。启动探针未能在服务进程中维持真实 BGE 状态，因此生产 fail-closed。

未替换前端，未执行生产表迁移（生产已是 head），未修改数据库卷。目标镜像在回滚后删除以恢复磁盘空间；旧稳定后端镜像和前端镜像保留。生产环境文件已恢复到发布前备份内容。

旧后端已恢复运行，但由于同一 Supabase DNS/验证依赖不可达，兼容 `/health` 仍为 degraded；前端静态入口保持可访问。不得通过关闭认证、启用匿名生成、改为 hash fallback 或伪造健康检查来绕过该阻断。

## 再发布条件

1. 修复 Supabase 项目 URL/DNS，或在受控密钥管理中提供有效 JWT 验证配置，并用只读验证确认 JWKS/密钥可用。
2. 在新进程中再次验证 `RAG_EMBEDDING=bge-m3`、PostgreSQL backend、向量维度 1024 和 `/readyz=200`。
3. 重新执行空间、备份恢复、镜像 ID、Alembic 和 canary 门禁，再按 Runbook 顺序切换 backend、frontend。

本记录不包含服务器地址、密码、token、Cookie、DSN 或 API key。
