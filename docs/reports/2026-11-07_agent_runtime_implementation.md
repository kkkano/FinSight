# 2026-11-07 Agent 运行时实施与验收记录

当前状态：后端agent-20261107-8b809bee23e0、前端独立补丁ui-20261107-9cfdc5be5e05已发布，后端未重启。主发布ready/health200、RAG2228 semantic_ready/pending0/full_ready；公网GitHub按钮与302正确授权跳转通过，未本人登录。最新计算320MiB低于512MiB正确拒绝；公开空记录、候选文字撤回和完整OAuth/研究验收边界保留，Git未提交。

本报告只记录此次工作树的实现与验证证据，不承担架构规范职责。当前事实源仍为 [架构](../01_ARCHITECTURE.md)、[Agent 指南](../AGENTS_GUIDE.md)、[执行事件合同](../execution-event-contract.md) 和 [RAG 架构](../05_RAG_ARCHITECTURE.md)。源码改动仍未提交；本轮使用发布 ID 和镜像/文件哈希追溯，不将该 ID 当作新 Git 提交。

## 当前严格设计与运行时修复（已发布）

| 范围 | 已核对实现与边界 |
|---|---|
| 默认真实思考 | 按新用户授权默认 provider reasoning.delta；单 run 含子 Agent 共 20,000 字符，owner/run/message 私有保存，历史可展开；不进金融证据、引用、普通正文、公开报告或日志。没有字段不编造，旧 opt-in/仅内存策略替代 |
| 工具与正文 | `tool_display.py` 逐项注册 display.target/result，脱敏参数、真实结果预览和来源展开；按 seq 与正文/思考穿插，隐藏重复 `*_model` 活动，不假造百分比 |
| 技能 | `/api/skills` 与输入 `/` 菜单读取 7 个真实 builtin manifest，最多选 3；主/子 Agent 可 discover/use_skill，方法指导不改权限或预算 |
| 普通追问 | 自动沿用同 owner/session 较早终态 run 的有效资料；逐记录 TTL 不续期，最新行情仍重新取数，无常驻继续 CTA 或人造续研问题 |
| 数据与计算 | SEC 平行数组/盈利预期多表适配，series_statistics、多标的共同日期/基准、明确连续下跌规则；拒绝未知参数，不以任意回撤替代连续下跌 |
| 金融语义与正文清理 | metadata guard 不让 unknown 复权/股息和 freshness 变成确定事实；公开正文 DSML 内部标记流式清理，不从文本解析工具；来源投影不复制整张 OHLC 表，原始数据仍在 records |
| 实际行情扩面 | 研究展示按市场日历裁剪一年，修复 Twelve 367 根问题；Yahoo 04:00–20:00 ET 扩展时段、FINRA 通常延迟2–4周的周场外成交；不提供实时暗盘/净流入，不改 forecast 冻结口径 |
| API 与公开战绩 | `/api/auth/providers`、真实公司 profile、范围/ticker/type 和确认 cohort 的只读统计及 metadata；预测核心冻结源码保持原样，provider false 不显示 GitHub 按钮 |
| 七稿逐区块对齐 | Welcome/Dashboard/TrackRecord、对话/思考/工具/图表、历史与单列右栏，保留 README 原 Logo、真实空态与 source/price_levels/引用联动；布局 fixtures 与真实金融图表单独验收 |

### 设计与真实图表证据

- `docs/reports/2026-11-07_page_design_alignment/PAGES_COMPARISON.md` 与 24 张 PNG：三页面桌面/窄屏、亮暗及并排对照；数据为测试接口 fixtures，不是生产金融验收。
- [对话与右栏对照](2026-11-07_chat_design_alignment/README.md) 与 68 张布局 PNG：36 张实现状态、16 张原稿、16 张并排；历史确认、seq 穿插、工具详情、160px 思考区、236px 市场图和真实缺失空态。
- [真实图表渲染](2026-11-07_chat_design_alignment/REAL_CHARTS.md)：直接加载真实模型 artifact 与对应来源投影，ECharts 逐点核验及真实鼠标悬停；不加载候选 terminal 正文，不改数值、额外调用模型或发生产请求。

