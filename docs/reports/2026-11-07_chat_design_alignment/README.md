# 对话、研究过程、图表、标的面板与历史：设计对照

本目录为 2026-11-07 的本地实现验收证据。本页布局截图使用独立的固定验收数据与模型回执，不代表真实行情或投资结论；生产没有导入原稿里的价格、胜率、来源条数等示例值。后续 `real-chart-*` 文件使用真实模型产物，见[真实图表渲染验收](REAL_CHARTS.md)。

本页保留早期布局对照；后续自然文案、progress/answer 分离、图标与来源去重的当前验收见[结果、过程与图标](RESULT_PROCESS_ICONS.md)。不要用旧截图中的措辞或旧来源计数替代新实现的检查。

已逐块读取 `Main.dc.html`、`Streaming.dc.html`、`ChatChart.dc.html`、`RightPanel.dc.html` 的 HTML、CSS 和默认渲染参数。对照范围包括 DOM 层级、宽度、留白、字号、工具行、输入框、图表与亮暗 token，未仅按配色模仿。

原稿缺少它引用的 `support.js`。`frontend/e2e/helpers/designReference.ts` 只执行仓库原稿自带的 `renderVals`、默认 props，并展开 `sc-if/sc-for` 与文本插值；不修改设计资产。外部 Google 字体不加载，保留系统字体回退。原稿没有完整手机交互，窄屏实现按本轮用户要求使用 56px 导航与全屏标的抽屉。

## 截图矩阵

桌面视口为 **1440×960**，窄屏为 **390×960**，均有亮暗两套。本节布局对照共 68 张 PNG：36 张实现状态、16 张原稿、16 张并排对照。并排图左侧为原稿，右侧为实现；因真实工作量和数据不同，不以逐像素相同冒充验收。

| 对照 | 桌面亮色 | 桌面深色 | 窄屏亮色 | 窄屏深色 |
| --- | --- | --- | --- | --- |
| Main | [并排](compare-main-light-wide.png) | [并排](compare-main-dark-wide.png) | [并排](compare-main-light-narrow.png) | [并排](compare-main-dark-narrow.png) |
| Streaming | [并排](compare-streaming-light-wide.png) | [并排](compare-streaming-dark-wide.png) | [并排](compare-streaming-light-narrow.png) | [并排](compare-streaming-dark-narrow.png) |
| ChatChart | [并排](compare-chatchart-light-wide.png) | [并排](compare-chatchart-dark-wide.png) | [并排](compare-chatchart-light-narrow.png) | [并排](compare-chatchart-dark-narrow.png) |
| RightPanel | [并排](compare-rightpanel-light-wide.png) | [并排](compare-rightpanel-dark-wide.png) | [并排](compare-rightpanel-light-narrow.png) | [并排](compare-rightpanel-dark-narrow.png) |

补充状态分别保存为 `panel-empty-*`、`panel-failure-*`、`history-*`、`history-delete-confirm-*`。历史截图通过 SPA 导航保留已完成的实际测试会话，未用空列表代替历史验收。

## 逐块差异表

