# /goal 文本（复制以下全文作为 goal）

目标：按 `docs/superpowers/plans/2026-07-03-finsight-overhaul/` 下的 11 份 spec（00 主纲 + 01~07 即 WP0-WP6 + 08 视觉重构 + 09 联动审计 + 10 Agent原生化），完成 FinSight 全部重构与新功能，通过全部完成门禁，并完成本地部署验证。

## 执行契约（每次会话唤醒都必须先重读本节）

1. **单一事实源**：任务定义、代码、验收标准一律以 spec 文件为准，禁止自由发挥、禁止"顺手优化"spec 之外的东西。执行顺序：**WP0 → WP1 → 08(Task1-3) → WP2 → WP3 → WP4 → WP5 → WP6 → 08(Task4-11) → 09 → 10**。
2. **进度账本**：`docs/superpowers/plans/2026-07-03-finsight-overhaul/PROGRESS.md` 是唯一进度事实源。每完成一个任务：①把 spec 里对应 checkbox 从 `- [ ]` 改 `- [x]`；②PROGRESS.md 追加一行 `日期 | 文档-任务号 | commit hash | 测试结果`。**每次会话开始的第一件事：读 PROGRESS.md + `git log --oneline -15` 定位断点，从下一个未完成任务继续，绝不重做已完成任务。**
3. **任务纪律**：一个任务 = 先写 spec 给的失败测试 → 实现 → 测试绿 → 用 spec 给的 commit message 提交一次。同一任务失败重试最多 2 次，仍失败 → 写入 `BLOCKED.md`（任务号/失败原因/尝试记录），跳过它继续不受阻塞的任务，所在 WP 收尾时回头再试一次。
4. **硬门禁（不过不得进入下一个 WP）**：`python -m pytest backend/tests tests/golden -x -q` 全绿；`cd frontend && pnpm test:unit && pnpm build` 全绿；标注 [MECHANICAL] 的任务金样快照零 diff（禁止用 GOLDEN_UPDATE 掩盖非预期 diff）。
5. **git 纪律**：所有工作在分支 `overhaul/main`（首次启动时从当前 HEAD 创建并切换）。只 commit，**绝不 push、绝不碰 main、绝不 force 操作**。
6. **依赖白名单（已预先批准，除此之外一律不装）**：`pydantic-settings`、`PyJWT[crypto]`、`akshare`、`openapi-typescript`、`@fontsource-variable/jetbrains-mono`、`vite-plugin-pwa`、`@tanstack/react-query`、`virtua`。每装一个在 PROGRESS.md 登记。
7. **偏差处理**：spec 行号漂移/结构不符 → 按 spec 的 grep 锚点自行适配，偏差记入 PROGRESS.md 的 `## Deviations` 段；语义级冲突（照做会破坏行为或做不了）→ 记 BLOCKED.md 跳过，**不许擅自改设计**。
8. **上下文管理**：每完成一个 WP，主动压缩上下文，压缩摘要必须包含：当前 WP、下一个任务号、未决 BLOCKED 项、分支名。
9. **不做的事**：不 merge/不碰 main 分支；不动服务器上 openclaw/sub2api 等无关容器；不改 spec 的设计决策；不在 BLOCKED 之外跳过任何任务；服务器密码不写入任何文件、脚本或命令行参数（全程 SSH key）。

## 完成判据（全部满足才算达成）

- A. 11 份 spec 全部 checkbox 为 [x]（BLOCKED.md 例外项 ≤ 总任务数的 5%，且每项有原因记录）
- B. `00-MASTER-SPEC.md` 末尾的全局验收门禁 4 条命令全绿
- C1. **本地部署验证**：`docker compose --env-file .env.server up -d --build` 全栈启动成功，`curl localhost:8000/health` 返回 200，冒烟清单全过：聊天一轮生成报告、多问题 query 分节回答、看板各 tab 加载且图表带来源徽标、工作台四段渲染、报告分享链接匿名可读、断流自动续传生效、@技术面分析师 深挖署名一致
- C2. **生产滚动更新（175.178.159.112，finsight-ai.chat 即此机）**：按下方《生产部署流程》执行并通过部署后验证
- D. 打 tag `v2.0.0-rc1`；CHANGELOG.md 增量段落；输出最终执行报告（完成清单/阻塞清单/偏差清单三张表）