`.omx/live-charts/REPORT.md`、`final-report.json`：3 例 run 均 completed，核心图表 3/3。AAPL 为 251 个日线点（2025-11-07→2026-11-06）；NVDA/AMD 215 点双线、共同基准2025-12-31，末值独立复算一致；SOXX 主图1322周点、9个连续下跌≥5周区间（8结束/1进行中）。共16次真实模型调用、74446 reported tokens、5752 reasoning字符只计数，0次429重试；没有生产测试会话或原始思考日志，费用不作估算。

该验证使用完整 run_agent_pipeline、限定只读图表工具与匹配生产 API capture 的真实行情，不预构造图表；生产会话/usage归档禁用，仍保留本地 quota。三个候选解释各有未核实扩展推断被撤回，所有 answer_status=partial、quality存在阻断；不能把 completed/core图通过称为全文可靠。

首次三例报告还记录未核实复权/股息措辞、DSML混入正文和小图边界缺点；随后源码加入 metadata semantic guard、分片安全正文清理与来源投影，并有聚焦回归。旧候选与 before 原图继续保存，新守卫通过不等于重新执行过完整付费模型或所有正文已无错误。

SOXX 同一真实 spec/数据的确定性重绘保存在 `chart-soxx-range-fixed.json`、`range-fix-verification.json`：主1322点不变，9区间ISO端点与真实类目对齐，6小图分别6/8/7/6/6/6点，均含前一期真实基准与结束周，额外模型调用0。最终前端实例/悬停/数据表验证见 REAL_CHARTS；unknown价格与股息口径仍显示未注明，百分比不再乘100。

最终会话验证：后端相关410项、真实PG22项（含reasoning owner/20k）、全前端481项通过；终态error覆盖修复后76项聚焦及全481再通过。早先展示/Agent116与各UI lane保留各自范围，所有计数重叠不相加。最终release已部署，真实上线检查如下；不把测试计数或构建完成当作所有功能/模型文字可靠的证明。

### 最终发布与线上接口验收

`.omx/deploy/design-rollout-result.json`记录release `agent-20261107-8b809bee23e0`：活跃研究0后排空旧后端，于18:08 UTC新后端ready后切换前端/watchdog，build ID一致，状态deployed_healthy。当前目录`/home/ubuntu/finsight-releases/agent-20261107-8b809bee23e0`，软链接`/home/ubuntu/finsight-current`；没有重跑已提交的RAG迁移。

`.omx/deploy/design-production-check.json`为18:14 UTC最终生产检查：

| 检查 | 实际结果与适用边界 |
|---|---|
| 主发布/容器 | 8b主发布当时前后端healthy/0restarts/无OOM；后台5c5ee9c…、当时前台410b926f…。最后前端已独立改为9c补丁，不以此行当最终前端镜像 |
| ready/health与RAG | HTTP200、无失败组件、RAG full_ready/2228 semantic_ready/pending0；不代表持续观察期或任意查询质量通过 |
| 登录provider | github/email均true；后续公网按钮跳github.com/login，后端302与callback正确。本人登录及完整OAuth未验收 |
| AAPL公司profile | HTTP200，Apple Inc./NasdaqGS，来源yfinance，真实时点保留 |
| AAPL一年历史 | HTTP200、Twelve Data251根，2025-11-07→2026-11-06，修复展示期数；不当作盘中即时价 |
| 公开战绩 | HTTP200，新范围/cohort metadata正常；28日视图opportunities/predictions/settled/pending均0、daily_series空、next_settlement_date=null。保留空态，不造命中率/曲线 |
| 技能权限 | 匿名请求401是预期权限拒绝；真实7项manifest与认证菜单/主子Agent使用另有本地合同覆盖，不把401记服务失败 |

旧`github-provider-preflight.json`曾为githubfalse/emailtrue，旧DNS/503和cf2d/538b均保留before审计，不能覆盖当前true或健康发布。计算worker物理内存限制仍保留，dispatcher健康不等于成功作业；完整本人OAuth、登录后研究SSE/持久交付、复杂研究质量与持续观察期仍各有未完成边界。

### 最后前端补丁与公网验收

`.omx/deploy/frontend-patch-deployed.json`：后端主release8b不变，前端ui-20261107-9cfdc5be5e05，镜像67ad1071…，status=deployed、backend_restarted=false。功能源码只改TurnActivity及其测试：有保存thinking但缺可信terminal时，不按当前时钟减消息时间伪造历史耗时，只显示已完成/调用数；17项对应单测通过。前端tag配置一并记录于source_changes；补丁源码与镜像/归档hash采用独立patch manifest，不能称所有文件仍与主manifest相同。

