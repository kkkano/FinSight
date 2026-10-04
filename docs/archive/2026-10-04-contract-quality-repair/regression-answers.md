# 原12题组合回归回答

此处展示 v2 全量中的9题与 v3 定向中的 h01/h02/h12；不是同一快照的一次12题运行。阅读版仅去除行尾空格，原始Markdown逐字保存在 regression-answers.json；执行文件hash见 regression-scores.json。

## h01_orcl_earnings

问题：甲骨文 ORCL 最近一个已公布季度赚得怎么样？请区分收入、净利润和现金流，并说明这份财报对股价的影响。

来源：regression-v3-targeted；耗时 288.031 秒。

## ORCL · 部分完成

**财务与公告**

- 2026-08-31 营收 193.45 亿 USD（2026-06-01 至 2026-08-31）；披露日 2026-09-11 [7]
  - 2026-08-31 净利润 47.6 亿 USD（2026-06-01 至 2026-08-31）；披露日 2026-09-11
  - 2026-08-31 经营现金流 231.03 亿 USD（2026-06-01 至 2026-08-31）；披露日 2026-09-11

**价格**

- ORCL 最新可用报价 142.3 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [4]

**新闻与催化剂**

- 样本舆情积极，平均分 0.2；情绪样本 8 条，当前合格报道 0 条。舆情标签不代表投资方向。 [2]
  - 偏多舆情与近期价格上行共振。

**盈利预期**

- 当前财政季度 共识 EPS 1.8922 [币种未提供]/股 [14]
  - 下一财政季度 共识 EPS 2.0222 [币种未提供]/股
  - 当前财政季度 近 7 天 EPS 预期：上修 13 次，下修 14 次
  - 下一财政季度 近 7 天 EPS 预期：上修 5 次，下修 23 次
  - 快照时间：2026-10-04T01:49:05.932403。预期并非已实现业绩。
- 快照时间：2026-10-04T01:49:05.933407。预期并非已实现业绩。 [15]

**管理层指引**

- Oracle Reports Q1 2027 Results: Full Earnings Call Transcript | Longbridge Title: Oracle Reports Q1 2027 Results: Full Earnings Call Transcript [9]
  - URL Source: https://longbridge.com/en/news/298651335
  - Published Time: 2026-09-10T22:03:14.000Z
  - Markdown Content:
  - Oracle reported record Q1 FY2027 revenue of $19.3 billion, up 30% year-over-year, driven by a 121% surge in cloud infrastructure to $7.4 billion. Non-GAAP operating income rose 31% to $8.2 billion. The company completed a $20 billion equity issuance and expects CapEx of $90-$95 billion for AI infrastructure expansion. Future guidance projects Q2 revenue growth of 30-34% and EPS of $1.85-$1.93.
  - On Thursday, Oracle (NYSE:ORCL) discussed first-quarter financial results during its earnings call. The full transcript is provided below.
  - This content is powered by Benzinga APIs. For comprehensive financial data and
