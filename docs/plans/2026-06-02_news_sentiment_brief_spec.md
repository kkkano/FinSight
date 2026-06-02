# 新闻舆情简报 Agent 设计规格

> 日期：2026-06-02
> 状态：已批准（设计定稿）
> 范围：Chat 对话场景的新闻请求（个股 + 泛市场），Selection Context 深度分析保留现状

---

## 1. 背景与问题诊断

### 用户痛点

在对话中说"拉几条 AAPL 新闻"，得到的是一个不带任何观点的原始新闻列表，且来源重复显示。
新闻 Agent 表现为"新闻搬运工"而非"舆情分析师"。

### 技术根因（三层叠加）

| # | 根因 | 位置 | 说明 |
|---|------|------|------|
| 1 | 子意图二分法设计缺陷 | `backend/orchestration/supervisor_agent.py:455` `_classify_news_subintent` | 无"分析/影响"等关键词的请求被判为 "fetch"，走纯列表路径。该二分假设（"用户只想看列表"）被产品决策否定 |
| 2 | 编码损坏的关键词检查吞掉分析 | `supervisor_agent.py:534` | `missing_news_word = ("??" not in summary_text) and ("news" not in summary_lower)`，其中 `"??"` 疑似中文"新闻"编码损坏产物。NewsAgent 的中文分析既不含 `??` 也不含英文 `news` → 被判"缺关键词" → 分析被丢弃，回退原始列表 |
| 3 | analyze 路径绕过 NewsAgent | `supervisor_agent.py:761` `_handle_news_analysis` | 所谓深度分析 = 原始新闻文本 + LLM prompt 套壳，未使用 NewsAgent 的舆情快照（情绪/催化/价格传导/可靠度）能力 |
| 4 | 来源重复显示 | `backend/tools/news.py:266` `_format_headline_line` | 输出格式 `[标题](url) (来源)`，但很多新闻标题末尾自带来源（如 "... - Yahoo Finance"），导致来源出现两次 |

### 现有资产（可复用）

`backend/agents/news_agent.py` 的 `NewsSentimentSnapshot` 已包含确定性计算的：

- `sentiment_bias`：情绪偏向（正/负/中性计数、平均分、置信度）
- `sentiment_trend`：情绪趋势（improving/deteriorating/stable）
- `heat`：讨论热度（新闻量 + 事件量代理）
- `catalyst_events`：催化事件（事件日历 + 高影响新闻）
- `price_transmission`：情绪-价格传导（共振/背离）
- 来源可靠度评分与汇总

**问题不在 NewsAgent 没有分析能力，而在 Chat 链路没把它用上。**

---

## 2. 产品决策记录

| 决策点 | 结论 | 备选项（被否决） |
|--------|------|------------------|
| 输出形态 | **舆情简报**：观点先行、证据（新闻列表）殿后 | 分析为主+列表折叠；保留两条路径 |
| fetch/analyze 二分 | **彻底废除**，所有新闻请求统一走舆情简报 | 保留二分但默认 analyze |
| 覆盖范围 | **个股 + 泛市场都做** | 只做个股 |
| 实现架构 | **确定性骨架 + LLM 观点**（方案 B） | 纯 Prompt 升级（A）；独立 SentimentAgent 重构（C） |

---

## 3. 设计

### 3.1 路由架构

**现状（废除）：**

```
NEWS 意图 → _classify_news_subintent() 关键词二分
              ├─ "fetch"   → _handle_news()          → 列表（分析被 bug 吞）
              └─ "analyze" → _handle_news_analysis() → LLM prompt 套壳
```

**新设计：**

```
NEWS 意图 → _handle_news_brief() 统一入口
              ├─ 有 Selection Context（点"问这条"）→ 引用新闻深度分析（保留现有实现）
              ├─ 有 ticker   → NewsAgent.research() → 个股舆情简报
              └─ 无 ticker   → 泛市场采集 + 主题聚类 → 泛市场舆情简报
```

改动清单：

- 删除 `_classify_news_subintent`（supervisor_agent.py:455-496）
- 删除 supervisor_agent.py:530-536 的关键词回退检查
- `_handle_news` 与 `_handle_news_analysis` 合并为 `_handle_news_brief`；
  Selection Context 分支原样保留（现有实现质量合格）

### 3.2 舆情简报渲染（确定性骨架 + LLM 观点）

新增 `backend/agents/sentiment_brief.py`（独立文件，单一职责：快照 → markdown 简报）。

#### 个股简报结构

| 区块 | 数据来源 | 生成方 |
|------|---------|--------|
| 标题行：情绪偏向 (+0.32) · 热度 · 催化数 | `snapshot.sentiment_bias` / `heat` | 代码渲染 |
| 📍 核心观点（2-4 句：事件主线 + 影响路径 + 短期判断） | snapshot + 新闻标题 → LLM | **LLM（唯一的 LLM 依赖）** |
| ⚡ 催化事件列表 | `snapshot.catalyst_events` | 代码渲染 |
| 📈 情绪与价格关系 | `snapshot.price_transmission` | 代码渲染 |
| ⚠️ 风险提示 | snapshot + reliability risks | 代码渲染 |
| 📰 依据新闻列表 | 新闻 items（来源去重后） | 代码渲染 |

#### 泛市场简报结构（无 ticker）

| 区块 | 数据来源 | 生成方 |
|------|---------|--------|
| 标题行：N 条新闻 · M 个主题 | 聚类结果 | 代码渲染 |
| 📍 核心观点 | 聚类结果 JSON 中的 `opinion` 字段 | LLM |
| 🗂 主题分布（2-4 个主题，各自情绪标签） | 聚类结果 JSON 中的 `themes` 字段 | 代码渲染 |
| 📰 依据新闻列表 | 新闻 items | 代码渲染 |