`frontend/.omx/artifacts/production-design/result.json`是补丁前主8b的完整公网页面验证：原Logo SHA一致、新首页示意标记、0JS异常，Dashboard无内部来源码、TrackRecord无内部术语且真实空态；GitHub按钮出现并实际导航github.com/login。`.omx/deploy/github-authorize-final.json`另验证302、github.com/login/oauth/authorize和正确Supabase callback；未本人登录或完成OAuth授权。未把补丁17项测试/部署记录冒充重新执行完整浏览器矩阵。

`.omx/deploy/design-compute-check.json`最终复验available320MiB/required512MiB，返回analysis_capacity_insufficient，正确拒绝，未调低安全门禁。

`.omx/deploy/design-cleanup-final.json`确认最终backend8b/frontend9c均healthy、RAG full_ready；删除2个无容器引用的中间前端镜像，保留当前与有效回滚点。清理本轮导入镜像压缩包406,946,522字节，数据库卷删除0，根盘可用7.9GiB/80%。这批字节属于本轮临时导入包，不能称为同等原有垃圾净释放；旧上传包、停用BGE权重与各次新导入包按类别分别记录。

发布结论：严格设计与运行时修复已发布，基础设施、真实公司/日线、公开metadata与权限边界检查通过；真实图表核心3/3、9/9 Mermaid实际parse/render通过。候选解释被撤回事实不变，不声称全部文字可靠或所有外部验收完成；Git未提交，文档以独立overlay同步，不改业务/source manifest。

文档收口归档两份被当前原生规范替代的旧LangGraph硬约束，映射及历史边界见 [2026-11-07归档](../archive/2026-11-07_agent-runtime-design-closeout/README.md)；原Logo和七份设计资产未改。当前README/架构/Agent/RAG/执行事件与运维图保持一致，归档不覆盖现行权限。

文档校验覆盖19份README/当前规范/本次归档、99个本地链接、130个非忽略路径，9/9 Mermaid实际parse/render与最终图定义一致。主manifest曾核验代码差异0；随后TurnActivity/test及前端tag配置由9c独立patch manifest追溯，不能继续声称全源码仍与主manifest相同。文档overlay不改业务/source manifest；本地Mermaid记录为`.omx/mermaid-validation/SUMMARY.md`与`result.json`。

## 初版实现与验收（before 历史）

以下记录首次发布及 Logo 补丁时的实现/环境，保留原证据供审计。早期 opt-in 思考、DNS/503 和待部署措辞不代表上方当前修复合同；当前状态以上方为准。

### 初版已实现并核对源码

| 范围 | 本轮实现与核对入口 |
|---|---|
| 默认研究路径 | `backend/agent_runtime/config.py` 默认 `FINSIGHT_RESEARCH_RUNTIME=agent`；`execution_router.py` 接原生循环，显式 legacy 仍保留六节点图 |
| 模型与研究循环 | `model.py`、`loop.py`、`tools.py` 实际流式原生工具调用、工具能力预检、动态发现/启用、同轮取数合并、专业角色同循环与定向消息 |
| 预算与上下文 | `context.py`、`limits.py` 资料压缩/回读、token 预留、模型/取数/研究分层租约；等待专业结果释放模型槽 |
| 保存与恢复 | `service.py`、`research_run_store.py` 保存已提交 blocks、水位和终态，恢复先送 snapshot；终态后旧 checkpoint 不能覆盖正文，读取不重跑付费研究 |
| 追加要求与续研 | `/api/execute/runs/{run_id}/instructions` 在模型边界应用；新 run 的 `resume_from_run_id` 校验 owner/session，复用未过期原始资料 |
| 操作权限 | `permissions.py`、`actions.py`、确认 API 保存并校验 payload hash 与持久收据；完整用户操作指令可复用授权，数据与同伴消息不能授权 |
| 金融计算与核验 | `analysis.py`、`grounding.py` 与共享 `grounded_quantities.py`；真实 dataset 计算与图表，数值/币种/期间/主体/来源绑定，未核验段落明确移除，质量不足报告保留预览 |
| 独立计算 | `backend/analysis_worker/`、`Dockerfile.compute` 双 target、Compose `compute` profile；dispatcher 与每个隔离 job 分开，未配置不在 API 进程执行开放代码 |
| 知识工具 | `backend/rag/tools.py` 按需检索/回读、KB 授权票据与 CJK 词法；默认 lexical、可选托管 API/私网 BGE，向量 identity/维数核验与明确降级 |
| 依赖拆分 | API 使用 `requirements-runtime.txt`；本地 ML 使用独立 requirements 与 `local-ml` 镜像，计算 worker 依赖另列 |
| 前端交付 | Claude 七画板方向、当前 run 活动侧栏、正文/artifact/action blocks、小图、追加要求/停止/确认/续研；provider 原始 reasoning 显式开启且仅页面内存；GitHub 登录入口按 provider 配置显示 |

