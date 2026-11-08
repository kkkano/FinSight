# Claude 对话与研究界面参考快照

状态：**视觉参考，非运行页面，非真实金融数据**。

这份快照来自用户指定的 Claude 会话 30e9db27-85e3-4125-b57b-adaa69fe415f。用户在当前讨论中明确认可其大部分样式，尤其对话部分。保存日期为 2026-11-06（America/Los_Angeles）。

在线交互画布：[FinSight 对话改造](https://claude.ai/artifact/XGaESQcceGvooyd265AUED)。

## 使用方式

- 详细实施计划属于本地任务输入，由任务入口显式提供；这里不链接被忽略的计划。实施副本放在 B 工作树的 .omx/plans/，不作为Git文档索引条目。
- 设计决策与组件合同见 [DESIGN.md](../../../DESIGN.md)。
- 可交付设计资料以 research-completeness 工作树中的 DESIGN.md 与本目录为准；主目录同名资料保留作审阅副本。当前仅准备可跟踪文件，尚未Git暂存/提交。
- 这里保存七画板源文件和 canvas 索引，用于查看布局、配色、交互层级与比对源内容。
- 原型使用 Claude canvas 的 x-dc、sc-if、模板事件和 support.js。原临时目录未包含 support.js；本目录不是可独立双击运行的普通 HTML 网站。
- 不直接复制原型到生产。实际组件必须接真实运行状态、数据来源、模型列表、身份和统计契约。
- 原型包含演示行情、模型名、耗时、胜率、预测频率和操作按钮。它们不是可用功能清单，也不构成产品数据或能力承诺。
- 特别注意：TrackRecord 的“每周”样例与 a5103511 实际每日 US20 协议不一致，正式文案必须由后端 metadata 决定。
- 未接入的分享、下载、GitHub 登录等行为不得以可点击占位方式上线。

## 画板

| 源文件 | 参考重点 |
|---|---|
| [Main.dc.html](Main.dc.html) | 完成态、助手正文、过程折叠、单行工具、引用 |
| [Streaming.dc.html](Streaming.dc.html) | 进行态、专业任务分组、停止与追加要求 |
| [ChatChart.dc.html](ChatChart.dc.html) | 内联分析图、历史区间小图、代码/数据详情 |
| [RightPanel.dc.html](RightPanel.dc.html) | 当前对话标的、K线与来源上下文 |
| [Dashboard.dc.html](Dashboard.dc.html) | 看板层级、指标来源/时间、空态 |
| [TrackRecord.dc.html](TrackRecord.dc.html) | 结果与基准、逐条记录、简明说明 |
| [Welcome.dc.html](Welcome.dc.html) | 欢迎页、能力预览、登录视觉位置 |
| [canvas.json](canvas.json) | 原画布排列与尺寸 |

## 来源与校验

- 原来源：用户指定会话的本机 scratchpad/fs-design/project。
- 原始文件按字节复制，不修改其示例内容和 DSL。
- [source-manifest.json](source-manifest.json) 记录每个源文件的 SHA-256 与大小。
- 本轮验证源文件与快照 hash 一致，并阅读了 HTML 结构与样式；未运行七画板的像素对齐测试。
- 用户提供的三张截图已阅读：历史周线/事件区间图，以及两张产业逻辑论述。其图片内容不在这里重新发布，也不作为金融事实来源；对应能力要求已进入计划第11节。

