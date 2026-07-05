# 执行进度账本（唯一进度事实源）

| 日期 | 任务 | commit | 测试结果 |
|------|------|--------|----------|
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