原始资料缓存为 `FINSIGHT_ARTIFACT_DIR` 下的 owner/session/run 文件，12 小时有效；操作收据和额度租约分别使用 `FINSIGHT_ACTION_STORE`、`FINSIGHT_RUNTIME_QUOTA_DB` 的 SQLite 文件。会话、权威正文、checkpoint/终态和自选数据仍由 PostgreSQL 保存。这些本地持久机制不构成多机调度或自动恢复执行能力。

## 本地验证证据

下表的测试数量来自本轮实施代理的会话执行汇总；广泛测试未生成持久日志，不提供虚构日志链接。文档收口核对源码、冒烟 JSON、依赖解析报告、冻结文件身份及当前工作树启动脚本帮助，不重复运行已通过的广泛套件。

| 验证 | 已记录结果 | 适用边界 |
|---|---|---|
| 后端广泛兼容回归 | 2633 passed、19 skipped、9 warnings，75.43 秒 | 在隔离 `.omx/runtime-venv`、`FINSIGHT_RESEARCH_RUNTIME=legacy` 下执行；不代表原生所有外部链路通过 |
| 原生运行时与交付聚焦 | 106 passed | 覆盖原生工具流、资料/权限/预算、事件身份与交付合同；模型/供应商主要为可控 fixtures |
| 最新权限/原生/交付/安全聚焦 | 77 passed，4.01 秒 | 后续权限收口的会话执行结果；与前面的聚焦和广泛结果存在重叠，不相加 |
| 后续原生/交付/模型/图片聚焦 | 99 passed；之后原生/交付54 passed | 包含图片协议、选区限制、资料续研、错误与引用修正等增量；不与前述计数相加 |
| 真实 PostgreSQL | 13 passed、0 skipped，2.15秒 | PostgreSQL 17.11/UTF8、独立测试库、非superuser且无BYPASSRLS角色；8项原有＋5项checkpoint、COMMIT失败回滚测试 |
| 最终前端单测 | 65文件、437 passed | 附件输入等增量完成后运行；后续小改按13项图表/PNG聚焦及TypeScript验证 |
| 独立计算 worker | 52 passed、0 skipped，18.35 秒 | 46 项模拟协议/边界单测与 6 项真实容器验收；WSL 独立 Docker daemon，真实 uvicorn HTTP `/health` 和鉴权 `/jobs` 通过 |
| 真实向量与重排 | 8 条标注查询，重排后 Recall@3 / nDCG@3 均为 1.0000 | SiliconFlow BGE-M3 1024 维、BGE reranker 和 pgvector；21 条合成金融/隔离记录，不外推生产质量 |
| 长文真实向量 | 19 个索引单元均保存真实 1024 维向量 | 36,454 字符原文无损分块与票据回读；两条父原文无向量、正文保持不变 |
| 存量迁移副本与生产 | semantic_ready / indexable 均为 2228，pending=0 | 副本无损/权限守卫验证后，生产迁移事务已提交；生产存量检索与回读通过 |
| 前端广泛单测 | 418 passed | 本地前端合同与组件验证；后续聚焦测试和至少 25 条不同 E2E 路径也已通过 |
| 冻结预测源码 | 6/6 文件与 `a5103511` 的 Git blob 一致 | TechnicalAgent、RiskAgent、forecasting、prediction_runner、prediction_store、agent_prediction_store；固定 US20 未改 |
| 运行依赖与最终镜像 | 142 个解析包未含五类重型 ML 包；最终 API 镜像 `local_ml_absent=true` | `.omx/runtime-dependency-report.json`、`.omx/deploy/final-images.json`；最终 API、前端、计算 job/dispatcher 镜像已构建并发布 |
| 启动脚本 | `scripts/run_agent_runtime.py --help` 成功 | 使用当前工作树 `.omx/runtime-venv/Scripts/python.exe`；只验证参数解析，未加载真实配置或启动持久服务 |