| 设计元素 | 实现位置 | 对照结果 / 差异原因 |
| --- | --- | --- |
| 浅底侧栏 220–264px、品牌、导航、最近对话、设置 | `Sidebar.tsx` | 桌面 240px，位于原稿允许范围；窄屏折叠 56px、展开 240px。保留用户要求的原橙蓝 K 线 F logo，未复制原稿蓝底字母 F 占位图。保留已实现的搜索/今日/历史入口；不复制无实际数据的提醒计数。 |
| hist 13px、7px/10px 留白、圆角 7px | `Sidebar.tsx` | 对齐。当前会话为 surface + shadow；删除图标 14px，仅 hover/focus 显示，窄屏可直接操作。 |
| 今天/昨天/7天内/更早分组 | `conversationHistory.ts`、`ConversationHistoryPanel.tsx` | 按本地日历日分组；空欢迎占位不加入历史。标题保留第一轮问题的最多 20 字回退。 |
| Header 标题 14.5px、轮次/时间 12px | `ChatWorkspace.tsx` | 使用实际用户轮数及消息时间。未提供的分享、原型提醒等操作不增加空按钮。 |
| 正文最大 760px，图表可扩到 920px | `ChatDesign.module.css`、`ChatList.tsx` | 已分别限制；带图消息的文字不会随图拉宽。用户消息最大 80%，padding 10px/14px，圆角 14/14/4/14。 |
| 消息间距与段落 | `ChatDesign.module.css` | 消息组间距 28px，回答内部 gap 14px；正文 14.5px、1.75 行高。首次提问后移除欢迎占位，不让其额外挤占研究正文。 |
| Claude 风格真实思考块 | `ReasoningBlock.tsx`、`researchStream.ts` | 默认接收供应商字段；运行时最多 160px 内滚、13px/1.6、左 2px line-2，随新内容滚动；结束收起，历史可展开。单 run（含子 Agent）总量 20,000 字符并标记截断。没有字段不制造思考内容。 |
| 工具行 18px / auto / minmax(0,1fr) / auto / 16px | `TurnActivity.tsx`、`ChatDesign.module.css` | gap 10px，desktop 行高 34px，触屏点击区至少 44px；后端 `display.target/result` 构成短行，真实时长及成功/失败状态在右侧。类别按取数 amber、计算 violet、绘图 teal、搜索阅读及 Agent accent。 |
| 参数与关键结果展开 | `TurnActivity.tsx` | 参数/结果并排自适应，KV/列表各最多 10 行；来源为真实标题与链接，失败原因和恢复建议优先显示。不再铺 JSON 树。旧调用未保存详情时明确说明。 |
| 工具、思考、正文顺序 | `messageTimeline.ts`、`ChatList.tsx` | 用 block 首次 seq 和活动首次 seq 穿插；连续工具合组，Agent 子活动可展开。普通 `*_model` 占位活动隐藏，真实失败/重试活动可保留。无 seq 的旧消息仅保留既有顺序。 |
| 双行输入框、底部动作条 | `ChatInput.tsx`、`ChatDesign.module.css` | max 760px、圆角 14px、padding 10/10/8/14；附件/深度研究/真实模型选择/发送在底条。运行中追加与停止仍可用，未完成时不显示复制/重试/下载操作。`/` 真技能菜单继续可用。 |
| 自然续聊 | `useChatStream.ts`、`ChatList.tsx` | 不复活原稿“从这里继续”按钮及人造续研问题；普通追问由服务端沿用资料，真实失败原位重试保留原 query、技能与失败 run 的恢复标识。 |
| ChatChart 卡片 | `ResearchArtifactView.tsx` | 标题、来源/时间副标题、主图、实际存在的区间小图、来源 footer、折叠“查看代码和数据”。字号、12px 圆角、header 12px/16px 留白已对齐；数据为空不给演示曲线。 |
| 右栏单列与顶部 chips | `RightPanel.tsx`、`RightPanelHeader.tsx` | 无图表/详情/战绩 tabs，无 autoSwitch/userPinnedTab；420px 默认、360–520px 拖拽保留。顶部 12px/16px、gap 8px，28px 高 ticker chips 在同一行横滚。 |
| 公司、交易所、价格与来源 | `RightPanelMarket.tsx`、`useCompanyProfile.ts` | 使用共享真实公司 profile，名称/交易所不可得时只显示已有 ticker。价格 28px/500，涨跌 14px，日期/口径/人类来源名在第三行。`sourceDisplayName` 统一供应商及适配器名称，不展示 snake_case。 |
| 236px 市场图 | `contextChart.ts` | 右侧 y 轴、细网格、20 日均线 1.4px amber、底部成交量透明度 .35；只 inside zoom，没有 slider。K线/折线及 1月/3月/6月/1年按钮为紧凑分组。 |
| 对话价位、财报竖线 | `RightPanel.tsx`、`contextChart.ts` | 只有后端本轮验证过的 `price_levels` 且 ticker 匹配才画 violet 虚线/标签；前端不猜价位。当前聚合接口没有真实 `event_calendar`，因此截图未画原稿的财报竖线，这是明确的数据差异。 |
| 指标 3×3 | `RightPanelMarket.tsx` | gap 12px/10px、上分隔线 padding 12px；值来自真实 OHLC、valuation/company profile；缺失超过半数只显示已有项，少量缺失为 — 并附原因。没有“交易日66”等非设计占位统计。 |
| 来源角标与右栏引用 | `researchCitations.ts`、`citationNavigation.ts`、`RightPanel.tsx` | source_id 一一绑定；正文角标打开右栏并滚动/高亮 1.5 秒，右栏来源在新页打开原文。无引用时不显示此区。 |
| 个人预测记录入口 | `RightPanelMarket.tsx` | 仅个人 API 返回该 ticker 实际记录才显示；跳 `scope=personal`，不与公共基准账本混用。无记录隐藏。 |
| 空态、失败、历史确认 | `RightPanel.tsx`、`ConversationDeleteDialog.tsx` | 空态示例仅填输入，不自动发研究；行情失败显示原因与重试，无空画布。历史删除使用项目内确认弹层与 Escape/焦点控制，禁止 `window.confirm`。 |
| 亮暗与窄屏 | 两份局部 CSS module + 全局 t-* | 使用另一 UI lane 补齐的原稿 token；侧栏背景、line/line-2、accent-soft、amber/violet/teal 均复用。窄屏抽屉是用户要求的交互适配，未照抄原稿静态最小高度导致横向溢出。 |

## 验证

- 13 个聚焦单测文件首轮 **85 passed**；随后新增的 legacy Agent 完成事件回归通过，当前本 lane 覆盖共 86 项。涉及的范围包含流式恢复、默认思考/20k 截断、seq 穿插、工具详情、图表、历史、来源、技能兼容。
- 对照截图与交互：`chat-design-alignment.spec.ts` 的 4 组宽窄/亮暗通过，验证 160px 思考区、236px 图、正文先于工具的 DOM 次序、来源高亮、自定义删除确认、空态/行情失败和页面不横溢。
- 既有技能菜单 3 项通过；旧右栏专家页签测试改为对话活动、周期/图型和窄屏抽屉测试，相关 4 项已通过。
- 本机未安装 Playwright 指定的 Chromium bundle，使用已安装的 Edge headless；没有安装全局包或修改系统配置。
- 构建/部署由主代理统一执行。本 lane 未提交 Git。
