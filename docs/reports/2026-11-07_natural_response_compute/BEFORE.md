# 自然回答与计算修复：冻结的 before

状态：**历史基线，不是当前 after 验收结果**。该轮已经包含部分早期修复，不能将下面的成绩归因为某一个单独变更。

来源是本地 `.omx/acceptance-natural/REPORT.md` 与 `results.json`。按四个会话、八个原样问题的最终选定运行统计，共 **42 次真实模型调用、254410 reported tokens，完整通过 1/8**。这些 token 是模型返回的用量，不是账单金额。首次 harness 中断及残留租约造成的零模型拒绝单独记录，不计业务失败；各次重试不能与选定运行再重复相加。

| 问题 / 会话 | 选定 run | 模型调用 | 完整验收 | 未通过原因 |
| --- | --- | ---: | --- | --- |
| 1：AAPL 最近交易日收盘价、涨跌幅和日期 / S1 | `acceptance-natural-9e7eb3eff2-1` | 3 | 通过 | 独立数值核对、正文与真实消息保存均通过 |
| 2：沿用股票，用 Python 算 20 个交易日均价并画收盘/均线 / S1 | `acceptance-natural-9e7eb3eff2-2-retry-9bdb` | 13 | 未通过 | 隔离 Python 的均值 343.3844995 与独立复算一致，但没有进入最终正文；要求的双序列图没有生成 |
| 3：均线算法及周末是否计入 / S1 | `acceptance-natural-9e7eb3eff2-3-retry-3014` | 2 | 未通过 | 修正提示的机械措辞进入正文，最终内容仍不完整 |
| 4：NVDA 最新两个已披露季度的营收及变化，只看财报 / S2 | `acceptance-natural-9e7eb3eff2-4-retry-3558` | 9 | 未通过 | 真实季度营收与环比变化没有交付，最终只留下标题/限制说明 |
| 5：营收单位与下一季是否保证增长 / S2 | `acceptance-natural-9e7eb3eff2-5-retry-20c7` | 3 | 未通过 | 不能保证未来增长的理由没有完整保留 |
| 6：NVDA/AMD 年初至今涨跌幅图 / S3 | `acceptance-natural-9e7eb3eff2-6-retry-34ae` | 5 | 未通过 | 图表数值正确；正文却把期末上涨概括为全年持续上行，忽略 96 个下降日与阶段回撤 |
| 7：只说图能确认的结论，不推断资金流 / S3 | `acceptance-natural-9e7eb3eff2-7-retry-fb7e` | 2 | 未通过 | “AMD 全年领先/从未被反超”与 34 个 NVDA 领先交易日矛盾；仍混淆期末收益与价格路径 |
| 8：AAPL 实时暗盘净流入，不能用成交量替代 / S4 | `acceptance-natural-9e7eb3eff2-8-retry-bb75` | 5 | 未通过 | 把暗盘交易场所问题换成盘前/盘后时段问题，没有准确回答原问题的边界 |

`completed/answered` 只是一种运行/交付状态，不是上表的通过条件。case6/7/8 即使返回该状态仍未完整通过。正确均值没有进入最终答案、图表失败、路径结论错误和错误替换用户问题，都属于未完成用户要求。

case6 的唯一成功图表另有[前端数值和 Source proof](../2026-11-07_chat_design_alignment/RESULT_PROCESS_ICONS.md)：215 点双序列与源数据一致。这只证明该 artifact 的数值渲染，不能把 case6 正文改判为通过。case2 没有图表，前端未补造均线图。

本文件只冻结结果与失败类别，不把含错误口径的 terminal 全文复制为示范答案。新的运行、调用成本、图表和发布版本须记录到[本次复验](README.md)，不得覆盖这份 before。