首轮广泛测试在约 1100 项通过后因本地缺 `pandas_market_calendars` 停止，随后隔离环境补齐项目指定 pandas 2.3.3 / market-calendars 5.4，完成上表回归。首次停止属于测试依赖缺口，不能记作业务回归缺陷，也不能与最终成绩相加。

前端截图位于工作树 `frontend/.omx/artifacts/ui-overhaul/`，包括 Chat、Welcome、Dashboard、公开战绩的桌面/移动/明暗主题及事件窗口小图。截图使用明确 fixtures，不是线上数据或真实金融质量证明；本地被忽略的证据目录不作为已发布资料链接。

## 真实模型冒烟

研究端点 `https://api.llm.pm/v1` 的 `deepseek-v4.1-flash-1017` 已完成模型目录检查与流式原生工具调用预检。真实凭据仅由被忽略的本地配置引用，本报告不记录凭据内容。

| 用例 | 证据与结果 | 验收结论 |
|---|---|---|
| 模型 → 日期工具 → 回答 | `.omx/live-runtime-smoke.json`：1 次日期工具、2 次模型调用、53.81 秒、5510 tokens，答案引用实际工具返回时间 | 真实模型原生调用闭环与流式协议通过；该单例不代表金融任务质量或延迟目标通过 |
| AAPL 当前报价 | `.omx/live-financial-agent-smoke.json`：1 次报价工具超时、source_count=0，模型明确无数据且未编造价格 | 缺失披露行为通过；真实行情取数验收未通过，不能将 JSON 的 `success=true` 当作报价成功 |
| 两个专业 Agent | `.omx/live-multi-agent-smoke.json`：technical/risk两个任务实际完成并汇总，24.83秒、14437 tokens | 真实协作与等待闭环通过；共用日期缓存不算两个独立金融来源 |
| 图片协议 | `.omx/live-vision-capability.json`：HTTP200，4.33秒，正确返回合成PNG的左红右蓝 | 验证图片传输和简单识别，不等于金融图表数字/OCR准确率通过 |
| 补依赖后的行情复验 | `.omx/live-quote-environment-check.json`：33.99秒，仍为market_data_unavailable | 明确行情网络/来源问题仍未解决，不生成模拟价格 |
| 发布后 AAPL 报价 | `.omx/deploy/production-market-smoke.json`：HTTP 200、4.979 秒，twelve_data，USD，`data_kind=daily_close`，来源日期 2026-11-06 | 真实日收盘报价通过；不是即时现价，不能覆盖此前开发网络失败记录或外推全部行情能力 |

研究服务现支持最多3张PNG、每张2MiB、800万像素、单边8192px，仅用于当前轮；图片不进入普通会话历史和原始资料缓存。精确数值分析仍需真实底层数据。原始provider推理默认不展示/不持久化。冷模型能力校验先发送SSE验证活动，未通过时用错误事件拒绝，不启动研究工具，避免HTTP入口长时间没有进展。

真实数据库专项日志与摘要保存在 `.omx/pg-test/pytest.log`、`pytest-results.xml`、`verification-summary.json`。该专项实例只监听本机15432，验收后已停止、端口释放；专项测试没有访问生产数据库。原始测试文件已保存为 `backend/tests/test_runtime_checkpoint_postgres.py`。会话测试与模型冒烟汇总为 `.omx/verification_summary.json`。

## 真实向量、长文与存量迁移

SiliconFlow 独立凭据现已安全配置并用于实际 embedding 与 rerank，请求没有使用模拟传输、hash 向量或本地 ML。默认无配置路径仍保留 lexical/none；真实验收使用显式托管 API 配置，不能把默认值当作此次实际运行模式。

`.omx/live-vector/summary.md` 与 `postgres-long-eval.json` 记录 pgvector 0.8.7 和 8 条中英文标注查询：混合检索 Recall@3=0.5000、nDCG@3=0.4759，真实重排后均为 1.0000。owner/session、TTL、时间窗、来源、实体过滤和票据正文回读通过。21 条合成金融/隔离记录和 8 条查询只证明该链路与这些标注案例，不代表任意金融任务质量或生产规模性能。

长文补验保存 36,454 字符、89,786 UTF-8 字节原文：存量准备产生 16 个分块，新摄取产生 3 个分块，19 个索引单元全部使用真实 1024 维向量，最大块 5984 字节。两条父原文保持完整且向量为空，分页票据回读逐字一致，索引 pending=0。

