# TERMINAL Token 速查（08 设计语言）

## 背景四层（由外到内）
`bg-t-bg`(页面底) → `bg-t-surface`(面板) → `bg-t-card`(卡片) → `bg-t-elevated`(卡内嵌块)

## 文字三层
`text-t-text`(正文) / `text-t-text2`(辅助说明) / `text-t-text3`(元信息、时间戳、标签)

## 语义色
- 涨跌**必须**用 `text-t-up` / `text-t-down`（跟随 A股/国际配色开关），禁止 text-green-*/text-red-*
- `t-accent`（终端橙）只用于：主操作按钮、焦点态、进行中状态、品牌标识——不做大面积底色
- 提示/警告/信息：`t-warning` / `t-info`

## 圆角
卡片 `rounded-lg`(8px) / 控件按钮 `rounded-md`(6px) / chip 标签 `rounded`(4px)。对话与卡片区禁用 rounded-xl。

## 数字
一切数值（价格/百分比/时间戳）挂 `num` 类（mono + tabular-nums）。

## 工具类
`t-caret`(流式光标) / `t-flash-up|down`(价格闪动) / `t-skeleton`(骨架屏，>300ms 加载必用)

## 兼容
旧 `--fin-*` 全部别名到新 token，存量代码不用改；新代码一律用 `t-*`。
