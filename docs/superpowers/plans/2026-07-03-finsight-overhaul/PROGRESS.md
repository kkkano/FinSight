# 执行进度账本（唯一进度事实源）

| 日期 | 任务 | commit | 测试结果 |
|------|------|--------|----------|
| 2026-07-12 | WP5-Task3 portfolio/conversation/monitor 多用户隔离 | e8e4ca9 | 新增 SQLite 幂等加列与复合用户主键迁移，旧 SQLite/JSON 数据无损归 `public`；三 store 全公开 CRUD 末尾新增默认 `user_id`，三主 router 及调仓、晨报、每日任务、宏观日历、后台盯盘旁路同步透传，缓存与调度均纳入用户维度。隔离/老库迁移/真实 Router 测试 7 passed；完整后端 `1970 passed/8 skipped`。使用两个独立 Chromium context 经真实 security_gate/API 验证同 session 的 Alice 与匿名用户持仓、会话、盯盘目标互不可见，QA 进程已清理。 |
| 2026-07-11 | WP5-Task2 security_gate 用户身份接入 | 450e412 | API key 检查后解析 Supabase JWT，写入 `request.state.user_id/user_email`；可选强制登录模式对非白名单返回中文 401，默认匿名保持 `public`；已登录用户使用独立限流/并发桶，RAG 既有身份回退保留。新增 5 项身份中间件测试；认证/安全/RAG 定向回归 43 passed，金样 12 passed 零漂移。 |
| 2026-07-11 | WP5-Task1 Supabase JWT 校验 | 7595d56 | 新增 HS256 secret 与 RS256/ES256 JWKS 自动探测校验、30 秒时钟偏移、10 分钟 JWKS 缓存及刷新失败旧缓存回退；Bearer 请求解析失败安全返回匿名。离线覆盖有效、过期、错密钥、缺 `sub`、缺配置、Bearer 异常、JWKS 缓存/回退共 12 passed；未访问真实 Supabase 或 LLM。 |
| 2026-07-11 | WP4 完成门禁 | a0e71fa | 使用仓库 `.venv` 锁定 FastAPI 0.122.0/Pydantic 2.12.3，并注入不联网的测试专用兼容端点；修正 datetime SSE 测试的旧 `main.aget_graph_runner` patch 目标与列表式 trace 断言后，后端 + 金样 `1960 passed/8 skipped`，OpenAPI 快照通过。前端重新生成 API 类型零漂移，41 files/235 tests passed，生产 build 成功；`_env_int` 重复和 `Promise<any>` 均为 0。真实 Vite + Chromium 验证聊天发送/重试、设置保存成功且控制台 0 error；仓库 Playwright 仪表盘路由与 MiniChat 2/2 通过。 |
| 2026-07-11 | WP4-Task9 中文文案常量表 | c204ea9 | 新建纯常量 `locales/zh.ts`，集中聊天输入、消息列表、会话状态和执行状态的用户可见文案，混合英文状态统一为中文；Task 7 已迁出的流式职责同步接入 `useChatStream`，避免形成第二文案源。停止状态与质量门禁测试引用同一常量；定向 lint 0 问题，相关 21 tests passed，完整前端 41 files/235 tests passed，生产 build 成功。 |
| 2026-07-11 | WP4-Task8 React Query 热数据 hook 收敛 | 6132519 | 新增根级 `QueryClientProvider`，默认 staleTime 30s、行情 5s，关闭自动重试与窗口聚焦刷新以保持原语义；`useDashboardData/useMarketQuotes/useMorningBrief/useFindings/usePortfolioSummary` 迁入统一 query/mutation 缓存，保留 60s 轮询、晨报 localStorage 当日 TTL、发现流乐观更新和既有返回合同。删除持仓汇总 100+ 行自建缓存/订阅/定时器。npm/pnpm 双锁同步；41 files/235 tests passed，生产 build 成功，改动文件定向 lint 0 问题。 |
| 2026-07-11 | WP4-Task7 useChatStream 统一发送/重试/停止 | c039b43 | `useChatStream` 以七块注释锚点统一模糊查询守卫、ticker/history、SSE/store 桥接、报告回捞、图表补挂与会话收尾；Retry 改为同一 SSE 管线并原位更新。`ChatInput.tsx` 由约 930 行降至 249 行，组件内 `handleSend` 5 行；本地假进度映射和 ChatList 非流式 Retry 清零。前端 40 files/234 tests passed，生产 build 成功；真实 Vite + Chromium 冒烟覆盖发送、重试、停止、断流回捞与执行台联动，全部通过且控制台 0 error；本任务四文件定向 lint 0 问题，全仓 lint 仍仅为未改动文件既有 2 errors/3 warnings。 |
| 2026-07-11 | WP4-Task6 ticker/图表工具归一 | 7ac4719 | `utils/ticker.ts` 收口 ticker 提取/过滤/去重，`utils/chartIntent.ts` 收口 API 检测、关键词回退、Inline/SmartChart 分流与 `[CHART]` 去重注入；ChatInput/ChatList 本地重复定义扫描 0 命中，净删 98 行。新增 AAPL K 线、NVDA 趋势图、普通介绍反例、渲染能力和最多三标的注入测试；前端 39 files/232 tests passed，生产 build 成功；全仓 lint 仍仅为未改动文件既有 2 errors/3 warnings。 |
| 2026-07-11 | WP4-Task5 API client 分域、类型收口与统一 SSE guard | 814178a | 旧/新 `apiClient` 经 TypeScript AST 对拍均为同一组 78 个方法，拆入 11 个领域模块，兼容出口由 1715 行收至 28 行；`Promise<any>` 扫描 0 命中；新增终态去重与 token idle synthetic-done 测试，前端 38 files/227 tests passed，生产 build 成功；真实 Vite + Chromium mock API/SSE 冒烟覆盖聊天、报告领域、执行流和工作台，控制台 0 error。全仓 lint 仅余未改动 `SettingsModal.tsx` 的 2 个既有声明顺序错误及 3 个既有 warning，本任务新增 lint 错误为 0。 |
| 2026-07-11 | WP4-Task4 OpenAPI 快照桥 | 637a084 | 后端 OpenAPI 快照测试重复运行均 1 passed；`openapi-typescript` 7.13.0 生成 `schema.d.ts`，CI 同款重新生成后零 diff；前端 38 files/225 tests passed，生产 build 成功；快照测试 F821 通过。CI 后端全量已覆盖快照测试，frontend build job 新增生成类型漂移守护；npm/pnpm 双锁文件同步。 |
| 2026-07-11 | WP4-Task3 llm_config 去硬编码端点 | d2e0040 | LLM/config/startup/lifespan 定向 50 passed；金样 12 passed；后端全量 + 金样 1940 passed/19 failed/8 skipped，19 项与 `tests/baseline-failures-4a1c055.txt` 逐项一致、零新增；运行时旧第三方端点与默认模型扫描零命中，相关 F821 与 compileall 通过；当前主机无 Docker CLI，Compose 解析留待本地 Docker 门禁。 |
| 2026-07-11 | WP4-Task2 planner/executor/agent/security typed Settings | 94e48ee | 四域合同 + 受影响回归 67 passed；WP3/金样 16 passed、快照零差异；全后端 + 金样 1928 passed/29 failed/8 skipped 后，19 项与固化基线一致，10 项新增均定位为 Settings cache/reload 迁移问题并修复，修复集 19 passed、限流跨测试顺序集 14 passed；全仓 ruff F821 通过。 |
| 2026-07-11 | WP4-Task1 统一 env helper | 756ec5f | helper 单测 16 passed；Task 1 定向 + 金样 247 passed；后端全量 1934 passed/19 failed/8 skipped，19 个失败与 `tests/baseline-failures-4a1c055.txt` 逐项一致、零新增；生产代码普通 `_env_*` 重复定义清零，5 个特殊语义变体明确命名并保留。 |
| 2026-07-11 | WP3-Task8 收尾实现与完成门禁 | defa0ce | shim/旧 router 清理、silent pass 治理与 execution/policy/synthesis 拆分完成；全量 1898 passed/26 failed/13 errors 后定位 20 个新增结果均为测试 patch 目标未迁移，修正后受影响 26 passed；剩余 19 项与固化环境基线一致；本次提交前关键回归 62 passed；nodes 最大 799 行、main 42 行、生产 `_stub.py` 为 0；假 Agent 演练为新实现文件 + 3 个既有接线点。 |
| 2026-07-11 | WP2 任务级隔离纠偏复审 | defa0ce | 显式空依赖、全局 barrier、无 URL 去重、跨 task 可变别名、selection evidence、共享 source scope、embedded claim scope 共 7 passed；全仓 ruff F821 通过。 |
| 2026-07-11 | WP0/WP1 手工与前端完成门禁 | e453959 | mock SSE 聊天/Authorization/设置成功失败/生成中输入/停靠滚动/复制/重试/删除确认通过；3231 字、373 帧，P95 16.8ms、最大 33.4ms、0 long task；当前 `pnpm test:unit` 38 files/225 passed，`pnpm build` 成功。 |
| 2026-07-09 | WP3-Task7 rebalance schema下沉+分层守护 | c821b96 | test_layering 1 passed（五下层包零 backend.api import）；rebalance回归5 passed；金样12零diff；main import冒烟OK |
| 2026-07-09 | WP3-Task6 api/main拆分+*_stub节点改名 | 987e466 | 全量1887 passed/19 failed=基线一致；金样12零diff；uvicorn /health=200；main 1355→288行(security_gate/lifespan/app_factory/session_context四件套)，execute_plan_node/render_node改名+shim，RAG ingestion 12函数迁backend/rag/ingestion.py |
| 2026-07-09 | WP3-Task5 report_builder四域拆分+formatter注册表 | d4371a2 | report域回归149 passed（4失败=基线report项）+金样12零diff；全量1887 passed/19 failed=基线一致；report_builder 2693→1825行壳，citations/grounding/quality_hints/agent_formatters/util 五模块 |
| 2026-07-09 | WP3-Task4 synthesize拆分(render_vars+verifier) | ca607d7 | 新对拍测试6条金样终态逐键全等；synthesize节点回归+金样12全绿；全量1887 passed/19 failed=基线一致；synthesize 3202→1785行，render_vars包10模块+verifier独立 |
| 2026-07-09 | WP3-Task3 understand_request/router归位intent包 | 5b6d0fd | 意图域回归461 passed（2失败=基线）+金样12零diff；全量1881 passed/19 failed=基线逐条一致；UR瘦身3355→362行(shell+shim)，router整体迁intent/router.py，生产侧旧路径import清零 |
| 2026-07-09 | WP3-Task2 planner→planning/builders注册表+改名 | 1e00d9f | planner回归169+金样12全绿零diff；全量1881 passed/19 failed=基线逐条一致；41闭包ctx化提升(tokenize精确改写)，TASK_BUILDERS查表替换双elif链，planner.py 5调用点改名rule_based_planner，trace字符串保持原样 |
| 2026-07-08 | WP3-Task1 chat_renderer→renderers注册表 | ac89268 | 渲染64+金样12全绿零diff；全量1881 passed/19 failed=基线逐条一致零新增；97函数守恒(新包113=97+14renderer+2ctx)，无重复定义，全文件≤400行(最大shared 356) |
| 2026-07-08 | WP2-门禁(手工验收) | - | 真LLM(sub2api gpt-5.4-mini)：①multi_question四任务+三节渲染宏观节在(## 美联储下次议息·宏观/## AAPL·投资观点/## MSFT·投资观点)②PE→direct秒回lane=llm无agent③坏key→lane=fallback(router_heuristic_only)仍出compare研究+真实价格④黑板：探针实证risk step收到含price_agent真实发现的__context_digest；叙事级目检因本地yfinance限流延至部署冒烟(C1/C2)复验⑤SSE契约完整(plan_ready/step_start/step_done/tool_*/done,26 pipeline_stage) → **WP2 完成** |
| 2026-07-08 | WP2-门禁(自动测试部分) | 01ce883 | 四flag全on全量1880 passed/20 failed→diff基线唯一新增=evidence_ledger测试只patch旧执行器入口（env敏感，非产品回归）→修为双入口patch后 off/on 双模式 1 passed；其余19失败与基线清单逐条一致 |
| 2026-07-08 | WP2-Task11 灰度收尾+验收bug修复 | 10e144f | 管线7 passed（新测2：compare残余hints续投+启发式降权）；金样12/12全绿（conftest固定四flag全on）；understand/router/planner回归320 passed（3失败全在基线清单，零新增） |
| 2026-07-08 | WP2-Task10 多问题分节渲染 | 6738517 | 新测2 passed；渲染/compare/reply回归180 passed（2失败=基线固有）；金样12/12零diff |
| 2026-07-08 | WP2-Task9 planner lane 具名化 | f67d98c | 新测4 passed；planner回归45+金样12 全绿（零diff） |
| 2026-07-08 | WP2-Task8 图拓扑诚实化 | 7345450 | 全量 1873 passed/19 failed，失败清单与基线逐条 diff 一致=零新增；节点集断言更新为诚实拓扑 |
| 2026-07-08 | WP2-Task7 证据黑板 | 6cb53e4 | 新测2 passed；dag3+executor12+金样12 全绿；__前缀键 cache-key 过滤仅 dag_executor 启用（旧执行器行为核实保留） |
| 2026-07-08 | WP2-Task6 AgentBrief注入 | d3e1be8 | 新测2 passed；agent/planner回归315 passed（仅基线固有1失败）；金样 off/brief-on 双模式 12/12 零diff |
| 2026-07-08 | WP2-Task5 DAG执行器 | 45ae191 | 新测3 passed+旧executor 12 passed；金样 off/on 双模式 12/12 零diff；planner回归45 passed |
| 2026-07-08 | 修复WP2-T4遗留 v2契约测试回归 | 9b8ef06 | test_understanding_v2_contract 5 passed（原4 failed，非基线固有） |
| 2026-07-06 | WP2-Task4 冻结双轨 | 8a06f03 | v2默认off+消费方清单存档；金样12/12零diff |
| 2026-07-05 | WP2-Task3 意图管线重排 | 3cbabfd | 管线5测试绿；金样 off/shadow/on 三模式 12/12 零diff；understand 回归绿 |
| 2026-07-05 | WP2-Task2 关键词单源+signals | a02d234 | identity断言+4信号测试绿；金样12/12零diff；understand回归71 passed |
| 2026-07-05 | WP2-Task1 IntentFrame/AgentBrief 模型 | a3d241b | 4 passed(往返无损+contract吸收+route推断) |
| 2026-07-05 | WP2-Task0 金样防护网 | eb7baf4 | 12快照首录+复跑零diff(50s)；审读发现cn_ticker空转怪癖已记录 KNOWN_QUIRKS |
| 2026-07-05 | 08-Task3 对话区去廉价化 | fbb3c8c | Flat=TERMINAL文档流(FS▎+橙竖线),Bubble收角去阴影,LoadingDots→终端光标+真实文案,prose-terminal表格等宽,快捷建议>前缀+flex-wrap；215 passed+build 绿 |
| 2026-07-05 | 08-Task1 TERMINAL token 层 | ce170a1 | build 绿(字体woff2入包)+215 passed；--fin-* 全量别名兼容 |
| 2026-07-05 | 08-Task2 原子组件规范 | 20135dd | Card/Button/Badge/Skeleton 升级+Stat/EmptyState/SourceBadge 新建；ui/ 内 rounded-xl 清零 |
| 2026-07-05 | WP1-Task2 滚动停靠+aria | 645c17a | 215 passed+build 绿 |
| 2026-07-05 | WP1-Task3+4 memo+流式跳过图表解析 | 3acb7bd | 215 passed+build 绿 |
| 2026-07-05 | WP1-Task5+6 selector收窄+文本先落定 | 108d722 | 215 passed+build 绿（T5/T6 同文件合并提交，账本注明） |
| 2026-07-05 | WP1-Task7 生成中可打字 | 1ed52f6 | 215 passed+build 绿 |
| 2026-07-05 | WP1-Task8 复制反馈 | f7b959b | 215 passed+build 绿；删除确认基线已有(confirmDeleteConversation)，仅补复制反馈 |
| 2026-07-05 | WP0 完成门禁 | - | 后端 1841 passed/19 failed(=基线,无新增)+1条基线flaky翻绿；前端 215 passed+build 绿 → **WP0 完成** |
| 2026-07-05 | WP1-Task1 localStorage去抖 | 5485ff5 | scheduler 4 passed；全量 215 passed(含流式切回恢复回归)；build 绿 |
| 2026-07-04 | WP0-Task4+5 超时/流式鉴权/clone | f3ce2ff | vitest 211 passed + build 绿；backtest/pdf 显式120s |
| 2026-07-04 | WP0-Task3 隐私声明+Toast | 8805746 | vitest 2 passed(反向验证旧文案FAIL) |
| 2026-07-04 | WP0-Task6 端口绑回环 | a331686 | cloudflared token模式ingress指宿主localhost,兼容已核实 |
| 2026-07-04 | WP0-Task7 .bak清理 | d7e959b | git rm + gitignore |
| 2026-07-04 | WP0-Task8 drill护栏 | 6ce6f61 | 新测2 passed+drill回归9 passed |
| 2026-07-03 | WP0-Task2 main.py重复import | afa2d56 | main import OK；全量基线1839 passed/19 failed(基线固有) |
| 2026-07-03 | WP0-Task1 price.py级联bug | 79ffdfd | 新测2 passed(旧实现复验FAIL)+回归22 passed |

## Installed Dependencies
- 2026-07-11 | `PyJWT[crypto] 2.13.0` | WP5-Task1 白名单依赖，仅安装到仓库 `.venv` 并以 `PyJWT[crypto]>=2.0,<3.0` 登记 requirements；用于 Supabase HS256/RS256/ES256 JWT 校验。
- 2026-07-11 | `.venv playwright==1.61.0` | 仅用于 WP4 浏览器门禁的本地 QA 运行，不写入项目 requirements/前端锁文件；Chromium 复用主机 Chrome 可执行文件。
- 2026-07-11 | `@tanstack/react-query@5.101.2` | WP4-Task8 经主人对完整 Goal 所需依赖的授权安装；用于高频数据 hook 的请求去重、缓存、轮询与 mutation 状态收敛，npm/pnpm 双锁文件已同步。

## Deviations
- 2026-07-11 | WP4-Gate | 系统 Python 的 FastAPI 0.135.3/Pydantic 2.12.5 会令 `ValidationError` schema 多出 `ctx/input`，与仓库锁定快照不一致；门禁改用现有 `.venv` 中 requirements 锁定的 0.122.0/2.12.3，快照随即通过，未误写生成物。为避免测试调用真实 LLM 或消耗额度，测试进程只注入本地不可达兼容端点满足启动解析，所有真实密钥均未读取或回显。浏览器仪表盘自写文本 locator 受内部滚动与重复 DOM 干扰，最终采用仓库稳定 Playwright 场景完成路由和 MiniChat 验收。
- 2026-07-11 | WP4-T9 | spec 按 Task 9 编写时只列出 `ChatInput/ChatList/executionStore/useStore`；Task 7 已将发送、重试、停止和 SSE 状态从组件迁入 `useChatStream`。为保持文案单一事实源，本任务将该 hook 一并纳入替换范围，未引入 i18n 框架。
- 2026-07-11 | WP4-T8 | spec 按候选名写 `usePortfolio`，仓库实际不存在该 hook；按“以 hooks 目录实际为准”迁移被 Workbench、Sidebar、Watchlist、右侧栏共同高频消费的 `usePortfolioSummary`。晨报生成是写操作，采用 `useMutation` 负责生成、`useQuery` 负责按会话读取当日 localStorage 缓存，而非把 POST 伪装成 query。
- 2026-07-11 | WP4-T7 | spec 以旧版 `handleSend` 543 行估算组件收缩目标；实际任务开始时 `ChatInput.tsx` 约 930 行。完成后组件为 249 行，但真正的组件内 `handleSend` 仅 5 行，全部流式职责已迁入 478 行的 `useChatStream`；hook 作为单一管线保留七块职责锚点，不为追求文件行数再做无契约收益的拆分。
- 2026-07-11 | WP4-T6 | ChatInput 与 ChatList 的关键词集合和普通 ticker 长度规则存在漂移：统一实现取语义并集，保留 `趋势`/`k线` 两个关键词和 ChatList 的单字母 ticker 能力，同时继续用停用词过滤 A/I 等误报。既有 `components/chatChartIntent.ts` 未物理删除，改为指向 `utils/chartIntent.ts` 的薄兼容出口，公共逻辑只有一份。
- 2026-07-11 | WP4-T5 | spec 估算原 `apiClient` 为 60+/76 个方法、`sendMessageStream` 有 13 个调用点；AST 与全仓调用扫描确认实际为 78 个方法、3 个调用点（ChatInput、MiniChat、SSE 测试），迁移地图按代码事实记录。11 个领域模块共享同一公共合同/SSE 层，拆分中间态不能独立通过 build，故按 Task 5 整体一次提交，而非机械制造 11 个不可独立验证的 commit；最终用旧/新 AST 方法集合完全相等守护无遗漏。
- 2026-07-09 | WP3-T6 | ①main 288行未达spec≤120：bootstrap工具导入块+测试兼容再导出shim为必要占位（T8删shim后可达标）。②spec未列的 session_context.py 为会话/trace helper 新增归置文件；ROUTER_FACTORIES 草表的 AppDeps 统一签名未采纳（24个create_*签名异构，保持原构造顺序整体入create_app）。③三轮测试patch目标随迁：rag_observability_auth(get_rag_observability_store→app_factory；_fetch_supabase_user_identity/_rate_limiter→security_gate)、security_gate_auth_rate_limit(reload需重载security_gate+补善后恢复段——该测试此前就遗留1/min限流器污染，恰无人踩中)。④ingestion切割踩两坑：函数间模块级import不随AST函数块走(user_profile_memory)→memory_scope延迟导入破graph饿加载环；_env_int经_host_env_int延迟取宿主。36个测试文件execute_plan_stub/render_stub全局随迁新名。
- 2026-07-09 | WP3-T5 | spec 草图 AgentClaimFormatter->list[str] 与现实不符：现网专属格式化仅 price_agent 且返回整段 summary 字符串 → 注册表按真实签名建 AGENT_REPORT_SUMMARY_FORMATTERS（未登记返回 None 走原默认路径）。共享叶子工具入 report/util.py（_safe_str 等7个，壳81处引用回接）；grounding 曾误判需宿主 _agent_summaries_from_steps（扫描误报，实际无引用）。地图见 notes-report-builder-map.md。
- 2026-07-09 | WP3-T4 | ①spec 草图假设键累积器+板块合并，实际为 subject_type 分支树逐支返回 RenderVars → 适配 T2 同款 ctx 化闭包提升（RenderVarsCtx 19字段），build_render_vars spec 接口名保留。②对拍基准落地为 tests/fixtures/render_vars_legacy.py 冻结副本 + 6 金样终态逐键相等测试（spec 的"拆完删副本"改为副本留测试区，T8 评估）。③verifier 与宿主共享 helper 留 synthesize，verifier 经 _synth() 延迟解析（backend.graph.__init__ 饿加载 runner 导致的 import 环，两处踩中：json_utils 触发链、nodes/__init__ 函数名遮蔽子模块）。④spec synthesize≤900 未达（1785，剩余无拆分锚点）；report_agents.py 482 小幅超限（同族内聚优先）。地图见 notes-synthesize-map.md。
- 2026-07-09 | WP3-T3 | ①spec 要求删除 _legacy_understand_request——但 WP2-T3 的 fallback_rules 是整体委托它（瀑布零复制），删除=杀死规则兜底 lane → 适配为物理搬家 intent/legacy_engine.py（1230行，主体为单个引擎函数），不删除；INTENT_FRAME 默认值不在代码翻转（灰度是部署期 env 决策，见 .env.server.example 顺序）。②spec 未列的 predicates.py(701)/legacy_engine.py 为新增归置文件；task_builders 1241 行超限（_add_router_task_hints_contract 单函数~430行，无锚不切）；router.py 1991=spec 明示整体迁移。③6 个测试文件 61 处 monkeypatch(route_conversation/generate_contextual_reply) 目标随迁 intent.legacy_engine（内联 import_module 形式，调用仍走 understand_request 壳）。④_build_subject 挪 predicates 解 direct_reply↔task_builders 环。
- 2026-07-09 | WP3-T2 | ①行数约束偏差：rule_planner.py 997 行（主体尾部 ~600 行 lane 组装 spec 未给拆分锚点，不臆拆，WP3-T8 收尾再议）；company builder 超限已再切 builders/evidence.py(225)。②spec 草表 "unknown"->company 与现实不符（原 elif 链对未登记类型 no-op），未采纳；holdings 按 operation 名、URL 存在性两守卫保留在调度函数不进表。③spec 未列的 frames.py/report_mode.py/context.py 为闭包家族新增归置文件；selection.py 未建（无对应闭包，selection 逻辑在 report_mode 内）。④原文件重名闭包 _task_operation_params(:313/:782) 语义等价保后者；trace 标签 "type":"stub"/"fallback":"planner_stub" 字符串保持原样（零行为）。地图见 notes-planner-map.md。

- 2026-07-08 | WP3-T1 | ①spec 草图的 RENDERERS 是 parts.append 拼接，实际原函数为互斥早退分支链 → 注册表语义适配为 first-non-None-wins（顺序=原分支顺序，末位 render_default 恒返回），ctx 两阶段构建保持原计算顺序与副作用时点（phase1→last_report renderer→phase2 含 news_map 联网 fallback 增补）。②spec 的 11 桶超 ≤400 行约束 → news 桶再切 news_items（条目工具底层，解 news↔fallback/snapshot 环）/news_fallback/news_snapshot，shared 再切 synthesis_vars，共 16 模块。③原 try-import 块按归属拆两半：COMPANY_MAP→news_items，get_company_news/get_authoritative_media_news→news_fallback；test_chat_response_contract 3 处 monkeypatch 目标随迁 backend.graph.renderers.news_fallback（shim re-export 无法传导 patch）。迁移地图与顺序表在 notes-chat-renderer-map.md。

- 2026-07-08 | WP2-门禁 | 手工验收④黑板项：本地 yfinance 全机限流(429)+x666 gemini通道死(503)导致 risk_agent 因子数据 insufficient_data、LLM 叙事走 fallback——黑板机制本身用进程内探针实证（risk 步骤 inputs.__context_digest 含 price_agent 真实发现"AAPL 310.66 -0.64%"，prompt 模板 <peers_findings> 接线核实，T7 单测护航）；叙事级"risk 文本引用前序发现"目检顺延到判据 C1/C2 部署冒烟（服务器数据源健康）。验收证据文件 wp2_accept_*.json 留 %TEMP%，不入库。
- 2026-07-08 | WP2-门禁 | 手工验收③的 query 语义修正：spec 例句"给我一份 NVDA 的投资分析"在无 LLM 基线本来就是 direct 空转（金样 single_report 佐证，KNOWN_QUIRKS cn_ticker 同族）；改用金样 compare 句式验证"规则兜底出研究结果"，符合条款本意（LLM 断 → 规则仍可产研究）。

- 2026-07-08 | WP2-T11 | spec Step2 说"金样 v2 目录转正（删旧目录重命名）"——实际 T0-T10 全程 LLM-off 下新旧路径逐字节一致、从未产生独立 v2 目录，转正落地为 conftest 确定性环境固定四 flag 全 on（金样从此压测新引擎路径）。KNOWN_QUIRKS 补收尾审读章节代替打勾（1/3 已修=分节渲染，cn_ticker 归 WP3-T3，greeting 行为正确保持）。
- 2026-07-08 | WP2-T11 | 验收准备中发现并修复两个真 bug：①compare 早退分支吞掉 router 非公司 hints（macro 等）→ understand_request 加 project_residual_hints 续投；②router fail-open 启发式决策（新增 decision_source 字段标记）曾被管线当 LLM 权威 → 视同 router 不可用交回规则兜底。测试样例注意：legacy _TRADE_DECISION_RE 动词表不含「投资」，「值得买吗」才触发 must_project 兜底。

- 2026-07-08 | WP2-T10 | 实证发现现网 artifacts.task_results 按分组名（如 primary_company）而非 task id 聚合（off/on 模式皆然）→ 分节只在"按 task id 聚合且 ≥2 个非空 subject_label"时触发，现有 compare/整体渲染路径不受影响。附加防御条件：空 label 的 task（如 compare 主任务）不出节。Task 11 灰度手工验收时用真 LLM 复核 multi_question 分节实际生效。

- 2026-07-08 | WP2-T6 | planner_stub 的 brief 字段注入放在 dedup key 计算之后（key 用原始 inputs）——保证既有"同 inputs 合并 task_ids"行为零变化；合并命中时保留首个 task 的 brief 字段。基类 __init__ 收编 tools_module 后，price/news/deep_search 的 super() 调用同步改为四参（防位置参数错位），fundamental/technical/macro/risk 四个同构 __init__ 删除。

- 2026-07-08 | WP2-T5 | 发现 WP2-T4 冻结 v2 默认值时漏跑 test_understanding_v2_contract.py（4个非基线失败）。修复方式：该文件是 v2 影子路径的契约测试，显式 monkeypatch shadow 模式（功能仍在 flag 后保留，默认 off 行为另有测试守护），未改任何生产代码。
- 2026-07-08 | WP2-T5 | 按 spec 把旧 executor 的 _run_step 提为模块级 run_single_step(step, ctx) 供双执行器共用；cache_key_inputs 钩子默认恒等（__escalation_stage 等历史上就参与 cache key，旧行为保持），__ 前缀过滤留给 T7 且仅 dag_executor 启用。

- 2026-07-06 | WP2-T4 | spec 假设 intent_contract_mode 默认 shadow 有误——实际默认 enforce（生产现役 required_evidence 机制）。纠偏：只冻结真影子 understanding_v2（无任何消费方），contract 保持 enforce 不动，其收编改判 WP3-T3（notes-contract-consumers.md 已列消费方与 on 模式灰度观察点）。

- 2026-07-05 | WP2-T3 | fallback_rules 未复制关键词瀑布，而是整体委托改名后的 _legacy_understand_request 并经 intent_frame_from_legacy 转换——瀑布零复制、fallback 与金样逐字节一致；物理拆分按计划归 WP3-T3。direct 复核新语义=只降级 clarify 不伪造 research（ORC-02 修复，测试守护）。shadow 模式管线+legacy 双跑（对拍成本，on 模式无双跑）。

- 2026-07-05 | WP2-T2 | conversation_router 的关键词是函数内联 token（非模块常量），与 understand 侧并集合并=行为变更，违背本任务零变更约束——合并推迟到 T3 意图管线重排（keywords.py 已注释说明）。29 个常量以'剪切+显式import回接'方式单源化，identity 测试守护。

- 2026-07-05 | 08-T3 | MessagePayload 无 timestamp/agents 字段，元信息行暂不含时间戳与 agent chips（agent 署名按计划归 10 号文档 Task 9 随 AgentProfile 接线）；chatStyle 双风格并存：flat 按 TERMINAL 全量改造、bubble 收角去渐变保留为备选。

- 2026-07-05 | WP1-T8 | 删除会话确认在基线已存在（ChatWorkspace confirmDeleteConversation），spec 该步骤按已完成处理；T9 虚拟化为可选任务按约定跳过。

- 2026-07-05 | WP1-T1 | 无 jsdom（不在白名单），spec 的 localStorage 计数测试改为抽取 persistScheduler 纯模块 + fake timers 单测调度语义；useStore 接线由既有会话生命周期测试守护（曾抓出 startNewChat 缺 flush 的真 bug，已修）。基线 flaky 观察：test_chat_supervisor_uses_langgraph_stub_when_enabled 在门禁轮翻绿。

- 2026-07-04 | WP0-T3 | 前端无 @testing-library（不在白名单不装），spec 的 userEvent 交互测试降级为 renderToStaticMarkup 静态断言（文案正反断言）+ toast 行为代码审查；现有测试需包 ToastProvider（useToast 无 Provider 会 throw）。
- 2026-07-04 | 环境 | 本机直连 pypi/npm 均被断（公司网络），pip 用清华镜像、pnpm 用 npmmirror 镜像安装成功。

- 2026-07-03 | 门禁修订 | 本机全量基线存在 19 个固有失败（已在基线 commit 4a1c055 复验，清单固化于 tests/baseline-failures-4a1c055.txt，16个集中在 test_langgraph_api_stub.py）。硬门禁'全绿'在本机执行为：**无新增失败**（对照基线清单）；服务器/CI 环境仍以全绿为准。

- 2026-07-03 | WP0-T1 | spec 测试代码用 Mock 包装缺 __name__，改为 new=真函数替换（测试写法修正，断言语义不变）。回归范围调整：-k price 全集含真实联网测试在本机超时，回归改跑非联网子集(test_price_fallback_regex/test_session_price/test_validator, 22 passed)；全量基线摸底另行后台执行。

- 2026-07-03 | 环境 | 测试 LLM 端点 http://175.178.159.112/v1 的 /models 正常但 chat completions 全模型报 upstream_error（sub2api 上游故障，有升级镜像修复的前科）。不阻塞 WP0/WP1（LLM-off 路径）；进入需要真 LLM 的环节（WP2 shadow 对拍、部署冒烟）前需复测并提醒主人。
- 2026-07-03 | 环境 | 本地 Python 3.12.10（spec 基线 3.11）：requirements 按 pin 版本安装，若有兼容性问题记录于此。