## 生产部署流程（判据 C2 的展开，逐步执行）

**服务器事实（2026-07-03 已核实）**：ubuntu@175.178.159.112，SSH key 免密已配置（密码不得写入任何文件或命令行）；部署目录 `/home/ubuntu/FinSight`（git 仓库，当前在基线 `4a1c055`）；机器 4 核 / 3.3G 内存（可用约 0.9G）/ 磁盘 40G 已用 85%；同机还跑着 `openclaw-openclaw-gateway-1`、`sub2api*` 等无关容器。

1. **代码送达**：优先 `git push origin overhaul/main`（GitHub 凭证不可用时备选：`git push ssh://ubuntu@175.178.159.112/home/ubuntu/FinSight overhaul/main` 直推服务器仓库）；服务器端 `git fetch && git checkout overhaul/main`。
2. **前置护栏（不满足不得继续）**：`docker builder prune -f`（可回收约 1.3G）后 `df -h /` 使用率必须 <82%；`free -h` 可用 >600Mi；备份：`docker tag finsight-backend finsight-backend:rollback && docker tag finsight-frontend finsight-frontend:rollback`，`tar czf ~/finsight_data_$(date +%m%d).tgz` 备份 backend_data 卷挂载目录。
3. **构建更新（只动 FinSight 三件套）**：`docker compose --env-file .env.server up -d --build backend frontend`——**串行构建防 OOM**（先 backend 后 frontend）；**绝不触碰 openclaw/sub2api 任何容器**；postgres 不重建。
4. **部署后验证**：`curl -s localhost:8000/health` 200；`docker ps` 三容器 healthy 且 openclaw/sub2api 原样；`docker logs finsight-backend --since 5m` 无 crash loop；浏览器过 https://finsight-ai.chat 冒烟（判据 C1 清单的线上版）；`df -h && free -h` 复查。
5. **回滚预案（验证失败即执行）**：`git checkout 4a1c055 && docker compose --env-file .env.server up -d --build backend frontend`，或直接用 rollback 镜像 tag 起容器；数据卷用备份 tgz 恢复。
6. **新增 env**：对照 `.env.server.example` 增量段把新变量（灰度 flag、SUPABASE_*、USER_DAILY_COST_LIMIT_USD 等）补进服务器 `.env.server`，灰度 flag 按 WP2 Task 11 顺序逐个开启观察。

---

# 浮浮酱的使用建议（不属于 goal 文本）

1. **建议先立一个小 goal 试跑水温**：只包 `WP0 + WP1 + 08(Task1-3)`（一周量级），验证"断点续跑 + 门禁 + 账本"这套工作流转得顺，再把上面的大 goal 立上。小 goal 文本 = 上面全文，把执行顺序和判据 A 换成对应范围即可。
2. **首次启动前的准备**（一次性）：
   - `git checkout -b overhaul/main`
   - 创建空的 `PROGRESS.md`（表头 + Deviations 空段）和 `BLOCKED.md`
   - 从服务器拉一份可用 env 到本地：`scp ubuntu@175.178.159.112:~/FinSight/.env.server ./.env.server`（已在 .gitignore，绝不提交）——金样快照与本地 docker 验证都靠它
   - 确认 `git push origin` 凭证可用（不可用则采用直推服务器备选方案）
3. **限流应对**：goal 跑批期间尽量串行、避免并行子 agent（今天已验证并行会 429）。
4. **判据 A 的 5% 豁免线**是给数据源/环境类不可控失败留的，不是给难任务留的——review 时盯一眼 BLOCKED.md 里有没有"其实是不想做"的项。
