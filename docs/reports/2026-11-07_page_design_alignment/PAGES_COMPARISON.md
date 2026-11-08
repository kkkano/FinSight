# Welcome / Dashboard / TrackRecord 对照验收

按三份原始 `.dc.html` 的DOM层级、Flex/Grid、字号、间距逐块实施。Edge截图：桌面1440×960，移动390×844，均有亮/暗主题。`index.html`可浏览并排图；`compare-*.png`是独立并排文件。

实现截图使用测试路由返回的接口形状数据，价格、新闻、预测均不进入生产。原稿价格、百分比和事件数量未复制为业务默认值。

| 设计稿元素 | 实现位置（frontend/src） | 对照与差异 |
|---|---|---|
| Welcome顶栏品牌/公开链接 | components/welcome/WelcomePage.tsx | 同行16/32px padding；按用户要求保留README原logo。无页面的更新日志/协议链接不放占位；保留可用主题切换。 |
| Welcome左右栏 | index.css: welcome-columns/intro/login | max1180、gap48、左999/520、右1/340/max400；登录卡radius16/padding28/原稿shadow，窄屏自然换行。 |
| Welcome标题/示意卡 | welcome-title/description/demo | 44px/700/-0.025em/1.2，第二行accent。示意卡内容盒max600、radius14、padding16×18；明确“示意”，统计句改成方法说明，不陈述虚构结果。 |
| Welcome登录能力 | WelcomePage的provider请求 | 后端status=ok且github=true才展示；邮箱同样遵循provider。截图关闭GitHub，因此卡片比原稿短，不用空按钮补高度。 |
| Welcome底部三能力 | welcome-features/feature-grid | bg2、padding32、max1180、gap28、34px图标；频率从metadata/universe读取，缺失则明确待核对。 |
| Dashboard公司/价格/状态 | dashboard/StockHeader.tsx | 公司22px、价格34px；真实profile name/name_zh/exchange。日收盘标非实时，未知延迟不填15分钟；无提醒配置页就不放按钮。保留返回、刷新、主题实际操作于同一操作区。 |
| Dashboard tabs和双栏 | pages/Dashboard.tsx | 概览/财务/新闻/技术；主flex999 1 520、侧1 1 280、gap18、padding24×28。复用240px统一侧栏，符合220–264范围，与原稿自动Flex宽度存在小幅水平位移。 |
| Dashboard价格图 | DashboardPriceChart.tsx | 周期按钮真实请求K线API；ECharts替代固定SVG路径，显示实际范围、来源和时点，不复制示例价格曲线。 |
| Dashboard指标 | MetricsBar.tsx | minmax150，每项来源/日期11.5px、数值.num；缺值显示暂无及原因，不补零。实际字段数由既有接口决定。 |
| Dashboard最近分析 | LatestResearchCard.tsx | 读取同标的报告索引，标注“已保存的研究”，链接原对话。无分析时价格锚点时变化显示暂无，不从日期反推假价格。 |
| Dashboard新闻/同行 | tabs/OverviewTab.tsx | 短行、标签、理由/时间和真实同行表。没有方向性字段时显示方向待判断，不把影响强度当利好/利空。 |
| Dashboard自选/盯盘 | DashboardWatchlistCard、MonitorActivityFeed compact | 自选wrow含64px真实数据sparkline和高亮；盯盘44px美东时间列。截图模拟监控不可用，显示真实空态而非原稿假事件。 |
| TrackRecord标题/范围/三卡 | track-record/BenchmarkTrackRecord.tsx | max980、gap20、标题24px；范围28/84天或全部，大数字34px。方向/大跌/等待顺序一致，低于基准照常显示；不同模型版本不按成绩排序。 |
| TrackRecord累计曲线 | CumulativeChart | 仅用服务端daily_series并匹配确认cohort，缺失为空态。实际百分比在线尾标注、基准虚线；测试含0%，轴范围不会照抄原稿40%–70%。 |
| TrackRecord四格与明细 | TrackRecordContent/RecordRow/BenchmarkRecordDetail | 四格26px，普通人文案；发布日/标的/预测/信心/实际/结果表，原位展开原依据及逐日对账行情。缺confidence显示未提供。 |
| TrackRecord规则 | 默认关闭details | 公式、分红、重叠窗口、身份、版本、样本口径折叠；原稿默认展开，按用户新要求改为收起。日期型交易日不按UTC午夜转成前一天；逾期未对账显示等待行情。 |
| 个人与公共记录 | TrackRecordPage scope分流 | scope=personal只读当前账号个人预测，公共基准独立，不混用统计。 |
| 全局tokens/字体 | index.css | bg2/line/line2/accent-soft/amber/violet/teal及soft均取原稿亮暗值，accent仍RGB；沿用行情配色偏好。系统正文+本地JetBrains Mono，不加载Google字体，因此字形不同于原稿远程字体。 |

## 验证

- TypeScript检查通过。
- 22项页面/记录/监测组件聚焦单测通过，涵盖空分母、负基准差、未知模型不合并、公开字段白名单、交易日日期及可见术语。
- 6组页面亮暗/窄屏对照加6条工作区回归：12 passed。后续只对受影响页重拍/重跑，Dashboard/TrackRecord 4 passed，最后日期显示修正TrackRecord 2 passed；数量不累加。
- 已修复移动标题被范围按钮挤成窄列、tabs flex收缩。390px截图等待侧栏实际56px再拍，桌面侧栏240px。
- 原稿缺失support.js，通过测试helper解释原稿自带renderVals/sc-if/sc-for，不修改原设计文件；外部Google字体移除。
- 未写生产测试数据、未提交Git。发布及真实账号/OAuth/研究端到端由主任务统一验收。
