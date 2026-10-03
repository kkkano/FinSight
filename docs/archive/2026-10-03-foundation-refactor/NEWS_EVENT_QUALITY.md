# 新闻、舆情与事件质量收口

## 参考依据

按本次需求核查 [KKKKhazix/AIHOT](https://github.com/KKKKhazix/AIHOT)，固定参考提交为 `cc66cceb1dc7a0bc147e942e49ff94c9cee418c6`。通过 GitHub 内容接口实际阅读了 README、许可证、精选/归组说明及以下生产代码，未运行该项目、未复制其服务或接入其线上数据。

| 已核查的来源 | 实际机制 | FinSight 的取舍 |
| --- | --- | --- |
| [events/hot.ts](https://github.com/KKKKhazix/AIHOT/blob/cc66cceb1dc7a0bc147e942e49ff94c9cee418c6/packages/backend/src/events/hot.ts) | 48 小时窗口、24 小时半衰期；按来源背后的参与者去重；以来源时间进入窗口，采集延迟影响趋势可比性 | 采纳时间分离、去重、覆盖不等于可信度。FinSight 没有来源所有权/全网采集队列，故不冒充独立来源数，不移植热点趋势或用转载数提高事实可信度。 |
| [events/relate.ts](https://github.com/KKKKhazix/AIHOT/blob/cc66cceb1dc7a0bc147e942e49ff94c9cee418c6/packages/backend/src/events/relate.ts) | 分开 `SAME_OCCURRENCE`、`SAME_STORY`、`UNRELATED`、`ROUNDUP`；向量/字面召回后由模型判断，并要求完整候选裁决 | 采纳“同一报道与后续进展不能混为一条”。本次只做保守的 URL/标题/发表日分组，移除 NewsAgent 的模糊标题收敛；不声称完成语义事件聚簇。 |
| [ingest/items.ts](https://github.com/KKKKhazix/AIHOT/blob/cc66cceb1dc7a0bc147e942e49ff94c9cee418c6/packages/backend/src/ingest/items.ts) | 规范 URL 判重；非法发布时间保留空值；采集入口不自动赋予发布资格 | 采纳保留未知时间、文章身份参数、追踪参数去重；缓存读取不变成新的抓取时间。 |
| [structure.md](https://github.com/KKKKhazix/AIHOT/blob/cc66cceb1dc7a0bc147e942e49ff94c9cee418c6/industry/prompts/structure.md) | 抽取谁、动作、对象、发生时间和原文证据；区分综合稿与单次发生；发表/抓取日期不得补作事件发生日期 | 采纳三种时间边界、主体关联和事实/观点分离。当前供应商通常只给标题/摘要，故统一 `occurred_at=null`，不凭标题合成已核验事实。 |
| [selection.md](https://github.com/KKKKhazix/AIHOT/blob/cc66cceb1dc7a0bc147e942e49ff94c9cee418c6/docs/selection.md)、[grouping.md](https://github.com/KKKKhazix/AIHOT/blob/cc66cceb1dc7a0bc147e942e49ff94c9cee418c6/docs/grouping.md) | 先取原文、结构化和判重；独立两次精选评分；用标注样本校准，并独立评测归组关系 | 保留以后金融领域标注/原文核验的方向。本次不新增两轮模型评分、语义归组服务或持久热点数据库；“分数较高”不能替代原文验证。 |

AIHOT 的代码为 [MIT](https://github.com/KKKKhazix/AIHOT/blob/cc66cceb1dc7a0bc147e942e49ff94c9cee418c6/LICENSE) 许可证，版权声明为 `Copyright (c) 2026 数字生命卡兹克`。名称、Logo 及第三方素材另有边界。本次仅参考机制并独立实现，未复制源码、提示词正文、品牌或数据。

## 已确认的原问题

1. `_build_news_item` 把精确时间截为日期，网关又把日期写成午夜时间，形成假精度。
2. 搜索标题/摘要中的日期可能被当成发表日期；未知日期在部分出口显示 `Recent`。
3. 新闻来源匹配使用域名子串，类似 `reuters.com.other.example` 也能命中 Reuters。
4. NewsAgent 按标题相似性收敛，可能吞掉同公司不同事件与后续进展；重复报道会影响催化数、情绪样本与“热度”。
5. `get_event_calendar` 在宏观日程搜索失败时，仍产生 CPI/FOMC/非农三个 `date=None` 占位“事件”，随后被计入催化和热度。
6. 轻量 Chat 舆情快照仅凭催化关键词，无时间、无 URL 的标题也能成为催化。
7. 情绪源的旧样本、重复文章、其他 ticker 的整体情绪可能混入当前股票的均值。

## 实现与边界

`backend/research/news_event_quality.py` 是无网络、无模型依赖的公共合同。`tools/news.py`、NewsAgent 与 `sentiment_brief.py` 复用该入口。网关保留公开元数据 `published_at_precision` 和 `retrieval_kind`，执行/合成层透传事件质量。

每条新闻在原字段之外包含 `event_quality`：

| 字段 | 口径 |
| --- | --- |
| `version` | `news-event-v1`。 |
| `published_at / published_precision` | 来源明确发布时间；保留时区转换后的 UTC 时间或日期精度。无时区的日期时间仅承认日期精度。 |
| `observed_at` | 首次规范化时记录的观察时间；缓存重读不刷新。 |
| `occurred_at` | 本版始终为空；标题、发表日期、抓取日期不证明事件发生时间。 |
| `freshness` | `fresh / stale / unknown / future`；默认最近 7 天，市场 RSS 使用原 48 小时窗口。未来超过 5 分钟的精确时间不是最新新闻；只有日期时按 UTC 日期比较。 |
| `subject_match` | `headline / summary_only / none / market`。标题主体基于明确 ticker/公司别名边界；仅摘要提及不能成为该公司的催化。 |
| `source_tier` | `primary / established_media / opinion_or_community / unknown`。按真实 URL 主机名的域边界匹配，不按来源字符串或 URL 子串授信。公司一手域名绑定对应公司。 |
| `content_kind` | `report / opinion / rumor / discovery`。搜索结果是线索；观点和传闻不是确认发生。 |
| `evidence_role` | `reported_news / historical_news / opinion / discovery`；非 `reported_news` 的合成用途为 `raw`。 |
| `usable_as_catalyst` | 仅时间有效、主体明确、来源已分类且内容为报道时可进入“候选催化”；仍不是已核验投资结论。 |
| `verification` | `headline_only` 或 `discovery_only`，明确原文尚未核验。 |
| `event_id / grouping` | 同标题、同发表日，或同一规范 URL、同发布时间的保守分组。不同标题/跨日进展保留；这是候选报道组，不能当作已经判定的真实世界事件身份。 |
| `report_count / source_count / independence` | 唯一文章 URL 数、来源域数及固定 `unverified`。同一通讯社转载到多个网站不证明独立核实。 |

`supporting_reports` 保留分组出处，最多 20 个 URL。再次走规范化合同不会累计重复计数。移除追踪参数时保留 `id` 等文章身份参数。旧闻、未知日期、传闻、观点和来源未分类等均有可见中文标签；报道列表注明“未核原文”。界面把“热度”改成“报道覆盖”，不依据来源打分推导金融影响强弱。

实际港股验收暴露的 Nike/G7 新闻被塞入腾讯报告的问题也已收口：NewsAgent 对个股请求中 `subject_match=none` 的报道直接排除出返回新闻、正文证据和 claims，仅在 `news_quality_filter` trace 保留来源与排除原因。`summary_only` 可作为明确标注的线索；泛市场和指数请求继续保留市场新闻。

事件日历只保留供应商给出的窗口内计划日期，附 `status=scheduled`、`verification=provider_reported`，并保留 `occurred_at=null`。搜索宏观日期只进入 `discovery_candidates`；没有日程时不造三条占位事件，返回 `no_calendar_events`。未来财报日与已经发生的催化分开表达。

情绪统计只使用最近 7 天且可关联该 ticker 的去重报道。未知/过期/未来时间不参与；指定 ticker 的评分缺失时，不用其他 ticker 的整体分数补齐。NewsAgent 从保留的样本重算均值，不信任缺少时间口径的孤立总均值；样本不足明确表达无法判断整体偏多或偏空。

## 验收

使用项目 `.venv`、禁止外网的 `verify-foundation-backend.py` 跑新闻/事件相关定向 fixture 测试。未调用付费模型、未向服务器发起新闻采集。

覆盖包括：未知/旧/未来时间、带时区时间与日期精度、缓存老化、搜索日期不变成事件发生时间、伪造域名、只在摘要提到 NVDA 的 Nike 新闻、传闻/观点、原始来源优先、URL 追踪参数判重、文章 ID 参数保留、不同后续进展、原文未核验、无日历不造事件、新闻工具→网关→执行证据→合成合同透传，以及轻量/完整 Agent 共用门禁。

最终运行 **14 个聚焦测试文件，202 项通过（2.33 秒）**；`git diff --check` 通过。新文件 `backend/tests/test_news_event_quality.py` 覆盖本次合同，既有新闻解析、来源/URL、情绪、轻量简报、Agent 原生 claims、图表、网关与金融事实测试一并回归。相应旧 fixture 改为明确日期、主体、来源 URL；未知时间/错误主体等负例独立保留，未放松生产门禁。

真实线上新闻源的覆盖与时效依赖供应商。本期产出是**带证据边界的候选报道组**，尚未实施正文抓取核验、真实发生抽取、跨语言语义事件聚类或全网持续新闻采集。本次门禁证明不把已知不合格输入包装成最新事实，不能保证媒体原文真实、全网实时覆盖或因果预测准确。

后续若要引入 AIHOT 式原文核验/语义归组，应先建立金融事件对照集，分别衡量主体关联、事实摘录、错误合并、漏分组与时效召回，再决定是否增加异步采集和持久事件库。
