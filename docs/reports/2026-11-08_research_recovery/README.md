# 研究恢复与发布验收

本目录记录原会话中新闻、补查和研究完成度修复的展示层验收。所有截图中的会话、行情和战绩均为明确的界面测试样本，不代表真实投资结论或线上战绩。实际供应商与模型验收由独立研究验收记录确认。

当前发布与真实研究结果见 [LIVE_RESEARCH.md](LIVE_RESEARCH.md)，逐题运行标识见 [LIVE_RESEARCH.json](LIVE_RESEARCH.json)。

已上线版本：`agent-20261108-365a20081c6b`，源码：`ddee6360`。公网与生产容器内三项研究检查均已通过；验证边界见发布记录。

## 当前行为

- 新闻来源仍可直接打开原文。行情、财报与计算来源可展开查看实际保存的供应商、时间、货币、数据口径和计算参数；有原始地址时同时提供原文入口。
- 正文引用会打开右栏、定位来源并展开数据详情。没有股票标的的宏观研究也能查看来源。
- 新回复在后端展示投影中清理内部资料编号；旧历史在前端渲染时做同样处理，不修改已保存数据，保留金融数值、有效来源引用、URL和代码围栏。
- 首页标题使用“你只管问，剩下的交给 FinSight。”；侧栏保留整体折叠、分组折叠、前八条截断、当前会话补位、原始标题提示和删除入口。
- 战绩没有到期样本时隐藏四宫格；已有样本时显示实际计数，包括 `0`。

## 验证

- 前端全量 Vitest：74 个文件、514 项通过。原用户指定的文案、历史、侧栏和战绩定向范围已覆盖；没有删除或跳过断言。
- `npx tsc --noEmit`、`npx tsc -b --pretty false` 通过。
- `npm run build` 通过。本地验证构建使用 `local` 标识，发布产物需由最终发布流程重新生成。
- Playwright 来源、欢迎页和战绩页：6 项通过。来源覆盖亮色和暗色的无链接详情、数据来源原文入口、新闻原文链接、正文引用定位、宏观来源以及旧消息编号清理。
- 侧栏视觉检查覆盖四个组合（改前/改后与亮色/暗色），并实际操作整体折叠及刷新持久化、分组、选中补位、删除取消和手机紧凑侧栏。预警空态与有数据态两项通过，明细见 [visual-result.json](visual-result.json)。
- 后端 `test_runtime_presentation.py` 与 `test_runtime_answer_verification.py`：155 项通过，包含新增的内部编号清理、金融数值与来源保留、URL/代码不改写回归。

## 截图与文案

| 内容 | 证据 |
|---|---|
| 来源详情，亮色 | [sources-light.png](sources-light.png) |
| 来源详情，暗色 | [sources-dark.png](sources-dark.png) |
| 侧栏改前/改后，亮色 | [sidebar-comparison-light.png](sidebar-comparison-light.png) |
| 侧栏改前/改后，暗色 | [sidebar-comparison-dark.png](sidebar-comparison-dark.png) |
| 预警无到期样本 | [track-empty.png](track-empty.png) |
| 预警有数据，保留零值 | [track-data.png](track-data.png) |
| 按页面分组的原文/新文案 | [COPY_REVIEW.md](COPY_REVIEW.md) |

改前侧栏来自原会话在修改前保存的真实组件；改后侧栏来自本轮源码。两者使用同一组测试会话。待确认文案：无。