- Oracle (ORCL) Q1 2027 Earnings Call Transcript | The Motley Fool Title: Oracle (ORCL) Q1 2027 Earnings Call Transcript [19]
  - URL Source: https://www.fool.com/earnings/call-transcripts/2026/09/11/oracle-orcl-q1-2027-earnings-call-transcript/
  - Published Time: 2026-09-11T13:38:32.000Z
  - ![Image 1: Logo of jester cap with thought bubble.](https://g.foolcdn.com/image/?url=https%3A%2F%2Fg.foolcdn.com%2Fmisc-assets%2Ffool-transcripts-logo.png&w=3840&op=resize)
  - Image source: The Motley Fool.
  - ## DATE
  - Thursday, Sept. 10, 2026 at 5:00 p.m. ET
  - ## CALL PARTICIPANTS
  - *   head of investor relations - Ken Bond
  - *   Chief Executive Officer - Mike Sicilia
  - *   Chief Executive Officer - Clayton Magouyrk
  - *   chief financial officer - Hilary Barbara Maxson
  - ## TAKEAWAYS
  - *   **Total Revenue** -- $19.3 billion, increasing 30% year over year driven by record gro
- ORCL Earnings Call Transcript — Fiscal Q3 2026 Title: ORCL Earnings Call Transcript · Fiscal Q3 2026 [20]
  - URL Source: https://exa.ai/library/markets/stocks/ORCL/earnings/FY2026/Q3/transcript
  - Oracle (ORCL) is a public company. Oracle is a global leader in AI, delivering the cloud infrastructure, data, and applications that organizations across the world trust to successfully achieve business outcomes at scale.
  - Oracle Cloud Infrastructure (OCI) provides fast, flexible, scalable AI infrastructure. With superior compute performance and network design, a comprehensive choice of AI services for developing and orchestrating agentic AI workflows at scale, and unrivaled data control, security, privacy, and governance, OCI is designed for AI workloads. It also gives customers the flexibility to run their workloads wherever they n
- Oracle ORCL Q4 2026 Earnings Call Transcript | The Motley Fool Title: Oracle ORCL Q4 2026 Earnings Call Transcript [21]
  - URL Source: https://www.fool.com/earnings/call-transcripts/2026/06/10/oracle-orcl-q4-2026-earnings-call-transcript/
  - Published Time: 2026-06-10T22:04:52.000Z
  - Wednesday, June 10, 2026 at 5:00 p.m. ET
  - *   Chief Executive Officer — Michael D. Sicilia
  - *   Chief Executive Officer — Clayton Magouyrk
  - *   Chief Financial Officer — Hilary Barbara Maxson
  - *   Investor Relations — Ken Bond
  - **Need a quote from a Motley Fool analyst? Email [[email protected]](https://www.fool.com/cdn-cgi/l/email-pr
- Oracle (ORCL) Q4 2026 Earnings Call Transcript & Audio Title: Just a moment... [22]
  - URL Source: https://stockanalysis.com/stocks/orcl/transcripts/592465-q4-2026/
  - Warning: This page maybe requiring CAPTCHA, please make sure you are authorized to access this page.
  - ![Image 1: Icon for stockanalysis.com](https://stockanalysis.com/favicon.ico)
  - ## stockanalysis.com
  - ## Performing security verification
  - This website uses a security service to protect against malicious bots. This page is displayed while the website verifies you are not a bot.

**风险**

- 因子 beta：市场 2.0257；成长 1.4165 [16]
  - 历史年化波动率 56.59%
  - 观察期最大回撤 -62.91%
  - 快照时间：2026-10-04T01:49:05.947571；历史模型不代表未来表现。

**事件日历**

- 分红：2026-10-08 Ex-Dividend Date（供应商日历，日期以公司或官方披露为准） [18]
  - 分红：2026-10-22 Dividend Date（供应商日历，日期以公司或官方披露为准）
  - 本轮供应商日历查询窗口为未来 30 天，不代表已取得全部事件；快照时间 2026-10-04T08:49:05.938415+00:00。

**基本面**

- 2026-08-31 营收: $19.34B；单位 USD；来源口径 quarterly。 [1]
- 2026-08-31 净利润: $4.76B；单位 USD；来源口径 quarterly。 [1]
- 2026-08-31 营业利润: $6.82B；单位 USD；来源口径 quarterly。 [1]
- 2026-08-31 经营现金流: $23.10B；单位 USD；来源口径 quarterly。 [1]
- 2026-08-31 总资产: $303.26B；单位 USD；来源口径 instant。 [1]
- 2026-08-31 总负债: $236.06B；单位 USD；来源口径 instant。 [1]

**研究判断与风险**

- 已披露季度实际数显示成长质量较强：收入同比高增但环比几乎持平；净利润同比、环比均改善，且净利润同比增速高于收入；营业利润同比高增但环比小幅回落。稀释 EPS 也高于上年同期。机制上，利润改善不能只用营收规模解释，还包含盈利能力/费用结构变化。 [1]
- 前瞻信息要区分已发生与未发生：Q1 实际数如上；下一季提供商估计显示营收均值继续处于高位，但 EPS 均值对应同比可能下滑，而公司指引仍指向营收高增。EPS 修正信号整体偏正，但下一季下调家数多于上调，年度估计以上调为主。若云/AI 需求与指引兑现，机制上会强化盈利与情绪；若资本开支继续使自由现金流为负、或高杠杆与高 beta/波动放大预期修正，股价双向波动风险也会上升。 [4] [5] [6]
- ORCL 成长质量向好：营收同比 29.6%。 [1]
- ORCL 经营现金流覆盖净利润，支撑盈利质量。 [1]
- ORCL 负债/资产比为 77.8%，影响资产负债表风险。 [1]
- 现金流质量需要分层看：经营现金流远高于净利润，覆盖净利润，支撑盈利质量；但资本开支超过经营现金流，使自由现金流为负。差异主要来自云/AI 基础设施投入，而非经营现金创造本身失效。与此同时，总负债/总资产处于高位，杠杆偏高，构成资产负债表风险。 [1]
- 从已观测市场反应看，收盘价单日上涨，短期价格上行，舆情偏多，价格传导状态为共振；但舆情趋势为 deteriorating，说明偏多强度在边际减弱。该共振是观测关系，不能把全部价格变动单独归因于财报。 [2]


**未核实的检索材料**
- How Sustainable Is Oracle’s Cash Flow Without Customer Prepayments? / finance.yahoo.com / 2026-10-02T17:54:25+00:00 [23]；观点；主体关联未确认；仅为检索线索，本轮未形成通过事实校验的对应解释。

## 风险与分歧

- 杠杆率偏高（负债/资产 = 78% > 60%），偿债压力较大。
- 旧闻、未知发布时间、观点及检索线索不计入当前新闻催化，需结合原始披露核实。
- ORCL 单日波动 +3.06%（中等波动）。

## 限制

- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。
- 因子暴露基于历史模型快照，不代表未来表现。
- 情绪传导基于近期可用价格数据，可能缺失盘中或盘后波动。

## 来源

- [1] [ORCL 基本面 / yfinance / 2026-08-31](https://finance.yahoo.com/quote/ORCL/financials/)
- [2] ORCL 新闻与催化剂 / news_sentiment_snapshot / 2026-10-04T01:49:14.845729
- [4] ORCL 价格 / twelve_data / 2026-10-02
- [5] ORCL 风险 / yfinance_factor_model / 2026-10-04T01:49:05.947571
- [6] ORCL 风险 / historical_price_analysis / 2026-10-02
- [7] [ORCL 财务与公告 / 2026-08-31](https://data.sec.gov/api/xbrl/companyfacts/CIK0001341439.json)
- [9] [Oracle Reports Q1 2027 Results: Full Earnings Call Transcript | Longbridge / longbridge.com](https://longbridge.com/en/news/298651335)
- [14] ORCL 盈利预期 / 2026-10-04T01:49:05.932403
- [15] ORCL 盈利预期 / 2026-10-04T01:49:05.933407
- [16] ORCL 风险 / 2026-10-04T01:49:05.947571
- [18] ORCL 事件日历 / 2026-10-04T08:49:05.938415+00:00
- [19] [Oracle (ORCL) Q1 2027 Earnings Call Transcript | The Motley Fool / fool.com](https://www.fool.com/earnings/call-transcripts/2026/09/11/oracle-orcl-q1-2027-earnings-call-transcript/)
- [20] [ORCL Earnings Call Transcript — Fiscal Q3 2026 / exa.ai](https://exa.ai/library/markets/stocks/ORCL/earnings/FY2026/Q3/transcript)
- [21] [Oracle ORCL Q4 2026 Earnings Call Transcript | The Motley Fool / fool.com](https://www.fool.com/earnings/call-transcripts/2026/06/10/oracle-orcl-q4-2026-earnings-call-transcript/)
- [22] [Oracle (ORCL) Q4 2026 Earnings Call Transcript & Audio / stockanalysis.com](https://stockanalysis.com/stocks/orcl/transcripts/592465-q4-2026/)
- [23] [How Sustainable Is Oracle’s Cash Flow Without Customer Prepayments? / finance.yahoo.com / 2026-10-02T17:54:25+00:00](https://finance.yahoo.com/markets/stocks/articles/sustainable-oracle-cash-flow-without-175425293.html?.tsrc=rss)

## h02_orcl_events

问题：沿用刚才这家公司，未来90天哪些已确认事件值得跟踪？把确定日期与仅供观察的可能催化分开。

来源：regression-v3-targeted；耗时 171.906 秒。

## ORCL · 部分完成

**事件日历**

- 财报：2026-12-10 预期财报发布日期（供应商日历，日期以公司或官方披露为准） [3]
  - 分红：2026-10-08 Ex-Dividend Date（供应商日历，日期以公司或官方披露为准）
  - 分红：2026-10-22 Dividend Date（供应商日历，日期以公司或官方披露为准）
  - 本轮供应商日历查询窗口为未来 90 天，不代表已取得全部事件；快照时间 2026-10-04T08:53:53.799366+00:00。

**新闻与催化剂**

- 样本舆情积极，平均分 0.2；情绪样本 8 条，当前合格报道 0 条。舆情标签不代表投资方向。 [1]
  - 偏多舆情与近期价格上行共振。

**研究判断与风险**

- 在已返回的未来90天供应商日历范围内，ORCL的确定日期项为：2026-10-08除息日、2026-10-22股息日、2026-12-10财报日；其中财报日由两个供应商来源列示为同一scheduled日期。需要区分的是，新闻舆情快照口径下的日历催化事件计数为0（C2），这与供应商公司行动日历属于不同统计口径，不能互相替代。该日历覆盖范围exhaustive=false，仅代表本轮供应商返回，不能据此排除其他潜在事件。 [3] [1]
- 在未来90天（direction=future、days_ahead=90）已返回的供应商日历材料中，可列为确定日期跟踪的公司行动项为：2026-10-08除息日、2026-10-22股息日、2026-12-10财报日；这些条目status=scheduled、verification=provider_reported，财报日由两个供应商来源列示为同一scheduled日期。这里的“确定”仅指供应商日历已列示，不等同于官方已确认。该日历coverage_window.exhaustive=false，仅代表本轮供应商返回，不能据此排除其他潜在事件。 [3]


## 风险与分歧

- 旧闻、未知发布时间、观点及检索线索不计入当前新闻催化，需结合原始披露核实。
- 新闻来源可靠度偏低，请结合一手披露文件核实关键结论。

## 限制

- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。
- 情绪传导基于近期可用价格数据，可能缺失盘中或盘后波动。
- 催化事件聚合识别的是时点/关注度驱动因素，本身并不证明价格方向。

## 来源

- [1] ORCL 新闻与催化剂 / news_sentiment_snapshot / 2026-10-04T01:53:58.847124
- [3] ORCL 事件日历 / 2026-10-04T08:53:53.799366+00:00

## h03_adbe_quote

问题：ADBE 最近一次可用报价是多少？告诉我币种、报价时间和是否为盘后价格，别把它说成实时价。

来源：regression-v2；耗时 0.266 秒。

## ADBE · 已回答

**价格**

- ADBE 最新可用报价 237.69 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [1]


## 来源

- [1] ADBE 价格 / twelve_data / 2026-10-02

## h04_avgo_technical

问题：只看 AVGO 的技术面：日线趋势、RSI、MACD、支撑和阻力，不需要新闻或基本面。

来源：regression-v2；耗时 8.187 秒。

## AVGO · 已回答

**技术面**

- 收盘价 355.14；MA20 354.1；MA50 373.22；RSI(14) 56.59；MACD -5.5183；MACD 信号线 -6.4512；RSI 尚未进入常用超买或超卖区间。；MACD 高于信号线。；指标趋势：横盘。 [3]
- 支撑 335.81 | 阻力 372.70 | 最新成交量 24607000 | 20日均量 25036465 | 量能 0.98x [4]
- Market sentiment: CNN Fear & Greed Index: 31.2 (fear) [5]
- MA20 354.10 | MA50 373.22 [4]
- RSI(14) 56.59 | MACD -5.5183 | 信号线 -6.4512 [4]

**价格**

- AVGO 最新可用报价 355.14 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [1]


## 风险与分歧

- 技术信号暂无明显风险。

## 来源

- [1] AVGO 价格 / twelve_data / 2026-10-02
- [3] Technical snapshot (AVGO) / twelve_data / 2026-10-02
- [4] [AVGO 技术面 / twelve_data / 2026-10-02](https://finance.yahoo.com/quote/AVGO/history/)
- [5] 技术面 / market_sentiment / 2026-10-02

## h05_baba_hk

问题：请研究阿里巴巴港股 9988.HK 的最新财务、估值和风险；只分析这个上市代码，金额标清币种。

来源：regression-v2；耗时 95.062 秒。

## 9988.HK · 部分完成

**基本面**

- 2026-06-30 营收: CNY 268.95B；单位 CNY；来源口径 quarterly。 [1]
- 2026-06-30 净利润: CNY 10.61B；单位 CNY；来源口径 quarterly。 [1]
- 2026-06-30 经营现金流: CNY 22.95B；单位 CNY；来源口径 quarterly。 [1]
- 2026-06-30 营业利润: CNY 19.62B；单位 CNY；来源口径 quarterly。 [1]
- 2026-06-30 总资产: CNY 1.96T；单位 CNY；来源口径 instant。 [1]
- 2026-06-30 总负债: CNY 848.22B；单位 CNY；来源口径 instant。 [1]

**公司与估值**

- 市值：20,777.65 亿 HKD [5]
  - 公司：Alibaba Group Holding Limited
  - Trailing P/E：24.06
  - Forward P/E：11.49

**盈利预期**

- 当前财政季度 共识 EPS 1.4251 [币种未提供]/股 [6]
  - 下一财政季度 共识 EPS 1.7692 [币种未提供]/股
  - 当前财政季度 近 7 天 EPS 预期：上修 0 次，下修 1 次
  - 下一财政季度 近 7 天 EPS 预期：上修 0 次，下修 2 次
  - 快照时间：2026-10-04T01:34:49.058247。预期并非已实现业绩。

**风险**

- 规则风险评分 15/100；该评分不代表未来损失概率。 [2]
  - 快照时间：2026-10-04T08:34:55.239725+00:00；历史模型不代表未来表现。
- Top 3 Historical Drawdowns for 9988.HK (coverage 2019-11-26 to 2026-10-02 (~6.9y)): [8]
  - - Drawdown: -80.01% (from 2020-10-28 to 2022-10-31)
  - Duration to trough: 733 days. Recovery time: Ongoing days.
- 因子 beta：市场 0.4123；成长 0.3073 [9]
  - 历史年化波动率 44.11%
  - 观察期最大回撤 -51.59%
  - 快照时间：2026-10-04T01:34:49.062391；历史模型不代表未来表现。
- 历史最大回撤 -80.01%，覆盖 2019-11-26 至 2026-10-02；这是历史事实，不是未来回撤预测。 [4]

**研究判断与风险**

- 估值层面，公司 Trailing P/E 与 Forward P/E 存在显著落差，P/B、P/S 及 EV/EBITDA 亦提供了资产、销售与企业价值倍数参照（E11）。这一落差隐含市场对未来盈利路径改善的定价；然而分析师 EPS 修订信号为负面，短端与长端预测均以下调为主（E13），且 0y 与 +1y 平均预测虽维持正增长（E12），但预测增速面临下修压力。机制上，若盈利预测无法兑现甚至继续下修，当前 Forward P/E 的估值消化将更依赖价格调整而非盈利上修，估值合理性因而受制于盈利预期的稳定性。 [5] [6] [7]
- 基本面呈现增长与盈利分化机制。营收端保持同比与环比双增长（E7），但净利润与营业利润均出现大幅同比下滑（E1、E9），显示成本、费用或非经营性因素对利润表造成显著挤压。与之相对，经营现金流实现同比增长与环比大幅改善（E2），并对净利润形成覆盖，表明主营业务现金创造能力尚未同步恶化，盈利质量的现金流支撑仍在。资产负债表方面，总资产与总负债的同比变动（E4、E6）对应负债/资产比约 43.2%，杠杆水平中等，未显现极端偿债压力，但负债增速高于资产增速需持续关注。 [1]
- 风险水平需分层看待。已观测规则给出的风险评分处于低区间（E5、C1），但该评分仅衡量预设规则触发程度，且原始返回包含市场数据不可用提示，不能等同于完整投资风险评级。历史价格数据显示最大回撤极深且恢复周期长（E10、E3），年化波动率亦处于高位（E14）。因子暴露显示对市场与成长因子存在正向敏感，但 market_r2 极低（E14、E8、C4），意味着历史波动主要由个股特异性风险驱动，市场因子模型解释力有限。叠加分析师 EPS 负面修订（E13），未来盈利路径的不确定性会通过预期修正渠道放大股价波动。 [2] [8] [4] [9] [3] [7]
- 9988.HK 经营现金流覆盖净利润，支撑盈利质量。 [1]
- 9988.HK 已观测规则的风险评分为 15.0/100（低规则信号强度）。 [2] [3] [4]
- 9988.HK 因子暴露快照：市场 beta=0.4123，成长 beta=0.3073。 [3]

- [数据缺失] 财务与公告尚未满足。
- [未完成] 估值口径与依据。

## 风险与分歧

- 基本面数据未见重大风险信号。
- 9988.HK estimated annualized volatility 44.1% is elevated.

## 限制

- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。
- 因子暴露基于历史模型快照，不代表未来表现。
- 仅衡量本轮可观测指标触发预设规则的程度，不等于对整体投资风险的完整评级。

## 来源

- [1] [9988.HK 基本面 / yfinance / 2026-06-30](https://finance.yahoo.com/quote/9988.HK/financials/)
- [2] 9988.HK 风险 / yfinance_fallback / 2026-10-04T08:34:55.239725+00:00
- [3] 9988.HK 风险 / yfinance_factor_model / 2026-10-04T01:34:49.062391
- [4] 9988.HK 风险 / historical_price_analysis / 2026-10-02
- [5] 9988.HK 公司与估值
- [6] 9988.HK 盈利预期 / 2026-10-04T01:34:49.058247
- [7] 9988.HK 盈利预期 / 2026-10-04T01:34:49.059246
- [8] 9988.HK 风险 / analyze_historical_drawdowns
- [9] 9988.HK 风险 / 2026-10-04T01:34:49.062391

## h06_v_ma_compare

问题：Visa（V）和 Mastercard（MA）谁的估值更贵、自由现金流质量更好？用可比较财期，并解释差异。

来源：regression-v2；耗时 313.312 秒。

## V, MA · 部分完成

**横向证据比较**

| 维度 | V | MA |
| --- | --- | --- |
| 公司与估值 | 市值：6,770.87 亿 USD 公司：Visa Inc. Trailing P/E：30.67 Forward P/E：24.04 [1] | 市值：4,837.85 亿 USD 公司：Mastercard Incorporated Trailing P/E：30.21 Forward P/E：23.99 [2] |
| 盈利预期 | 当前财政季度 共识 EPS 3.4292 [币种未提供]/股 下一财政季度 共识 EPS 3.6274 [币种未提供]/股 快照时间：2026-10-04T01:36:24.211358。预期并非已实现业绩。 [4] | 当前财政季度 共识 EPS 5.1512 [币种未提供]/股 下一财政季度 共识 EPS 5.1703 [币种未提供]/股 快照时间：2026-10-04T01:36:24.217524。预期并非已实现业绩。 [3] |
| 财务与公告 | 2026-03-31 营收 112.3 亿 USD 2026-03-31 净利润 60.21 亿 USD 2026-03-31 经营现金流 30.08 亿 USD [6] | 2026-06-30 营收 92.77 亿 USD 2026-06-30 净利润 43.88 亿 USD 2026-06-30 经营现金流 37.73 亿 USD [5] |
| 价格 | V 最新可用报价 360.66 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [7] | MA 最新可用报价 552.26 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [8] |
估值、盈利与风险需要共同评估；以上事实差异本身不构成买入或卖出建议。

**研究判断与风险**

- 估值口径上，V 收报 360.66 美元，总市值约 6770.9 亿美元，trailing P/E 30.67、forward P/E 24.04、P/S 15.22、EV/EBITDA 21.66；MA 收报 552.26 美元，总市值约 4837.9 亿美元，trailing P/E 30.21、forward P/E 23.99、P/S 13.79、EV/EBITDA 22.38。 [7] [8] [1] [2]
- 可比较财期按相同期末日期处理：V 为 9 月财年，MA 为 12 月财年，因此采用 2026-03-31 与 2026-06-30 两个共同期末，而不是相同季度序号。 [6] [5] [13] [11]
- 趋势上，MA 2026-06-30 OCF 同比 -18.03%，FCF 从 2025-06-30 的 45.63 亿美元降至 34.82 亿美元；V 2026-06-30 OCF 同比 -2.62% 但环比 +117.89%，季度波动更大。由于 V 缺 FCF 输入，最终只能确认 MA 具备可验证的高转化 FCF，V 则是绝对现金流规模更强但 FCF 质量待补充数据。 [9] [5] [10]
- 自由现金流质量上，MA 在 2026-06-30 三个月的 OCF 为 3773000000 美元、capex 为 291000000 美元、FCF 为 3482000000 美元；2026-03-31 三个月的 OCF 为 2999000000 美元、capex 为 154000000 美元、FCF 为 2845000000 美元。capex 明显小于 OCF，已披露经营现金流大部分转化为 FCF。 [5]
- 趋势上，MA 2026-06-30 OCF 为 $3.77B，yfinance 快照显示 yoy -0.1803、qoq 0.2581；V 2026-06-30 OCF 为 $6.55B，yoy -0.0262、qoq 1.1789。MA 的 FCF 从 2025-06-30 的 4563000000 美元降至 2026-06-30 的 3482000000 美元。由于 V 缺 FCF 输入，只能确认 MA 具备可验证的高转化 FCF，V 则是绝对现金流规模更强但 FCF 质量待补充数据。 [9] [10] [5]

- [未完成] 估值口径与依据。

## V · 部分完成

**盈利预期**

- 当前财政季度 共识 EPS 3.4292 [币种未提供]/股 [4]
  - 下一财政季度 共识 EPS 3.6274 [币种未提供]/股
  - 当前财政季度 近 7 天 EPS 预期：上修 0 次，下修 2 次
  - 下一财政季度 近 7 天 EPS 预期：上修 2 次，下修 0 次
  - 快照时间：2026-10-04T01:36:24.211358。预期并非已实现业绩。

**财务与公告**

- 2026-03-31 营收 112.3 亿 USD（2026-01-01 至 2026-03-31）；披露日 2026-04-29 [6]
  - 2026-03-31 净利润 60.21 亿 USD（2026-01-01 至 2026-03-31）；披露日 2026-04-29
  - 2026-03-31 经营现金流 30.08 亿 USD（2026-01-01 至 2026-03-31）；披露日 2026-04-29

**价格**

- V 最新可用报价 360.66 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [7]

**公司与估值**

- 市值：6,770.87 亿 USD [1]
  - 公司：Visa Inc.
  - Trailing P/E：30.67
  - Forward P/E：24.04

- [未完成] 现金流的事实解释尚未完成。

## MA · 部分完成

**盈利预期**

- 当前财政季度 共识 EPS 5.1512 [币种未提供]/股 [3]
  - 下一财政季度 共识 EPS 5.1703 [币种未提供]/股
  - 当前财政季度 近 7 天 EPS 预期：上修 1 次，下修 0 次
  - 下一财政季度 近 7 天 EPS 预期：上修 9 次，下修 17 次
  - 快照时间：2026-10-04T01:36:24.217524。预期并非已实现业绩。

**财务与公告**

- 2026-06-30 营收 92.77 亿 USD（2026-04-01 至 2026-06-30）；披露日 2026-07-30 [5]
  - 2026-06-30 净利润 43.88 亿 USD（2026-04-01 至 2026-06-30）；披露日 2026-07-30
  - 2026-06-30 经营现金流 37.73 亿 USD（2026-04-01 至 2026-06-30）；披露日 2026-07-30

**价格**

- MA 最新可用报价 552.26 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [8]

**公司与估值**

- 市值：4,837.85 亿 USD [2]
  - 公司：Mastercard Incorporated
  - Trailing P/E：30.21
  - Forward P/E：23.99

- [未完成] 现金流的事实解释尚未完成。

## 风险与分歧

- 杠杆率偏高（负债/资产 = 63% > 60%），偿债压力较大。
- 杠杆率偏高（负债/资产 = 90% > 60%），偿债压力较大。

## 限制

- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。

## 来源

- [1] V 公司与估值
- [2] MA 公司与估值
- [3] MA 盈利预期 / 2026-10-04T01:36:24.217524
- [4] V 盈利预期 / 2026-10-04T01:36:24.211358
- [5] [MA 财务与公告 / 2026-06-30](https://data.sec.gov/api/xbrl/companyfacts/CIK0001141391.json)
- [6] [V 财务与公告 / 2026-03-31](https://data.sec.gov/api/xbrl/companyfacts/CIK0001403161.json)
- [7] V 价格 / twelve_data / 2026-10-02
- [8] MA 价格 / twelve_data / 2026-10-02
- [10] [V 基本面 / yfinance / 2026-06-30](https://finance.yahoo.com/quote/V/financials/)
- [9] [MA 基本面 / yfinance / 2026-06-30](https://finance.yahoo.com/quote/MA/financials/)
- [11] [Mastercard Inc 10-K (2026-02-11) / sec_edgar / 2026-02-11](https://www.sec.gov/Archives/edgar/data/1141391/000114139126000013/ma-20251231.htm)
- [13] [VISA INC. 10-K (2025-11-06) / sec_edgar / 2025-11-06](https://www.sec.gov/Archives/edgar/data/1403161/000140316125000089/v-20250930.htm)

## h07_multi_task

问题：XOM 看近期新闻，COST 看经营基本面，BTC-USD 看价格趋势；请分别回答，不要把三种任务混在一起。

来源：regression-v2；耗时 275.094 秒。

## XOM · 部分完成

**新闻与催化剂**

- 样本舆情中性，平均分 0.04；情绪样本 8 条，当前合格报道 0 条。舆情标签不代表投资方向。 [1]
  - 舆情方向或价格方向不够明确，暂未形成强共振/背离。

**研究判断与风险**

- 窗口内还存在多条次要或待核实线索：涉及伊朗摩擦推升油价（E2）、Wells Fargo给予Equal Weight评级（E3）、战争利润交易计划目标价180美元（E4），以及低成本Guyana和Permian上游资产支撑长期盈利（E5）。这些线索发布时间未知、来源待核实，若后续证实，可能通过油价传导、评级调整或长期基本面预期影响市场；但在当前窗口内不能作为已发生事实或确定催化。 [4] [2] [3] [5]
- 需要提示的是，本轮新闻来源可靠度整体偏低（平均0.5975，高可靠度0条，低可靠度3条），且覆盖窗口为非穷尽返回，不能据此排除窗口内存在其它未返回事件；供应商日历日期亦非官方已确认，需结合一手披露核实。 [1]
- 机制上，整体舆情标签为中性，情绪趋势稳定，价格传导状态同样为中性。这意味着当前股价变动缺乏明确的公司消息驱动证据，更可能由行业、宏观或市场整体因素解释；在舆情方向进一步明确前，不宜把近期价格波动直接归因于 XOM 特定新闻催化。 [1]
- 需要提示的是，本轮新闻来源可靠度整体偏低，并检测到多个低可靠度来源；覆盖窗口为非穷尽返回，不能据此排除窗口内还存在其它未返回事件。供应商日历日期也不等同于官方已确认，关键结论需结合一手披露文件核实。 [1]


**未核实的检索材料**
- No title / seekingalpha.com / 2026-10-04T01:41:50.471018 [14]；发布时间未知；检索线索，待核实；主体关联未确认；仅为检索线索，本轮未形成通过事实校验的对应解释。

## COST · 部分完成

**财务与公告**

- 2026-05-10 营收 705.27 亿 USD（2026-02-16 至 2026-05-10）；披露日 2026-06-03 [11]
  - 2026-05-10 净利润 21.92 亿 USD（2026-02-16 至 2026-05-10）；披露日 2026-06-03
  - 2026-05-10 经营现金流 34.49 亿 USD（2026-02-16 至 2026-05-10）；披露日 2026-06-03

**基本面**

- 2026-05-31 营收: $70.53B；单位 USD；来源口径 quarterly。 [6]
- 2026-05-31 净利润: $2.19B；单位 USD；来源口径 quarterly。 [6]
- 2026-05-31 营业利润: $2.81B；单位 USD；来源口径 quarterly。 [6]
- 2026-05-31 经营现金流: $3.45B；单位 USD；来源口径 quarterly。 [6]
- 2026-05-31 总资产: $86.43B；单位 USD；来源口径 instant。 [6]
- 2026-05-31 总负债: $52.92B；单位 USD；来源口径 instant。 [6]

**研究判断与风险**

- 现金流质量方面，经营现金流绝对额仍显著高于当期净利润，覆盖倍数充足，说明账面盈利具备现金支撑，盈利质量较为扎实。然而，经营现金流同比几乎零增长，与净利润双位数增长形成明显差异；这一差异机制上可能源于库存备货、门店资本开支增加或应付账款周期变化，导致利润增长未能完全同步转化为现金流入。 [6]
- COST 成长质量向好：营收同比 11.6%。 [6]
- 资产负债表风险方面，总资产同比增长约 14.5%，总负债同比增长约 9.4%，负债/资产比约为 61.2%。虽然负债增速低于资产增速，但绝对杠杆水平仍处于相对高位，对资产负债表稳健性构成压力。机制上，较高的负债/资产比意味着公司资产中由债务融资的比例较大，若未来盈利或现金流增速放缓，财务弹性将受到更大约束；同时，资产端的快速扩张若主要依赖负债驱动，也会进一步加剧杠杆敏感性。 [6]
- 从成长质量看，COST 最新季度收入与利润端均保持双位数扩张，且净利润增速快于营收增速，显示公司在会员制仓储模式下的经营杠杆正在释放，单位收入向利润的转化效率提升。但同期经营现金流与利润端的强劲增长出现短暂背离，提示需关注营运资本变动或资本开支节奏对现金转化的阶段性影响。 [6]
- 资产负债表风险方面，总资产与总负债均同比增长，负债/资产比处于相对高位。虽然负债增速低于资产增速，但绝对杠杆水平仍对资产负债表稳健性构成压力。机制上，较高的负债/资产比意味着公司资产中由债务融资的比例较大，若未来盈利或现金流增速放缓，财务弹性将受到更大约束；同时，资产端的快速扩张若主要依赖负债驱动，也会进一步加剧杠杆敏感性。 [6]


## BTC-USD · 证据不足

[数据缺失] 本轮没有取得可验证的对应事实或论据。
- [数据缺失] 趋势质量尚无可展示的已验证事实。
- [数据缺失] 技术面尚未满足。
- [未完成] 价格趋势。

## 风险与分歧

- 旧闻、未知发布时间、观点及检索线索不计入当前新闻催化，需结合原始披露核实。
- 新闻来源可靠度偏低，请结合一手披露文件核实关键结论。
- 本批次中检测到多个低可靠度来源。

## 限制

- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。
- 情绪传导基于近期可用价格数据，可能缺失盘中或盘后波动。
- 部分模型解释未通过事实绑定校验，已移除对应段落；其它已验证事实与论据仍保留。

## 来源

- [1] XOM 新闻与催化剂 / news_sentiment_snapshot / 2026-10-04T01:41:50.238937
- [2] [ExxonMobil (NYSE:XOM) Earns Equal Weight Rating from Wells Fargo & Company / americanbankingnews.com / 2026-10-04T01:41:50.471018](https://www.americanbankingnews.com/2026/10/03/exxonmobil-nysexom-earns-equal-weight-rating-from-wells-fargo-company.html)
- [3] [ExxonMobil Ready to Ride War-Driven Margins Higher — XOM Trade Plan to $180 / tradevae.com / 2026-10-04T01:41:50.471018](https://tradevae.com/news/trade-ideas/ExxonMobil-Ready-to-Ride-War-Driven-Margins-Higher-XOM-Trade-Plan-to-180/)
- [4] [ExxonMobil (NYSE:XOM) Firms As Iran Friction Lifts Oil / kalkinemedia.com / 2026-10-04T01:41:50.471018](https://kalkinemedia.com/us/stocks/oil-gas/exxonmobil-nysexom-firms-as-iran-friction-lifts-oil)
- [5] [ExxonMobil's Advantageous Upstream Assets to Fuel Long-Term Growth / finance.yahoo.com / 2026-10-01T16:31:00+00:00](https://finance.yahoo.com/energy/articles/exxonmobils-advantageous-upstream-assets-fuel-163100049.html?.tsrc=rss)
- [6] [COST 基本面 / yfinance / 2026-05-31](https://finance.yahoo.com/quote/COST/financials/)
- [11] [COST 财务与公告 / 2026-05-10](https://data.sec.gov/api/xbrl/companyfacts/CIK0000909832.json)
- [14] [No title / seekingalpha.com / 2026-10-04T01:41:50.471018](https://seekingalpha.com/article/4951752-exxonmobil-set-for-record-highs-as-war-profits-boom)

## h08_oil_macro

问题：如果最近原油价格走高，会怎样传导到美国通胀、利率预期与航空股？区分已发生的数据和假设推演。

来源：regression-v2；耗时 147.25 秒。

## CL=F · 部分完成

**宏观事件**

- 2026-09-01 联邦基金利率（历史观测） 3.75%；该序列观测不等同于最近一次 FOMC 决议确认。 [2]
- 2026-08-01 CPI 通胀同比 3.35% [1]
- 2026-10-01 10 年期美债收益率 5.24% [4]

**研究判断与风险**

- 条件推演，而非已发生事实：若最近油价走高，首先会通过能源分项直接推高美国整体CPI，并可能经运输、化工及商品成本间接传导。已发生CPI同比读数见事实段，说明整体通胀已有基数；若油价上涨只是短期脉冲，对核心通胀的传导可能有限，若持续更久则可能影响通胀预期与定价行为。已发生失业率见事实段，但本轮材料未提供已验证的薪资螺旋证据，因此不能断定油价走高已造成全面物价失控。检索材料将中东供应担忧和成品油供给瓶颈视为油价风险溢价来源，这属于机制参考。 [1] [2] [3]
- CL=F近期价格背景缺失或未核实：本轮未提供usage=fact的CL=F价格快照；E10为raw检索材料，且内部油价表述不一致，不能确认“最近原油价格走高”已经发生。因此后续分析均按条件假设处理，不写成已发生事实。 [3]


**未核实的检索材料**
- 宏观事件 / Economic Calendar [8]；仅为检索线索，本轮未形成通过事实校验的对应解释。
- 宏观事件 / Web Search [9]；仅为检索线索，本轮未形成通过事实校验的对应解释。
- [未完成] 以“如果最近原油价格走高”为条件，解释对通胀与物价的传导；实际数据与假设推演分开。。
- [未完成] 以“如果最近原油价格走高”为条件，解释对利率预期的传导；实际数据与假设推演分开。。
- [未完成] 以“如果最近原油价格走高”为条件，解释对航空股的传导；实际数据与假设推演分开。。
- [未完成] 近期价格事实或明确尚未核实；不能把条件假设写成已发生。。

## 风险与分歧

- Policy transmission lag risk
- Macro data revision risk

## 限制

- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。
- 解释基于列出的材料，不替代原始公告或数据核验。

## 来源

- [1] 宏观事件 / FRED / 2026-08-01
- [2] 宏观事件 / FRED / 2026-09-01
- [3] 宏观事件 / search
- [4] 宏观事件 / FRED / 2026-10-01
- [8] 宏观事件 / Economic Calendar
- [9] 宏观事件 / Web Search

## h09_nflx_news

问题：汇总 NFLX 最近72小时值得关注的新闻，合并同一事件的重复报道；过期报道和未证实传闻单独标出。

来源：regression-v2；耗时 252.594 秒。

## NFLX · 部分完成

**新闻与催化剂**

- 样本舆情积极，平均分 0.03；情绪样本 8 条，当前合格报道 0 条。舆情标签不代表投资方向。 [1]
  - 整体舆情偏多，但近期价格走弱，存在情绪与价格背离。
- 媒体归因报道：2026-10-02T00:10:57+00:00 Netflix (NFLX) Is Pushing Further Into Live Programming And Cloud Gaming [2]

**研究判断与风险**

- 在最近72小时窗口内，NFLX 已确认且值得关注的新闻可归纳为三类。第一类是业务与资本配置动态：Yahoo Finance 于 2026-10-02 报道 Netflix 正加强直播、视频播客与云游戏布局，宣布大规模股票回购，并探索收购华纳兄弟的可能性（E7）。第二类是管理层增长表述：Proactive Investors 与 StockTwits 在 2026-10-01 至 2026-10-02 转述 co-CEO Ted Sarandos 于 Bloomberg Screentime 的发言，称增长不及预期且上半年观看量仅小幅上升（E12、E11）；Motley Fool 于同日发表的观点性文章引用同一发言，并补充下调评级、艾美奖失利及 YouTube 竞争等归因（E8），三者属于同一事件的不同出处，已合并。第三类是日历催化：新闻快照显示当前窗口聚合 2 个财报类日历事件，日期为 2026-10-20（E4）。上述事件均具备明确发布时间或数据接口记录，处于 72 小时覆盖范围内。 [2] [3] [4] [5] [1]
- 日历催化方面，新闻快照显示当前窗口聚合 2 个财报类日历事件，日期为 2026-10-20（E4）。该记录来自数据接口排定事件，可作为已排定催化处理，但其性质不是新发生的新闻事实。 [1]


## 风险与分歧

- 旧闻、未知发布时间、观点及检索线索不计入当前新闻催化，需结合原始披露核实。
- 新闻来源可靠度偏低，请结合一手披露文件核实关键结论。
- 本批次中检测到多个低可靠度来源。

## 限制

- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。
- 部分模型解释未通过事实绑定校验，已移除对应段落；其它已验证事实与论据仍保留。
- 催化事件聚合识别的是时点/关注度驱动因素，本身并不证明价格方向。

## 来源

- [1] NFLX 新闻与催化剂 / news_sentiment_snapshot / 2026-10-04T01:48:52.868991
- [2] [Netflix (NFLX) Is Pushing Further Into Live Programming And Cloud Gaming / finance.yahoo.com / 2026-10-02T00:10:57+00:00](https://finance.yahoo.com/media-advertising/articles/netflix-nflx-pushing-further-live-001057016.html?.tsrc=rss)
- [3] [Netflix co-CEO says streaming giant "isn't growing as fast as I want us to" / finance.yahoo.com / 2026-10-01T17:36:00+00:00](https://www.proactiveinvestors.com/companies/news/1099476/netflix-co-ceo-says-streaming-giant-isn-t-growing-as-fast-as-i-want-us-to-1099476.html?.tsrc=rss)
- [4] [NFLX Stock On Track For Fifth Week Of Declines: Analyst Raises Concerns Over Growth After Co-CEO’s Remarks / finance.yahoo.com / 2026-10-02T01:00:28+00:00](https://stocktwits.com/news-articles/markets/equity/nflx-stock-on-track-for-fifth-week-of-declines-analyst-raises-concerns-over-growth-after-co-ceo-s-remarks/cZDSutERB0k?.tsrc=rss)
- [5] [Should You Buy Netflix On The Dip? / finance.yahoo.com / 2026-10-02T15:47:49+00:00](https://finance.yahoo.com/markets/stocks/articles/buy-netflix-dip-154749772.html?.tsrc=rss)

## h10_missing_subject

问题：现在还值得买它吗？

来源：regression-v2；耗时 0.016 秒。

**证据状态：暂不能形成方向判断**

- 结构化证据尚未就绪。

## h11_cashflow_concept

问题：自由现金流和净利润为什么会差很多？用虚构数字举例即可，不要查询股票行情。

来源：regression-v2；耗时 12.265 秒。

因为**净利润是“会计利润”**，而**自由现金流是“真金白银”**。两者计算规则不同，所以经常差很多。

主要差异来自这几类：

1. **折旧与摊销**
   净利润里扣掉了折旧摊销，但这些并没有实际付出现金，只是资产成本的账面分摊。
   → 算现金流时要加回来。

2. **资本开支（CapEx）**
   买设备、建厂房等大额支出，在会计上不会一次性计入当期净利润，而是通过折旧慢慢扣。
   → 算自由现金流时要一次性全额减去。

3. **营运资本变动**
   应收账款增加、存货增加，说明货卖出去了但钱还没收回来，或者货压在仓库里。
   → 这些会减少现金流，但不影响当期净利润。

4. **非现金项目**
   比如资产减值、股权激励费用、公允价值变动等，影响利润表，但不涉及现金。

---

**以下数字均为虚构，仅用于举例：**

假设有一家虚构的“甲公司”，某年度数据如下：

| 项目 | 金额（万元） |
|---|---:|
| 营业收入 | 10,000 |
| 净利润 | 1,500 |
| 折旧与摊销 | 800 |
| 资本开支 | 2,000 |
| 应收账款增加 | 600 |
| 存货增加 | 400 |

那么它的自由现金流大致可以这样算：

**自由现金流 ≈ 净利润 + 折旧摊销 − 资本开支 − 营运资本增加**

= 1,500 + 800 − 2,000 − 600 − 400
= **−700 万元**

可以看到：甲公司账面上**盈利 1,500 万元**，但因为当年花了大钱扩产（资本开支 2,000 万），同时有 1,000 万资金被应收账款和存货占用，实际自由现金流是**负 700 万元**。

---

**一句话总结：**
净利润告诉你“这门生意理论上赚不赚钱”，自由现金流告诉你“公司手里实际多出多少可以自由支配的钱”。前者受会计政策影响大，后者更接近企业真实的现金创造能力。

## h12_crm_report

问题：给我一份 Salesforce（CRM）的正式投资研究报告，覆盖业务、竞争、最新财务、估值、未来90天催化和风险，关键事实附可追溯来源。

来源：regression-v3-targeted；耗时 623.219 秒。

## 总判断

无法判断：本轮尚未形成证据支持的总体结论。

## CRM · 部分完成

**业务与商业模式**

- 2026-08-27 Salesforce, Inc. 10-Q (2026-08-27)；已读取披露正文。
竞争正文摘录：Table of Contents factors, including customer dissatisfaction, customers’ spending levels, mix of customer base, decreases in the number of users at our customers, customer mergers and acquisitions, competition, pricing increases or changes, such as the increased prevalence of consumption-based pricing models and economic downturns. Additionally, our transition toward more complex pricing structures, including AI-driven consumption models, may make it more difficult to optimize our pricing, predict attrition rates, and accurately forecast revenue. Our future success depends in part on our ability to sell additional features and services, more subscriptions or enhanced editions of our services to our current customers. This may also require increasingly sophisticated and costly sales efforts that are targeted at senior management. Similarly, the rate at which our customers purchase new or enhanced services depends on a number of factors, including general economic conditions and customer receptiveness to price changes related to these additional features and services. In addition, the markets and monetization strategies for certain offerings, including Agentforce and Data 360, remain relatively new and uncertain and may present additional risks and challenges. If customer usage for these offerings is below expected levels, we may not be able to adequately forecast renewals or op
管理层讨论摘录：ITEM 2. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS This Quarterly Report on Form 10-Q contains forward-looking statements within the meaning of the Private Securities Litigation Reform Act of 1995. All statements other than statements of historical fact, which may consist of, among other things, trend analyses and statements regarding future events, future financial performance, anticipated growth, and industry prospects, are forward-looking. Words such as “aims,” “anticipates,” “assumes,” “believes,” “commitments,” “could,” “estimates,” “expects,” “forecasts,” “foresees,” “goals,” “intends,” “may,” “plans,” “predicts,” “projects,” “seeks,” “should,” “targets” and “would,” and variations of such words and similar expressions are intended to identify such forward-looking statements. These forward-looking statements are inherently uncertain and based on management’s current expectations and assumptions, which are subject to risks and uncertainties that are difficult to predict, including those described in Part I, Item 2, “Management’s Discussion and Analysis of Financial Condition and Results of Operations,” Part I, Item 3, “Quantitative and Qualitative Disclosures About Market Risk,” Part II, Item 1A, “Risk Factors,” and elsewhere in this Quarterly Report on Form 10-Q. Moreover, we operate in a very competitive and rapidly changing env [12]
- 2026-05-28 Salesforce, Inc. 10-Q (2026-05-28)；该来源为公告索引，财务结论需核对文件正文。 [13]
- 2026-03-02 Salesforce, Inc. 10-K (2026-03-02)；已读取披露正文。
业务正文摘录：ITEM 1. BUSINESS Overview Salesforce, Inc. (“Salesforce,” the “Company,” “we” or “our”) is a global leader in customer relationship management (“CRM”) technology, helping organizations of any size become agentic enterprises. Founded in 1999, we bring humans, agents, applications, and data together on a trusted, unified platform to unlock growth and innovation. Our artificial intelligence (“AI”) powered Agentforce 360 Platform unites our offerings — spanning sales, service, marketing, commerce, collaboration, data management, integration, analytics, IT service, industry verticals and more — on a single, intelligent platform for trusted enterprise execution. We unify and harmonize across systems, applications and devices to create a complete view of customers. With this single source of customer truth powering agents, teams can be more responsive, productive and efficient and deliver AI-powered, personalized and automated experiences across every channel. With Agentforce, the agentic layer of the Agentforce 360 Platform, our customers can build and deploy always-on digital labor for employees and customers, leveraging autonomous AI agents across business functions that aim to increase productivity, lower costs and drive operational efficiencies. With Agentforce, AI is embedded in the flow of work — in the applications that our customers already use every day. Every Agentforce-emb
竞争正文摘录：m acquisitions. Performance, functional depth, security, usability, ease of integration and configuration and sustainability of our solutions influence our technology decisions and product direction. Competition The market for our service offerings is highly competitive, rapidly evolving and fragmented, and subject to changing technology with low barriers to entry, shifting customer needs and frequent introductions of new products and services. Our current competitors include: • vendors of packaged business software, as well as companies offering enterprise applications delivered through on-premises offerings from enterprise software application vendors and cloud computing application service providers, either individually or with others; • AI-native companies and emerging startups that leverage generative AI and large language models as the core foundation of their architecture, offering highly specialized, autonomous, or automated solutions that may bypass traditional business process workflows or displace established user interfaces; • software companies that provide their product or service free of charge as a single product or when bundled with other offerings, or only charge a premium for advanced features and functionality, as well as companies that offer solutions that are sold without a direct sales organization; • vendors who offer software tailored to specific servic
管理层讨论摘录：ITEM 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS The following discussion contains forward-looking statements, including, without limitation, our expectations and statements regarding our outlook and future revenues, expenses, results of operations, liquidity, plans, strategies and management objectives and any assumptions underlying any of the foregoing. Our actual results may differ significantly from those projected in the forward-looking statements. Our forward-looking statements and factors that might cause future actual results to differ materially from our recent results or those projected in the forward-looking statements include, but are not limited to, those discussed in the section titled “Forward-Looking Information” and “Risk Factors” of this Annual Report on Form 10-K. Except as required by law, we assume no obligation to update the forward-looking statements or our risk factors for any reason. The following section generally discusses fiscal 2026 and 2025 items and year-to-year comparisons between fiscal 2026 and 2025, as well as certain fiscal 2024 items. Discussions of fiscal 2024 items and year-to-year comparisons between fiscal 2025 and 2024 that are not included in this Form 10-K can be found in “Management’s Discussion and Analysis of Financial Condition and Results of Operations” in Part II, Item 7 of our Annual [14]
- 2025-12-04 Salesforce, Inc. 10-Q (2025-12-04)；该来源为公告索引，财务结论需核对文件正文。 [15]
- 2025-09-04 Salesforce, Inc. 10-Q (2025-09-04)；该来源为公告索引，财务结论需核对文件正文。 [16]
- 2025-05-29 Salesforce, Inc. 10-Q (2025-05-29)；该来源为公告索引，财务结论需核对文件正文。 [17]
- 2026-07-31 营收 113.45 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 毛利 86.96 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 经营利润 23.31 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 净利润 35.26 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 EPS 4.29 USD/shares（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 经营现金流 12.69 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 自由现金流 10.98 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 总资产 1,096.2 亿 USD（期末余额）；披露日 2026-08-27
2026-07-31 总负债 712.42 亿 USD（期末余额）；披露日 2026-08-27 [19]
- 2026-07-31 营收 113.45 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 毛利 86.96 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 经营利润 23.31 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 净利润 35.26 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 EPS 4.29 USD/shares（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 经营现金流 12.69 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 自由现金流 10.98 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
2026-07-31 总资产 1,096.2 亿 USD（期末余额）；披露日 2026-08-27
2026-07-31 总负债 712.42 亿 USD（期末余额）；披露日 2026-08-27 [19]
- 2026-09-17 Salesforce, Inc. 8-K (2026-09-17)；该来源为公告索引，财务结论需核对文件正文。 [24]
- 2026-09-04 Salesforce, Inc. 8-K (2026-09-04)；该来源为公告索引，财务结论需核对文件正文。 [25]
- 2026-08-26 Salesforce, Inc. 8-K (2026-08-26)；该来源为公告索引，财务结论需核对文件正文。 [26]
- 2026-08-05 Salesforce, Inc. 8-K (2026-08-05)；该来源为公告索引，财务结论需核对文件正文。 [27]
- 2026-06-02 Salesforce, Inc. 8-K (2026-06-02)；该来源为公告索引，财务结论需核对文件正文。 [28]
- 市值：1,931.5 亿 USD
公司：Salesforce, Inc.
行业大类：Technology
细分行业：Software - Application
Trailing P/E：21.51
Forward P/E：14.66
P/B：5.03
P/S：4.40
EV/EBITDA：17.38
业务：Salesforce, Inc. provides customer relationship management technology services that connect companies and customers together in the United States, Europe, and the Asia Pacific. The company offers Agen... [30]
[数据缺失] 已取得相关材料，但本轮尚未形成通过引用校验的对应解释。

**竞争格局**

- 市值：1,931.5 亿 USD
公司：Salesforce, Inc.
行业大类：Technology
细分行业：Software - Application
Trailing P/E：21.51
Forward P/E：14.66
P/B：5.03
P/S：4.40
EV/EBITDA：17.38
业务：Salesforce, Inc. provides customer relationship management technology services that connect companies and customers together in the United States, Europe, and the Asia Pacific. The company offers Agen... [30]
- 样本舆情积极，平均分 0.18；情绪样本 8 条，当前合格报道 0 条。舆情标签不代表投资方向。
整体舆情偏多，但近期价格走弱，存在情绪与价格背离。 [2]
[数据缺失] 已取得相关材料，但本轮尚未形成通过引用校验的对应解释。

**价格**

- CRM 最新可用报价 234.69 USD；源日期：2026-10-02（来源仅提供交易日，不代表精确成交时刻）；常规交易时段的日线收盘价，非盘后价格。 [11]

**财务与公告**

- 2026-08-27 Salesforce, Inc. 10-Q (2026-08-27)；已读取披露正文。 [12]
  - 竞争正文摘录：Table of Contents factors, including customer dissatisfaction, customers’ spending levels, mix of customer base, decreases in the number of users at our customers, customer mergers and acquisitions, competition, pricing increases or changes, such as the increased prevalence of consumption-based pricing models and economic downturns. Additionally, our transition toward more complex pricing structures, including AI-driven consumption models, may make it more difficult to optimize our pricing, predict attrition rates, and accurately forecast revenue. Our future success depends in part on our ability to sell additional features and services, more subscriptions or enhanced editions of our services to our current customers. This may also require increasingly sophisticated and costly sales efforts that are targeted at senior management. Similarly, the rate at which our customers purchase new or enhanced services depends on a number of factors, including general economic conditions and customer receptiveness to price changes related to these additional features and services. In addition, the markets and monetization strategies for certain offerings, including Agentforce and Data 360, remain relatively new and uncertain and may present additional risks and challenges. If customer usage for these offerings is below expected levels, we may not be able to adequately forecast renewals or op
  - 管理层讨论摘录：ITEM 2. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS This Quarterly Report on Form 10-Q contains forward-looking statements within the meaning of the Private Securities Litigation Reform Act of 1995. All statements other than statements of historical fact, which may consist of, among other things, trend analyses and statements regarding future events, future financial performance, anticipated growth, and industry prospects, are forward-looking. Words such as “aims,” “anticipates,” “assumes,” “believes,” “commitments,” “could,” “estimates,” “expects,” “forecasts,” “foresees,” “goals,” “intends,” “may,” “plans,” “predicts,” “projects,” “seeks,” “should,” “targets” and “would,” and variations of such words and similar expressions are intended to identify such forward-looking statements. These forward-looking statements are inherently uncertain and based on management’s current expectations and assumptions, which are subject to risks and uncertainties that are difficult to predict, including those described in Part I, Item 2, “Management’s Discussion and Analysis of Financial Condition and Results of Operations,” Part I, Item 3, “Quantitative and Qualitative Disclosures About Market Risk,” Part II, Item 1A, “Risk Factors,” and elsewhere in this Quarterly Report on Form 10-Q. Moreover, we operate in a very competitive and rapidly changing env
- 2026-05-28 Salesforce, Inc. 10-Q (2026-05-28)；该来源为公告索引，财务结论需核对文件正文。 [13]
- 2026-03-02 Salesforce, Inc. 10-K (2026-03-02)；已读取披露正文。 [14]
  - 业务正文摘录：ITEM 1. BUSINESS Overview Salesforce, Inc. (“Salesforce,” the “Company,” “we” or “our”) is a global leader in customer relationship management (“CRM”) technology, helping organizations of any size become agentic enterprises. Founded in 1999, we bring humans, agents, applications, and data together on a trusted, unified platform to unlock growth and innovation. Our artificial intelligence (“AI”) powered Agentforce 360 Platform unites our offerings — spanning sales, service, marketing, commerce, collaboration, data management, integration, analytics, IT service, industry verticals and more — on a single, intelligent platform for trusted enterprise execution. We unify and harmonize across systems, applications and devices to create a complete view of customers. With this single source of customer truth powering agents, teams can be more responsive, productive and efficient and deliver AI-powered, personalized and automated experiences across every channel. With Agentforce, the agentic layer of the Agentforce 360 Platform, our customers can build and deploy always-on digital labor for employees and customers, leveraging autonomous AI agents across business functions that aim to increase productivity, lower costs and drive operational efficiencies. With Agentforce, AI is embedded in the flow of work — in the applications that our customers already use every day. Every Agentforce-emb
  - 竞争正文摘录：m acquisitions. Performance, functional depth, security, usability, ease of integration and configuration and sustainability of our solutions influence our technology decisions and product direction. Competition The market for our service offerings is highly competitive, rapidly evolving and fragmented, and subject to changing technology with low barriers to entry, shifting customer needs and frequent introductions of new products and services. Our current competitors include: • vendors of packaged business software, as well as companies offering enterprise applications delivered through on-premises offerings from enterprise software application vendors and cloud computing application service providers, either individually or with others; • AI-native companies and emerging startups that leverage generative AI and large language models as the core foundation of their architecture, offering highly specialized, autonomous, or automated solutions that may bypass traditional business process workflows or displace established user interfaces; • software companies that provide their product or service free of charge as a single product or when bundled with other offerings, or only charge a premium for advanced features and functionality, as well as companies that offer solutions that are sold without a direct sales organization; • vendors who offer software tailored to specific servic
  - 管理层讨论摘录：ITEM 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS The following discussion contains forward-looking statements, including, without limitation, our expectations and statements regarding our outlook and future revenues, expenses, results of operations, liquidity, plans, strategies and management objectives and any assumptions underlying any of the foregoing. Our actual results may differ significantly from those projected in the forward-looking statements. Our forward-looking statements and factors that might cause future actual results to differ materially from our recent results or those projected in the forward-looking statements include, but are not limited to, those discussed in the section titled “Forward-Looking Information” and “Risk Factors” of this Annual Report on Form 10-K. Except as required by law, we assume no obligation to update the forward-looking statements or our risk factors for any reason. The following section generally discusses fiscal 2026 and 2025 items and year-to-year comparisons between fiscal 2026 and 2025, as well as certain fiscal 2024 items. Discussions of fiscal 2024 items and year-to-year comparisons between fiscal 2025 and 2024 that are not included in this Form 10-K can be found in “Management’s Discussion and Analysis of Financial Condition and Results of Operations” in Part II, Item 7 of our Annual
- 2025-12-04 Salesforce, Inc. 10-Q (2025-12-04)；该来源为公告索引，财务结论需核对文件正文。 [15]
- 2025-09-04 Salesforce, Inc. 10-Q (2025-09-04)；该来源为公告索引，财务结论需核对文件正文。 [16]
- 2025-05-29 Salesforce, Inc. 10-Q (2025-05-29)；该来源为公告索引，财务结论需核对文件正文。 [17]
- 2026-07-31 营收 113.45 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27 [19]
  - 2026-07-31 毛利 86.96 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
  - 2026-07-31 经营利润 23.31 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
  - 2026-07-31 净利润 35.26 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
  - 2026-07-31 EPS 4.29 USD/shares（2026-05-01 至 2026-07-31）；披露日 2026-08-27
  - 2026-07-31 经营现金流 12.69 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
  - 2026-07-31 自由现金流 10.98 亿 USD（2026-05-01 至 2026-07-31）；披露日 2026-08-27
  - 2026-07-31 总资产 1,096.2 亿 USD（期末余额）；披露日 2026-08-27
  - 2026-07-31 总负债 712.42 亿 USD（期末余额）；披露日 2026-08-27
- 2026-09-17 Salesforce, Inc. 8-K (2026-09-17)；该来源为公告索引，财务结论需核对文件正文。 [24]
- 2026-09-04 Salesforce, Inc. 8-K (2026-09-04)；该来源为公告索引，财务结论需核对文件正文。 [25]
- 2026-08-26 Salesforce, Inc. 8-K (2026-08-26)；该来源为公告索引，财务结论需核对文件正文。 [26]
- 2026-08-05 Salesforce, Inc. 8-K (2026-08-05)；该来源为公告索引，财务结论需核对文件正文。 [27]
- 2026-06-02 Salesforce, Inc. 8-K (2026-06-02)；该来源为公告索引，财务结论需核对文件正文。 [28]

**风险**

- 历史回撤 -70.5%（2008-06-23 至 2008-11-19），到谷底 149 天，恢复耗时 405 天。 [18]
  - 快照时间：源数据时间未提供；历史模型不代表未来表现。
- 因子 beta：市场 0.462；成长 0.1516；小盘 0.094；利率 0.0369；黄金 -0.0485；美元 0.202 [31]
  - 历史年化波动率 47.68%
  - 观察期最大回撤 -43.33%
  - 观察窗口 252 个交易日
  - 有效样本 251 个
  - 市场模型 R² 0.0159
  - 快照时间：2026-10-04T01:56:45.743133；历史模型不代表未来表现。

**盈利预期**

- 当前财政季度 共识 EPS 3.4463 [币种未提供]/股，区间 3.39 至 3.85 [币种未提供]/股，覆盖分析师 42 位，供应商预期增长 6.04% [20]
  - 下一财政季度 共识 EPS 3.5562 [币种未提供]/股，区间 3.45 至 4.01 [币种未提供]/股，覆盖分析师 41 位，供应商预期增长 -6.66%
  - 当前财年 共识 EPS 16.7543 [币种未提供]/股，区间 16.67 至 17.6 [币种未提供]/股，覆盖分析师 52 位，供应商预期增长 33.82%
  - 下一财年 共识 EPS 16.0207 [币种未提供]/股，区间 14.6632 至 18.12 [币种未提供]/股，覆盖分析师 53 位，供应商预期增长 -4.38%
  - 当前财政季度 近 7 天 EPS 预期：上修 1 次，下修 0 次
  - 当前财政季度 近 30 天 EPS 预期：上修 34 次，下修 4 次
  - 下一财政季度 近 7 天 EPS 预期：上修 2 次，下修 1 次
  - 下一财政季度 近 30 天 EPS 预期：上修 6 次，下修 30 次
  - 当前财年 近 7 天 EPS 预期：上修 3 次，下修 0 次
  - 当前财年 近 30 天 EPS 预期：上修 48 次，下修 0 次
  - 下一财年 近 7 天 EPS 预期：上修 3 次，下修 2 次
  - 下一财年 近 30 天 EPS 预期：上修 38 次，下修 9 次
  - 当前财政季度 共识 EPS：30 天前 3.4281，当前 3.4463 [币种未提供]/股
  - 下一财政季度 共识 EPS：30 天前 3.5448，当前 3.5562 [币种未提供]/股
  - 当前财年 共识 EPS：30 天前 16.4359，当前 16.7543 [币种未提供]/股
  - 下一财年 共识 EPS：30 天前 15.9145，当前 16.0207 [币种未提供]/股
  - 快照时间：2026-10-04T01:56:45.731509。预期并非已实现业绩。

**技术面**

- MA20 241.13 | MA50 220.06 [21]
- Option metrics: available [22]
- Market sentiment: CNN Fear & Greed Index: 31.2 (fear) [23]
- RSI(14) 28.44 | MACD 1.8531 | 信号线 4.8005 [21]
- 支撑 221.18 | 阻力 263.60 | 最新成交量 7901800 | 20日均量 12083870 | 量能 0.65x [21]

**事件日历**

- 财报：2026-12-02 预期财报发布日期（供应商日历，日期以公司或官方披露为准） [29]
  - 分红：2026-10-07 Dividend Date（供应商日历，日期以公司或官方披露为准）
  - 本轮供应商日历查询窗口为未来 90 天，不代表已取得全部事件；快照时间 2026-10-04T08:56:45.739233+00:00。

**公司与估值**

- 市值：1,931.5 亿 USD [30]
  - 公司：Salesforce, Inc.
  - 行业大类：Technology
  - 细分行业：Software - Application
  - Trailing P/E：21.51
  - Forward P/E：14.66
  - P/B：5.03
  - P/S：4.40
  - EV/EBITDA：17.38
  - 业务：Salesforce, Inc. provides customer relationship management technology services that connect companies and customers together in the United States, Europe, and the Asia Pacific. The company offers Agen...

**新闻与催化剂**

- 样本舆情积极，平均分 0.18；情绪样本 8 条，当前合格报道 0 条。舆情标签不代表投资方向。 [2]
  - 整体舆情偏多，但近期价格走弱，存在情绪与价格背离。

**基本面**

- 2026-07-31 营收: $11.35B；单位 USD；来源口径 quarterly。 [1]
- 2026-07-31 净利润: $3.53B；单位 USD；来源口径 quarterly。 [1]
- 2026-07-31 营业利润: $2.42B；单位 USD；来源口径 quarterly。 [1]
- 2026-07-31 经营现金流: $1.27B；单位 USD；来源口径 quarterly。 [1]
- 2026-07-31 总资产: $109.62B；单位 USD；来源口径 instant。 [1]
- 2026-07-31 总负债: $71.24B；单位 USD；来源口径 instant。 [1]

**宏观事件**

- 2026-09-01 联邦基金利率（历史观测） 3.75%；该序列观测不等同于最近一次 FOMC 决议确认。 [32]
- 2026-08-01 CPI 通胀同比 3.35% [33]
- 2026-09-01 失业率 4.2% [32]
- 2026-04-01 GDP 增速 2.2% [34]
- 2026-10-01 10 年期美债收益率 5.24% [35]
- 2026-10-02 10Y-2Y 利差 0.45个百分点 [36]
- 市场情绪监测: CNN Fear & Greed Index: 31.2 (fear) [37]

**研究判断与风险**

- CRM 成长质量向好：营收同比 10.8%。 [1]
- CRM 经营现金流明显低于净利润，削弱盈利质量。 [1]
- CRM 负债/资产比为 65.0%，影响资产负债表风险。 [1]
- CRM 整体新闻舆情倾向偏多（平均情绪分 +0.18）。 [2]
- CRM 在当前舆情窗口内聚合了 0 个新闻/日历催化事件。 [2]
- CRM 情绪-价格传导状态为背离：整体舆情偏多，但近期价格走弱，存在情绪与价格背离。 [2]
- CRM 次要新闻信号或待核实线索（发布时间未知；检索线索，待核实）：Salesforce (CRM) Is Buying Back $50 Billion of Stock. What Does That Say About Growth? [3]
- CRM 次要新闻信号或待核实线索（发布时间未知；检索线索，待核实；来源待核实）：Is Salesforce (CRM) a Buy Right Now? (October 2026) | The Money GPS [4]
- CRM 次要新闻信号或待核实线索（发布时间未知；检索线索，待核实；来源待核实）：Salesforce (NYSE:CRM) Shares Climb 3% – Time to Buy? - Daily Political [5]
- CRM 次要新闻信号或待核实线索（发布时间未知；检索线索，待核实；来源待核实）：Salesforce stock consolidates within recent range with momentum signals mixed: weekly analysis [6]
- CRM 次要新闻信号或待核实线索（发布时间未知；检索线索，待核实；来源待核实）：Salesforce (NYSE:CRM) Shares Up 2% – Should You Buy? - The Cerbat Gem [7]
- CRM 价格动量偏弱：近 1 月 -8.66%，近 3 月 +41.68%，状态 偏弱。 [8]
- CRM 相对 SPY 的相对强度：近 1 月 -9.24%，近 3 月 +39.23%。 [9]
- CRM 量价确认为缩量波动；最新成交量为 20 日均量的 0.65x。 [8]
- CRM 波动率状态显示 ATR14 +3.37%，ATM IV 暂无数据，PCR 暂无数据。 [10]
- CRM 关键价位风险集中于 20 日支撑 221.18 与 20 日压力 263.60。 [8]


**未核实的检索材料**
- Salesforce (CRM) Is Buying Back $50 Billion of Stock. What Does That Say About Growth? / finance.yahoo.com / 2026-10-04T04:07:23+00:00 [38]；观点；仅为检索线索，本轮未形成通过事实校验的对应解释。
- Salesforce vs. CrowdStrike: What Revenue Growth Trends for These Software Giants Tell Investors / finance.yahoo.com / 2026-10-03T03:45:48+00:00 [39]；观点；仅为检索线索，本轮未形成通过事实校验的对应解释。
- Salesforce vs. Palantir: Which AI Software Stock Is a Better Buy in 2026? / finance.yahoo.com / 2026-10-02T15:45:01+00:00 [40]；观点；仅为检索线索，本轮未形成通过事实校验的对应解释。
- Salesforce vs. CrowdStrike: Which Tech Stock Is a Better Buy in 2026? / finance.yahoo.com / 2026-10-02T14:49:02+00:00 [41]；观点；仅为检索线索，本轮未形成通过事实校验的对应解释。
- Salesforce Expands AI Bundles: Will Higher Adoption Boost ARR? / finance.yahoo.com / 2026-10-02T09:45:00+00:00 [42]；观点；仅为检索线索，本轮未形成通过事实校验的对应解释。
- Salesforce (CRM) Adds Fresh AI Deals, Is The Stock Still A Bargain? / finance.yahoo.com / 2026-10-02T00:11:39+00:00 [43]；观点；仅为检索线索，本轮未形成通过事实校验的对应解释。
- CRM 文档事实 / search [44]；仅为检索线索，本轮未形成通过事实校验的对应解释。
- 宏观事件 / Economic Calendar [45]；仅为检索线索，本轮未形成通过事实校验的对应解释。
- 宏观事件 / Web Search [46]；仅为检索线索，本轮未形成通过事实校验的对应解释。
- [未完成] 估值口径与依据。
- [未完成] 业务与商业模式。
- [未完成] 竞争格局。
- [未完成] 新闻、事件及催化。
- [未完成] 主要风险及依据。
- [未完成] 按未来90天覆盖事件；确认事实与观察条件分开。

## 风险与分歧

- 杠杆率偏高（负债/资产 = 65% > 60%），偿债压力较大。
- 旧闻、未知发布时间、观点及检索线索不计入当前新闻催化，需结合原始披露核实。
- 新闻来源可靠度偏低，请结合一手披露文件核实关键结论。
- 本批次中检测到多个低可靠度来源。
- RSI 进入超卖区间，波动性风险较高。
- 价格变动缺少量能确认，成交量约为20日均量 0.65x
- 当前较阶段高点回撤 -19.39%，趋势修复仍需确认
- 历史区间最大回撤 -48.44%，下行尾部风险不可忽视
- Policy transmission lag risk
- Macro data revision risk

## 限制

- 财务报表快照，最终投资决策前请核对原始申报文件。
- 现金流质量结论仅基于可用报表行项目。
- 杠杆率偏高（负债/资产 = 65% > 60%），偿债压力较大。
- 聚合情绪的完整度受限于可用的新闻情绪数据源与标题。
- 催化事件聚合识别的是时点/关注度驱动因素，本身并不证明价格方向。
- 情绪传导基于近期可用价格数据，可能缺失盘中或盘后波动。
- 次要市场媒体信号，请勿将其作为独立投资证据。
- publication_time_unknown
- content_discovery
- source_unclassified
- 价格动量基于历史收益率，不应视为预测。
- 相对强度当前基于基准 ETF，同业相对强度需要单独的同业样本集。
- 量价确认是短周期行为信号，可能快速反转。
- 当工具未提供时，期权字段可能缺失 IV rank 与完整期限结构。
- 关键价位由近期价格区间推导，并非完整技术形态模型。
- 该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。
- 模型合成不可用，结论来自已校验证据
- 时间范围仅覆盖本轮取得的供应商资料，不能据此断言窗口内没有其它事件；预期日历日期仍需公司或官方确认。

## 来源

- [1] [CRM 基本面 / yfinance / 2026-07-31](https://finance.yahoo.com/quote/CRM/financials/)
- [2] CRM 新闻与催化剂 / news_sentiment_snapshot / 2026-10-04T01:56:51.112328
- [3] [Salesforce (CRM) Is Buying Back $50 Billion of Stock. What Does That Say About Growth? / finance.yahoo.com / 2026-10-04T01:56:51.359222](https://finance.yahoo.com/markets/stocks/articles/salesforce-crm-buying-back-50-040723292.html)
- [4] [Is Salesforce (CRM) a Buy Right Now? (October 2026) | The Money GPS / themoneygps.com / 2026-10-04T01:56:51.359222](https://themoneygps.com/is-crm-a-buy)
- [5] [Salesforce (NYSE:CRM) Shares Climb 3% – Time to Buy? - Daily Political / dailypolitical.com / 2026-10-04T01:56:51.359222](https://www.dailypolitical.com/2026/10/03/salesforce-nysecrm-shares-climb-3-time-to-buy.html)
- [6] [Salesforce stock consolidates within recent range with momentum signals mixed: weekly analysis / tradersunion.com / 2026-10-04T01:56:51.359222](https://tradersunion.com/news/stocks/show/3609471-salesforce-slips-1-00percent-this-week/)
- [7] [Salesforce (NYSE:CRM) Shares Up 2% – Should You Buy? - The Cerbat Gem / thecerbatgem.com / 2026-10-04T01:56:51.359222](https://www.thecerbatgem.com/2026/10/02/salesforce-nysecrm-shares-up-2-should-you-buy.html)
- [8] CRM 价格 / price_history / 2026-10-02
- [9] CRM 价格 / benchmark_history / 2026-10-02
- [10] CRM 价格 / price_history
- [11] CRM 价格 / twelve_data / 2026-10-02
- [12] [Salesforce, Inc. 10-Q (2026-08-27) / sec_edgar / 2026-08-27](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000190/crm-20260731.htm)
- [13] [Salesforce, Inc. 10-Q (2026-05-28) / sec_edgar / 2026-05-28](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000127/crm-20260430.htm)
- [14] [Salesforce, Inc. 10-K (2026-03-02) / sec_edgar / 2026-03-02](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm)
- [15] [Salesforce, Inc. 10-Q (2025-12-04) / sec_edgar / 2025-12-04](https://www.sec.gov/Archives/edgar/data/1108524/000110852425000238/crm-20251031.htm)
- [16] [Salesforce, Inc. 10-Q (2025-09-04) / sec_edgar / 2025-09-04](https://www.sec.gov/Archives/edgar/data/1108524/000110852425000088/crm-20250731.htm)
- [17] [Salesforce, Inc. 10-Q (2025-05-29) / sec_edgar / 2025-05-29](https://www.sec.gov/Archives/edgar/data/1108524/000110852425000030/crm-20250430.htm)
- [18] CRM 风险 / analyze_historical_drawdowns
- [19] [CRM 财务与公告 / 2026-07-31](https://data.sec.gov/api/xbrl/companyfacts/CIK0001108524.json)
- [20] CRM 盈利预期 / 2026-10-04T01:56:45.731509
- [21] [CRM 技术面 / twelve_data / 2026-10-02](https://finance.yahoo.com/quote/CRM/history/)
- [22] CRM 技术面 / yfinance_options / 2026-10-04T01:56:45.973020
- [23] 技术面 / market_sentiment / 2026-10-02
- [24] [Salesforce, Inc. 8-K (2026-09-17) / sec_edgar / 2026-09-17](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000210/crm-20260916.htm)
- [25] [Salesforce, Inc. 8-K (2026-09-04) / sec_edgar / 2026-09-04](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000197/crm-20260902.htm)
- [26] [Salesforce, Inc. 8-K (2026-08-26) / sec_edgar / 2026-08-26](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000187/crm-20260826.htm)
- [27] [Salesforce, Inc. 8-K (2026-08-05) / sec_edgar / 2026-08-05](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000160/crm-20260805.htm)
- [28] [Salesforce, Inc. 8-K (2026-06-02) / sec_edgar / 2026-06-02](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000138/crm-20260527.htm)
- [29] CRM 事件日历 / 2026-10-04T08:56:45.739233+00:00
- [30] CRM 公司与估值
- [31] CRM 风险 / 2026-10-04T01:56:45.743133
- [32] 宏观事件 / FRED / 2026-09-01
- [33] 宏观事件 / FRED / 2026-08-01
- [34] 宏观事件 / FRED / 2026-04-01
- [35] 宏观事件 / FRED / 2026-10-01
- [36] 宏观事件 / FRED / 2026-10-02
- [37] 宏观事件 / CNN Fear & Greed
- [38] [Salesforce (CRM) Is Buying Back $50 Billion of Stock. What Does That Say About Growth? / finance.yahoo.com / 2026-10-04T04:07:23+00:00](https://finance.yahoo.com/markets/stocks/articles/salesforce-crm-buying-back-50-040723292.html?.tsrc=rss)
- [39] [Salesforce vs. CrowdStrike: What Revenue Growth Trends for These Software Giants Tell Investors / finance.yahoo.com / 2026-10-03T03:45:48+00:00](https://www.fool.com/coverage/charts/2026/10/02/salesforce-vs-crowdstrike-what-revenue-growth-trends-for-these-software-giants-tell-investors/?.tsrc=rss)
- [40] [Salesforce vs. Palantir: Which AI Software Stock Is a Better Buy in 2026? / finance.yahoo.com / 2026-10-02T15:45:01+00:00](https://www.fool.com/coverage/better-buy/2026/10/02/salesforce-vs-palantir-which-ai-software-stock-better-buy-2026/?.tsrc=rss)
- [41] [Salesforce vs. CrowdStrike: Which Tech Stock Is a Better Buy in 2026? / finance.yahoo.com / 2026-10-02T14:49:02+00:00](https://www.fool.com/coverage/better-buy/2026/10/02/salesforce-vs-crowdstrike-which-tech-stock-is-a-better-buy-in-2026/?.tsrc=rss)
- [42] [Salesforce Expands AI Bundles: Will Higher Adoption Boost ARR? / finance.yahoo.com / 2026-10-02T09:45:00+00:00](https://finance.yahoo.com/technology/ai/articles/salesforce-expands-ai-bundles-higher-094500029.html?.tsrc=rss)
- [43] [Salesforce (CRM) Adds Fresh AI Deals, Is The Stock Still A Bargain? / finance.yahoo.com / 2026-10-02T00:11:39+00:00](https://finance.yahoo.com/markets/stocks/articles/salesforce-crm-adds-fresh-ai-001139199.html?.tsrc=rss)
- [44] CRM 文档事实 / search
- [45] 宏观事件 / Economic Calendar
- [46] 宏观事件 / Web Search
