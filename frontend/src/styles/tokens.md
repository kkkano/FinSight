# FinSight 样式与 Token 说明

更新：2026-11-13。实际值以 [index.css](../index.css)、[Tailwind 配置](../../tailwind.config.js)和[设计合同](../../../DESIGN.md)为准。当前采用统一研究工作区主题，历史 TERMINAL 橙色说明不再适用。

| 用途 | Token |
|---|---|
| 页面与面板 | --t-bg、--t-bg-2、--t-surface、--t-card、--t-elevated |
| 文字层级 | --t-text、--t-text-2、--t-text-3 |
| 品牌与主操作 | --t-accent、--t-accent-hi、--t-accent-soft |
| 边框与分隔 | --t-border、--t-divider、--t-line、--t-line-2 |
| 行情方向 | --t-up、--t-down，随红涨绿跌/国际模式切换 |
| 执行语义 | --t-success、--t-error、--t-warning、--t-info，不随行情模式反转 |
| 图表 | --t-chart-grid；真实数据色沿图表规范 |

浅色品牌主色 #3b5bdb，--t-accent 保存 RGB 分量；浅色正文 #0f172a，背景 #ffffff。深色与行情模式覆盖同一组变量。组件不新建颜色体系，旧 --fin-* 只作兼容别名。

正文使用 Geist Variable 和中文系统字体回退，数值/代码使用 JetBrains Mono，num 提供等宽数字。fs-prose 控制正文标题、列表、表格、引用和代码，不重新叠加旧 typography 规则。

间距、字号、圆角和阴影以现有 CSS/设计合同为准。复杂表格和图表在自身容器横滚，390px 不造成整页溢出。骨架、流式光标与价格闪动遵循 prefers-reduced-motion，关动画后仍能操作。

验收覆盖浅/深色、两种涨跌色、桌面/平板/390px、键盘焦点、中文组合输入和读屏活动。配色切换不让成功变失败；图表懒加载显示实际加载态，不显示模拟曲线。