泛市场的主题聚类与核心观点由**同一次 LLM 调用**完成（返回结构化 JSON：
`{"themes": [{"name", "sentiment", "news_indices"}], "opinion": "..."}`），控制延迟与成本。

无价格传导、无事件日历区块（依赖 ticker，泛市场不适用）。

### 3.3 来源重复修复

`backend/tools/news.py` `_format_headline_line`：

1. 渲染前剥离标题末尾自带的来源后缀（` - Reuters`、` | Bloomberg`、` - Yahoo Finance` 等模式：
   `\s*[-|–|—]\s*[A-Za-z][A-Za-z\s.&']{2,30}$` 且匹配已知来源名或与 source 字段相同）
2. 统一格式：`[标题](url) — 来源 · 日期`，来源只出现一次

### 3.4 错误处理（降级阶梯）

```
LLM 观点段失败    → 简报骨架 + 催化 + 风险 + 列表照常输出（保住 80% 价值）
舆情快照无信号    → 跳过对应区块，不渲染 N/A 占位
新闻采集全失败    → 保留现有 fallback 文案（"新闻源连接失败，请稍后重试"）
泛市场聚类失败    → 退化为带情绪标注的新闻列表
```

区块"跳过" vs "显示说明文案"的边界：

- **数据源不可用 / 无数据** → 跳过区块（例：价格传导 `status="todo"`、无任何新闻）
- **数据源可用但分析结果为空** → 显示真实说明（例：有新闻但未识别到催化 →
  "未识别到催化事件"；情绪样本 < 3 → "情绪样本不足"）

判断标准：前者是"我们没做到"（不暴露半成品），后者是"市场确实如此"（真实信息，有价值）。

### 3.5 测试

- 新增 `backend/tests/test_sentiment_brief.py`：
  - 骨架渲染正确性（给定 snapshot → 期望 markdown 区块）
  - 来源去重（标题自带来源后缀时不重复）
  - LLM 失败降级（观点段缺失但骨架完整）
  - 空数据 / 无信号场景（区块跳过而非渲染占位）
  - 数据真实性防线（见 3.6 的每条防线各一个测试）
- 修改 `backend/tests/test_supervisor_agent.py`：删除 fetch/analyze 二分断言，改为统一路由断言
- 不受影响：`test_news_parsing.py` / `test_news_tags.py` / `test_news_url_sanitization.py`

### 3.6 数据真实性防线

核心原则：**拿不到真数据就承认拿不到，绝不用默认值演戏。**

| # | 坑 | 现状（假数据行为） | 防线 |
|---|----|--------------------|------|
| 1 | 假可靠度分数 | `news_agent.py:189` 无评分工具时返回编造的 `0.55 "medium"`，并进入证据 confidence | `reason == "default"` 的分数不渲染、不进 confidence 计算，简报中标记"未评估" |
| 2 | 价格传导半成品 | `news_agent.py:664` 拿不到价格时返回 `status="todo"` + TODO 文案 | `status == "todo"` 时整个"情绪与价格关系"区块不渲染，TODO 文案绝不输出给用户 |
| 3 | 催化检测对中文失效 | `news_agent.py:539` 催化关键词全英文，A 股中文新闻催化检测全漏（假阴性） | 补中文催化词（财报、超预期、不及预期、减持、增持、立案、调查、重组、并购、中标、回购、停牌、分红）；检测不到时显示"未识别到催化事件"而非"0 个" |
| 4 | 情绪样本不足装有数据 | 样本为 0 时仍输出 "neutral" + 拍脑袋 confidence | 样本 < 3 条时标题行显示"情绪样本不足"，不显示具体分数 |
| 5 | 泛市场低质数据 | 搜索文本硬解析新闻 confidence 仅 0.4 | 低置信（< 0.5）新闻在列表标注 ⚠️，且不参与主题聚类情绪统计 |

---

## 3.7 架构修正（2026-06-02 验证后补充）

**动态验证发现**：本 spec 3.1 节假设的路由架构（SupervisorAgent._handle_news）
**不是生产链路**——SupervisorAgent 在生产代码中零调用（仅测试引用），是 LangGraph 图之前的废弃架构。

**真实生产链路**（后端日志证实）：

```
Chat 快速模式: conversation_router → understand_request → planner
              → execute_plan_stub（拉新闻, :605-610）→ synthesize（LLM 合成回复, :1160/:2364）→ render
报告模式:      21节点图 → agent_adapter.py:285 → NewsAgent 等 7 agent 并行
```

**修正后的接入方案（方案 A：synthesize 节点接入）**：

- `synthesize.py` 在 `tool_name == "get_company_news"` 且有 ticker 时：
  新闻数据 → 构建轻量快照 → `render_stock_brief()` 输出舆情简报
- 无 ticker 的泛市场新闻：`render_market_brief()`
- NewsAgent（报告模式）继续走 B4 已完成的简报输出，两条路共用 sentiment_brief.py 渲染器
- SupervisorAgent 死代码（含 B5/B6 改动）整体删除

**经验教训**：改任何 Chat 行为前必须先用日志/grep 验证目标代码在真实调用链上，
不能只看代码结构"像不像"主路径。

## 4. 不在本次范围内

- 报告模式（investment_report）的新闻章节模板升级
- 论坛/社交媒体舆情源接入（Reddit、雪球等）
- 前端新闻卡片组件改版（简报为 markdown，现有渲染器可直接展示）
- A 股新闻源扩充（东方财富新闻已有，本次只修中文催化词）
