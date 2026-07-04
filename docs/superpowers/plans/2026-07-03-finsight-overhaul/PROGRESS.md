# 执行进度账本（唯一进度事实源）

| 日期 | 任务 | commit | 测试结果 |
|------|------|--------|----------|
| 2026-07-04 | WP0-Task3 隐私声明+Toast | 8805746 | vitest 2 passed(反向验证旧文案FAIL) |
| 2026-07-04 | WP0-Task6 端口绑回环 | a331686 | cloudflared token模式ingress指宿主localhost,兼容已核实 |
| 2026-07-04 | WP0-Task7 .bak清理 | d7e959b | git rm + gitignore |
| 2026-07-04 | WP0-Task8 drill护栏 | 6ce6f61 | 新测2 passed+drill回归9 passed |
| 2026-07-03 | WP0-Task2 main.py重复import | afa2d56 | main import OK；全量基线1839 passed/19 failed(基线固有) |
| 2026-07-03 | WP0-Task1 price.py级联bug | 79ffdfd | 新测2 passed(旧实现复验FAIL)+回归22 passed |

## Installed Dependencies

## Deviations

- 2026-07-04 | WP0-T3 | 前端无 @testing-library（不在白名单不装），spec 的 userEvent 交互测试降级为 renderToStaticMarkup 静态断言（文案正反断言）+ toast 行为代码审查；现有测试需包 ToastProvider（useToast 无 Provider 会 throw）。
- 2026-07-04 | 环境 | 本机直连 pypi/npm 均被断（公司网络），pip 用清华镜像、pnpm 用 npmmirror 镜像安装成功。

- 2026-07-03 | 门禁修订 | 本机全量基线存在 19 个固有失败（已在基线 commit 4a1c055 复验，清单固化于 tests/baseline-failures-4a1c055.txt，16个集中在 test_langgraph_api_stub.py）。硬门禁'全绿'在本机执行为：**无新增失败**（对照基线清单）；服务器/CI 环境仍以全绿为准。

- 2026-07-03 | WP0-T1 | spec 测试代码用 Mock 包装缺 __name__，改为 new=真函数替换（测试写法修正，断言语义不变）。回归范围调整：-k price 全集含真实联网测试在本机超时，回归改跑非联网子集(test_price_fallback_regex/test_session_price/test_validator, 22 passed)；全量基线摸底另行后台执行。

- 2026-07-03 | 环境 | 测试 LLM 端点 http://175.178.159.112/v1 的 /models 正常但 chat completions 全模型报 upstream_error（sub2api 上游故障，有升级镜像修复的前科）。不阻塞 WP0/WP1（LLM-off 路径）；进入需要真 LLM 的环节（WP2 shadow 对拍、部署冒烟）前需复测并提醒主人。
- 2026-07-03 | 环境 | 本地 Python 3.12.10（spec 基线 3.11）：requirements 按 pin 版本安装，若有兼容性问题记录于此。