`.omx/rag-migration/DELIVERY.md` 记录本机生产数据副本：原记录 2409，原 active 1941、expired 468；保留 76 条长文原文并新增 363 个无损片段，最终 active 2304，其中 indexable / semantic_ready 均为 2228。400 次真实 API 调用无失败，原文和非索引字段守卫、过期整行哈希、权限/日期继承及副本 IVFFlat 重建验证通过。TEMP 目标上的 COPY/应用首次插入 363 个片段，重复执行新增 0，正文、owner 或父哈希变动被拒绝；该验证事务已回滚。

迁移包上传与哈希记录于 `.omx/deploy/uploaded-artifacts.json`，生产事务提交记录于 `rollout-result.json`。`.omx/deploy/production-rag-smoke.json` 验证生产存量文档：8 个语义命中、3 个重排结果、完整原文回读一致，耗时 0.686 秒，indexable / semantic_ready=2228、pending=0；没有插入生产测试文档。该服务器内部烟测证明这次存量检索与回读链路，不能替代登录用户 HTTP 研究流或生产规模质量评估。

## 真实计算隔离

`.omx/compute-live/SUMMARY.md` 记录 WSL Debian 独立 Docker 29.9.3 daemon 上的双镜像构建、52 项测试与实际 HTTP 请求。真实容器使用 UID 65532，不能外网访问、读取主服务 token 或 Docker socket、写根目录/输入，下一任务看不到前一任务临时文件；超时和取消后所属容器、输入卷均为零。

10,000 行 Pandas 小算例在 192/256 MiB job 下通过，进程 RSS 峰值约 76 MiB；实际 HTTP worker 冷启动约 2.83 秒，小作业约 1.81 秒。真实低内存保留配置拒绝作业且不创建资源。上述只支持有界小算例，不能承诺任意代码容量。生产 dispatcher 已启动且健康；`production-compute-smoke.jsonl` 实测可用内存 414 MiB、要求 512 MiB，返回 `analysis_capacity_insufficient`，正确拒绝计算，未将资源不足伪装为作业成功。

## 首次发布时的服务器准备与清理（before）

服务器 SSH 已通过 `ubuntu` 账号接通；先前认证失败已解除。`.omx/deploy/preflight-inventory.json` 记录预检时旧服务使用 `a5103511`，总内存 3399 MiB、可用 372 MiB，swap 2047 MiB 已用 1977 MiB。发布后计算门禁实测为 414/512 MiB，仍不满足运行要求；不能把 dispatcher 健康当作计算作业可用。

首次发布快照 `.omx/deploy/final-state.json`：当时可用内存309 MiB，swap1734/2047 MiB；backend运行/0重启/无OOM，Docker health因认证故障unhealthy，其他服务healthy、RAGfull_ready。414 MiB是更早计算探针值；该快照不是恢复后当前故障或资源状态。

`.omx/deploy/auth-egress-probe.json` 记录当时Supabase NXDOMAIN与旧容器配置一致；该故障不是本轮新版本造成，随后已恢复，恢复后的provider/ready证据见上方。

用户授权下的定向清理已完成：`.omx/deploy/cleanup-result.json` 记录删除 25 个过时 FinSight 上传包，共 120,902,409 字节；镜像删除数为 0，所有当前镜像仍被引用。有效回滚版本、审计目录、持久卷与其他项目保留。

早期final-cleanup-result.json记录删除停用BGE权重与当次新导入gzip共2,767,091,762字节；加旧上传包合计删除2,887,994,171字节。该合计含当次临时导入包，不代表等量原有垃圾净释放；当时镜像删除0/卷删除0、根盘7.8GiB，最新清理与7.9GiB状态见上方design-cleanup-final。旧rag容器移除，再启local-ml需重下BGE，其他项目不在范围。

回滚镜像、安全配置、原始文档与向量回滚 SQL 已保留。`.omx/rag-migration/rollback-validation.json` 的真实 PostgreSQL TEMP 目标演练恢复全部 2409 条原记录，仅精确删除此次迁移的 363 个新片段，保留无关新增记录，重复执行幂等；owner、后续向量身份或片段内容变化会被拒绝。验证事务已回滚，不是生产服务已执行版本回滚。自包含回滚包为 `.omx/rag-migration/rollback-package.tar.gz`。

