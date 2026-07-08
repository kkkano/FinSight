# 执行进度账本（唯一进度事实源）

| 日期 | 任务 | commit | 测试结果 |
|------|------|--------|----------|
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

## Deviations

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