## 首次发布与 Logo 补丁结果（before）

发布目录为 `/home/ubuntu/finsight-releases/agent-20261107-cf2d9330cb94`，当前软链接为 `/home/ubuntu/finsight-current`。`.omx/deploy/final-images.json` 保存最终四个镜像与导入归档哈希；`rollout-result.json` 状态为 `deployed_external_auth_degraded`，记录迁移提交、新后端和其余服务启动。

`.omx/deploy/final-integrity.json` 确认三类研究/embedding/rerank 凭据与用户给定安全配置一致，首次发布源码与部署快照一致（文档更新除外）；随后 Logo/Compose 前端版本修订单独由 `frontend-patch-deployed.json` 追踪，Git 未提交；只保留匹配布尔值，不输出凭据。

| 生产检查 | 结果 | 可得结论与限制 |
|---|---|---|
| 公网 Edge 前端 | `frontend/.omx/artifacts/live-deployment/result.json`：HTTP 200、新 build ID、0 JS 错误，GitHub 入口关闭 | 新前端已交付；不代表 OTP/OAuth 登录或完整聊天链路通过 |
| 初版 `/readyz` 与 `/health` | 当时HTTP503，仅authentication auth_verifier_unavailable | 当时Supabase NXDOMAIN未解除，保持鉴权；随后恢复，最终新发布为200，不能把本行当当前状态 |
| 存量生产 RAG | 8 个语义命中、3 个重排结果、原文回读一致，0.686 秒，2228 ready / 0 pending | 真实向量链路通过；未插入生产测试文档，不证明任意查询质量 |
| AAPL 公开报价 | HTTP 200、twelve_data、4.979 秒、2026-11-06 `daily_close` | 真实日收盘数据通过，不是即时现价 |
| 计算 dispatcher / 作业 | dispatcher 健康；414 MiB 可用低于 512 MiB 要求，拒绝作业 | 资源门禁通过，生产计算仍不可用 |
| 线上 HTTP 研究 | 服务器没有既有内部 API key，未执行烟测；普通登录受认证故障影响 | 不宣称线上 SSE、研究终态持久交付或普通登录通过；本机真实模型/PG 专项证据仍有效 |
| 前端 Logo 独立补丁 | 前端 `ui-20261107-538b0293185e`；恢复 a5103511 / README 原橙蓝 K 线 F 图，五处资产/引用更新，内容版本参数避免旧缓存；构建及公网浏览器通过 | 后端继续 `agent-20261107-cf2d9330cb94`，补丁确认未重启后端；GitHub 入口仍按 provider 配置关闭 |

## 保留验收限制

- Supabase旧故障已恢复且ready/health200；真实用户OTP/OAuth与新版本线上SSE/持久交付组合仍需实际会话，不能仅凭探针标通过。
- 生产计算服务已启动，门禁按实际内存拒绝作业；成功作业与更大输入容量仍未通过，私网 local-ml 真推理未验证。
- GitHub provider现已配置，按钮/授权跳转与完整本人OAuth授权分开记录；provider true不等于本人授权或登录后完整研究链路通过。
- AAPL 日收盘报价以外的金融取数、复杂研究题独立质量/性能和金融图片数值/OCR 精度仍待补；小样本、前端 fixtures 和协议冒烟不能替代。
- 回滚包与真实 PG 数据回滚演练已验证；生产整套服务回滚演练、真实账号 canary 与持续观察期尚未完成。
- Git 仍未提交或推送，不将已部署发布 ID 当作新 Git 提交，也不将全部计划或 P9 勾为完成。

### 首次发布结论（历史）

首次版本与生产迁移发布、公开前端/存量RAG/日收盘通过，当时认证与计算均降级，后来认证恢复；该历史不替代上方8b809bee23e0的最终健康发布及其独立验收边界。

部署前会先核对实际Compose项目、当前release/镜像/卷和可用资源；保留当前版本与有效回滚点，只清理可归属FinSight且确认不再使用的产物。不会使用全局Docker清空替代定向清理。原始资料缓存仅清理自身标记的过期文件，默认512MiB写入预算，不删除会话/报告/数据库。

本地启动入口仍为 `scripts/run_agent_runtime.py` 和工作树 `.omx/runtime-venv/Scripts/python.exe`，帮助与真实PG专项已验证；文档变更不需重启，新默认思考/技能/工具展示等业务修复要在下一发布后加载与验收。
