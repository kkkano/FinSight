# 2026-03-07 本地 PostgreSQL / DeepSearch / RAG Inspector 联调验证记录

更新时间：2026-03-07 02:56（UTC+8）  
状态：已完成本地实测与补跑复核，可作为后续修复与开发依据  
适用范围：本地 `backend`、本地 `frontend`、`PostgreSQL 17`、DeepSearch、RAG 可观测性、RAG Inspector

---

## 1. 本次验证结论

### 1.1 结论总览

- [x] 本地 `PostgreSQL` 已接上，RAG 主后端实际运行在 `postgres`
- [x] DeepSearch 抓到的原文，已经可以落库并被 Inspector 看到
- [x] 可以看到“切了什么、切成几段、每段全文是什么”
- [x] 可以看到“这篇文档是由哪条 DeepSearch query 抓回来的”
- [x] 可以看到命中来源、命中 chunk、原始文档全文
- [x] 可以通过 SQL 直接审计 `run -> event -> source_doc -> chunk -> hit`
- [x] 本地前端可通过“开发模式进入 RAG Inspector”直接查看观测数据
- [x] 已再次补跑一条新的 DeepSearch-only 深度任务，结果正常落库
- [ ] `chunk_count` 统计仍有一处真实不一致，尚未修复
- [ ] DeepSearch 的 gap query 仍存在漂移，尚未修复
- [ ] Windows 下 `LangGraph checkpointer` 仍回退到 memory，尚未修复

### 1.2 一句话判断

这条链路现在已经不是“黑盒子”了。  
它已经能把 DeepSearch 搜了什么、存了什么、怎么切、命中了什么、原文到底长什么样，完整暴露出来。

---

## 2. 本地启动与访问方式

### 2.1 当前实测访问地址

- 后端：`http://127.0.0.1:8001`
- 前端：`http://127.0.0.1:5174`
- Inspector 页面：`http://127.0.0.1:5174/rag-inspector`

### 2.2 本次联调依赖的关键环境变量

只记录键名，不记录真实敏感值：

- `RAG_V2_BACKEND`
- `RAG_V2_POSTGRES_DSN`
- `LANGGRAPH_CHECKPOINT_BACKEND`
- `LANGGRAPH_CHECKPOINT_POSTGRES_DSN`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`
- `VITE_API_BASE_URL`

### 2.3 RAG Inspector 本地进入方式

#### 方式 A：直接验证匿名链路

1. 打开 `http://127.0.0.1:5174/`
2. 点击 `匿名体验（数据仅存本地）`
3. 进入 `/chat`
4. 再点击侧边栏 `RAG 观测`
5. 页面会跳到 `/welcome?from=/rag-inspector`
6. 点击 `开发模式进入 RAG Inspector`
7. 成功进入 Inspector，并能看到 run / 原文 / chunk / collection

#### 方式 B：直接访问 Inspector

1. 打开 `http://127.0.0.1:5174/rag-inspector`
2. 若未登录，会被导到欢迎页
3. 点击 `开发模式进入 RAG Inspector`
4. 成功进入 Inspector

### 2.4 当前权限边界

- `GET /health`：可匿名访问
- `GET /diagnostics/rag/status`：匿名访问会返回 `401 Authentication required`
- 前端 `RAG Inspector`：生产逻辑要求登录用户访问
- 本地调试：前端已提供“开发模式进入 RAG Inspector”入口，便于本地验证

这意味着：

- 后端观测接口的鉴权收口是生效的
- 本地又保留了一个可测试入口，不会卡死在登录链路上

---

## 3. 本次构造的深度查询

本次核心验证 query：

```text
请基于 Apple(AAPL) 最近一个季度财报、业绩会电话会议纪要、公开新闻与 SEC 披露，深度分析 iPhone 需求、服务业务趋势、管理层指引变化和主要风险，并给出 5 条结论。
```

对应执行体示例：

```json
{
  "query": "请基于 Apple(AAPL) 最近一个季度财报、业绩会电话会议纪要、公开新闻与 SEC 披露，深度分析 iPhone 需求、服务业务趋势、管理层指引变化和主要风险，并给出 5 条结论。",
  "output_mode": "investment_report",
  "analysis_depth": "deep_research",
  "confirmation_mode": "skip",
  "agents": ["deep_search_agent"],
  "budget": 3,
  "source": "rag_inspector_validation_deepsearch_verify",
  "session_id": "local-rag-observe-deepsearch-verify",
  "run_id": "local-rag-observe-deepsearch-verify-20260307-0246",
  "trace_raw": true
}
```

执行入口：

```bash
curl.exe -N -H "Content-Type: application/json" \
  --data-binary "@body.json" \
  http://127.0.0.1:8001/api/execute
```

---

## 4. 关键 run 与 collection

### 4.1 最新补跑：DeepSearch 原文落库验证 run

- `run_id`: `run_e33c31da70a940a9baba31aeeb93d238`
- `collection`: `session:deepsearch:aapl:10b81746151aba77`
- `status`: `completed`
- `source_doc_count`: `6`
- `chunk_count`（run 汇总）: `6`
- `retrieval_hit_count`: `6`
- `latency_ms`: `4363.71`

### 4.2 最新补跑：完整链路观测 run

- `run_id`: `run_ea169b10d3d142e6b8effccea3d2e986`
- `collection`: `session:public:anonymous:local-rag-observe-deepsearch-verify`
- `status`: `completed`
- `source_doc_count`: `24`
- `chunk_count`: `24`
- `retrieval_hit_count`: `18`
- `latency_ms`: `32.54`

### 4.3 02:31 基线样本（对照）

- `run_id`: `run_6a03e87d9be24fa387852858d03ce9e2`
- `collection`: `session:deepsearch:aapl:eca4746cc3961589`
- `source_doc_count`: `5`
- `chunk_count`（run 汇总）: `5`
- `retrieval_hit_count`: `5`

- `run_id`: `run_900968ac72a54dd49567d433821a62e9`
- `collection`: `session:public:anonymous:local-rag-observe-deepsearch-only`
- `source_doc_count`: `19`
- `chunk_count`: `19`
- `retrieval_hit_count`: `18`

- `run_id`: `run_7069a47f37804b0f9440d57b8f1296b8`
- `collection`: `session:public:anonymous:local-rag-observe`
- `source_doc_count`: `43`
- `chunk_count`: `43`
- `retrieval_hit_count`: `18`

---

## 5. 这次到底观测到了什么

### 5.1 现在能看到“搜了什么”

最新补跑 `run_e33c31da70a940a9baba31aeeb93d238`（以及 02:31 的 `run_6a03e87d9be24fa387852858d03ce9e2`）在 `rag_source_docs.metadata_json` 中已实测包含：

- `origin=deep_search_agent`
- `ticker=AAPL`
- `search_query`
- `search_queries`
- `gap_query`
- `gap_queries`
- `deepsearch_phase`
- `deepsearch_phases`
- `search_rank`

最新补跑样本：

| 标题 | phase | search_query | gap_query | search_rank |
|---|---|---|---|---|
| `https://www.sec.gov/.../aapl-20250927.htm` | `initial` | `site:sec.gov AAPL 10-K annual report` | 空 | `1` |
| `https://www.fool.com/earnings/call-transcripts/...` | `targeted` | `AAPL Apple 2025财年 预测 财务数据, financial forecast, debt structure, liabilities, assets, context` | `Apple 2025财年 预测 财务数据, financial forecast, debt structure, liabilities, assets, context` | `3` |
| `F1 season kicks into high gear with new Apple TV streaming deal` | `targeted` | `AAPL Apple 其他负债 构成 明细` | `Apple 其他负债 构成 明细` | `11` |

结论：

- 现在不只是“知道抓到了哪篇文档”
- 还知道“它是被哪一条 query 抓回来的”
- 还能区分是 `initial` 阶段还是 `targeted` 阶段
- 还可以直接发现 DeepSearch query 是否已经漂移

### 5.2 现在能看到“原文是什么”

`rag_source_docs.content_raw` 已实测保存原始抓取文本。  
这个“原文”不是摘要，而是系统实际拿到的原始文本。

#### 财报 / SEC 原文样本

- `Apple Inc. 10-K (2024-11-01)`
- `Apple Inc. 10-K (2025-10-31)`
- `https://www.sec.gov/Archives/edgar/data/.../aapl-20250927.htm`

原文前缀样本：

```text
Apple Inc. 10-K (2024-11-01)

SEC EDGAR 10-K filing. Filed: 2024-11-01. 10-K
```

#### 电话会议纪要 / transcript 原文样本（成功抓取）

- `https://www.fool.com/earnings/call-transcripts/2020/10/30/apple-aapl-q4-...`

原文前缀样本：

```text
Apple (AAPL) Q4 2020 Earnings Call Transcript | The Motley Fool
Accessibility Menu Search for a company Accessibility ...
```

#### 电话会议纪要 / transcript 原文样本（失败抓取也可见）

- `Apple Inc. ( AAPL ) Earnings Call Transcripts | Seeking Alpha`

原文前缀样本：

```text
Apple Inc. ( AAPL ) Earnings Call Transcripts | Seeking Alpha
Title: Access to this page has been denied
URL Source: https://seekingalpha.com/symbol/AAPL/earnings/transcripts
Warning: Target URL returned error 403: Forbidden
```

注意：这条非常重要。  
它说明系统现在不仅能让你看到“抓到了 transcript 来源”，还会把“实际抓到的是 403 拒绝页”原样暴露出来。  
这正是可观测性的价值：不是只看成功样本，而是看系统真实拿到了什么。

#### 新闻原文样本

- `Formula 1 and Apple's big gamble kicks off this weekend`
- `F1 season kicks into high gear with new Apple TV streaming deal`

原文前缀样本：

```text
Formula 1 and Apple's big gamble kicks off this weekend
A big change is coming in the all-important US market for F1: Gone is ESPN...
```

```text
F1 season kicks into high gear with new Apple TV streaming deal Oops, something went wrong ...
```

### 5.3 现在能看到“怎么切、切成什么样”

`rag_chunks` 已实测保存：

- `chunk_index`
- `total_chunks`
- `chunk_text`
- `chunk_length`
- `doc_type`
- `chunk_strategy`
- `chunk_size`
- `chunk_overlap`
- `char_start`
- `char_end`
- `metadata_json`

当前 `backend/rag/chunker.py` 的规则实测如下：

- `filing`：`1000 / 200`
- `transcript`：`800 / 100`
- `news`：`<= 2000` 时不切
- `research`：`1200 / 200`
- `web_page`：`1200 / 200`
- `table`：不切

#### 最新 DeepSearch collection 的真实切片结果

`session:deepsearch:aapl:10b81746151aba77`：

- 实际 `doc_count = 6`
- 实际 `chunk_count = 63`

其中单个 SEC 文档样本：

- `doc_type = web_page`
- `total_chunks = 12`
- `chunk_size = 1200`
- `chunk_overlap = 200`

样本 chunk 前缀：

```text
aapl-20250927 false 2025 FY 0000320193 P1Y P1Y P1Y P1Y ...
```

结论：

- 现在可以直接看到某篇文档被切成多少段
- 可以看到每段具体正文
- 可以看到切片策略和参数

### 5.4 现在能看到“命中了什么”

`rag_retrieval_hits` 已实测保存：

- `dense_score`
- `sparse_score`
- `rrf_score`
- `content_preview`
- `source_doc_id`
- `chunk_id`

通过关联 `rag_source_docs`，最新完整链路 `run_ea169b10d3d142e6b8effccea3d2e986` 已能看到命中来源是：

- `Apple Inc. 10-K (2024-11-01)`
- `Apple Inc. 10-K (2025-10-31)`
- `Apple Inc. 10-Q (2025-05-02)`
- `Apple Inc. ( AAPL ) Earnings Call Transcripts | Seeking Alpha`
- `The Week in Numbers: oil prices up, Apple prices down`
- `get_sec_company_facts_quarterly output`
- `get_stock_price output`

这意味着：

- 不只是知道“命中了 18 条”
- 而是知道“具体命中哪篇原文、哪段 chunk、分数是多少”

---

## 6. 当前 PostgreSQL 里各张表到底装了什么

### 6.1 主向量表

#### `rag_documents_v2`

这是主向量库表。  
真正的向量、collection、embedding 存这里。

### 6.2 观测表

#### `rag_query_runs`

一条查询 / 检索运行的汇总记录：

- 查了什么
- 查哪个 collection
- 实际后端是什么
- 命中多少
- 文档多少
- chunk 多少
- 花了多久
- 最终状态是什么

#### `rag_query_events`

一条 run 的事件时间线：

- `search_started`
- `pending_ingest_claimed`
- `pending_ingest_materialized`
- `search_completed`

这张表最关键的价值是：能把 ingest 和 search 拆开看。

#### `rag_source_docs`

原始文档表：

- 原文全文 `content_raw`
- 文档标题 `title`
- 来源 URL `url`
- 元信息 `metadata_json`

这是“我到底存了什么”的核心答案。

#### `rag_chunks`

切片明细表：

- 每个 chunk 的正文
- chunk 序号
- 总段数
- 策略
- size / overlap
- 来源原文

这是“怎么切的”的核心答案。

#### `rag_retrieval_hits`

召回命中表：

- 命中了哪个 chunk
- 属于哪个 source doc
- dense / sparse / RRF 分数
- 命中内容预览

这是“效果如何”的核心答案。

#### `rag_rerank_hits`

重排命中表：

- 输入排名
- 输出排名
- rerank score
- 是否进入最终答案

当前这轮文档重点不在 rerank，但表已经预留。

---

## 7. 关键 SQL：你现在可以怎么查

### 7.1 查某条 run 概览

```sql
select id,status,collection,source_doc_count,chunk_count,retrieval_hit_count,started_at,finished_at,latency_ms
from rag_query_runs
where id in (
  'run_e33c31da70a940a9baba31aeeb93d238',
  'run_ea169b10d3d142e6b8effccea3d2e986'
)
order by started_at;
```

### 7.2 查 DeepSearch ingest 事件

```sql
select seq_no,event_type,stage,payload_json
from rag_query_events
where run_id='run_e33c31da70a940a9baba31aeeb93d238'
order by seq_no;
```

### 7.3 查 DeepSearch 原始文档 + query 元数据

```sql
select
  title,
  url,
  metadata_json->>'origin' as origin,
  metadata_json->>'search_query' as search_query,
  metadata_json->>'gap_query' as gap_query,
  metadata_json->>'deepsearch_phase' as deepsearch_phase,
  metadata_json->>'search_rank' as search_rank,
  left(content_raw, 500) as raw_preview
from rag_source_docs
where run_id='run_e33c31da70a940a9baba31aeeb93d238'
order by created_at;
```

### 7.4 查 chunk 明细

```sql
select
  chunk_index,
  total_chunks,
  doc_type,
  chunk_strategy,
  chunk_size,
  chunk_overlap,
  left(chunk_text, 600) as chunk_preview
from rag_chunks
where run_id='run_e33c31da70a940a9baba31aeeb93d238'
order by source_doc_id, chunk_index;
```

### 7.5 查召回命中 + 关联原文标题

```sql
select
  sd.title,
  sd.url,
  rh.rrf_score,
  rh.dense_score,
  rh.sparse_score,
  left(rh.content_preview, 500) as preview
from rag_retrieval_hits rh
left join rag_source_docs sd on sd.id = rh.source_doc_id
where rh.run_id='run_ea169b10d3d142e6b8effccea3d2e986'
order by rh.rrf_score desc nulls last;
```

### 7.6 查 collection 实际 chunk 总数

```sql
select collection, count(distinct source_doc_id) as doc_count, count(*) as chunk_count
from rag_chunks
where collection in (
  'session:deepsearch:aapl:10b81746151aba77',
  'session:public:anonymous:local-rag-observe-deepsearch-verify'
)
group by collection
order by collection;
```

---

## 8. RAG Inspector 页面上现在能看到什么

### 8.1 实测可见模块

- 最近查询回放
- 查询总览
- 事件时间线（含 payload）
- 命中与重排
- 原始文档（含原文）
- 切片明细（含完整 chunk）
- Collection 浏览

### 8.2 本次截图

- 截图文件：`rag-inspector-validated-20260307.png`

### 8.3 页面上的真实可见证据

截图拍摄于 02:45，当时页面已经显示：

- `session:public:anonymous:local-rag-observe-deepsearch-only`
- `run：2 · doc：19 · chunk：19`
- `session:deepsearch:aapl:eca4746cc3961589`
- `run：1 · doc：5 · chunk：63`

02:50 补跑之后，库里又新增了：

- `session:public:anonymous:local-rag-observe-deepsearch-verify`
- `session:deepsearch:aapl:10b81746151aba77`

也就是说，前端现在已经能直接把：

- query 回放
- collection 聚合
- 原文全文
- chunk 全文
- chunk metadata

完整展开给你看。

---

## 9. 已确认的真实缺陷

### 9.1 `chunk_count` 汇总不一致

现象：

- 最新补跑 `run_e33...` 在 `rag_query_runs.chunk_count = 6`
- 但 `rag_query_events.pending_ingest_materialized.payload_json.chunk_count = 63`
- `rag_chunks` 按 collection 聚合后也是 `63`
- 前端 `Collection 浏览` 也会显示 `chunk：63`

结论：

- `run` 级汇总字段目前没有正确反映 materialized chunk 总数
- 高概率是 `complete_search_run()` 只汇总了某个中间结果，而不是最终真实 chunk 数

优先级：`P1`

### 9.2 DeepSearch gap query 漂移

现象：

- 自反思阶段会生成与主问题不够贴合的 query
- 最新补跑中已出现 `AAPL Apple 其他负债 构成 明细` 这类明显偏题的 targeted query
- 也出现了 `AAPL Apple 2025财年 预测 财务数据, financial forecast, debt structure, liabilities, assets, context` 这类过宽 query

影响：

- 会引入与主题不强相关的网页
- 影响召回质量与解释性
- 会让 Inspector 虽然“看得见”，但看见的是一堆偏题来源

优先级：`P1`

### 9.3 SEC 文档被当成 `web_page` 切，不是 `filing`

现象：

- 最新补跑 `run_e33...` 的 SEC 10-K chunk 样本里，`doc_type = web_page`
- 因此它走的是 `1200 / 200`，不是 `filing` 的 `1000 / 200`

影响：

- 语义上不够准确
- 未来若对 `filing` 做专门清洗和 chunk 优化，这条链路会吃不到

优先级：`P2`

### 9.4 Inspector 顶部“最近 24h 查询”卡片显示为 `0`

现象：

- 页面左侧 `最近查询回放` 明明有多条 run
- 但顶部卡片 `最近 24h 查询` 仍显示 `0`

影响：

- 首页摘要卡与真实列表不一致
- 会误导使用者判断系统是否真的在工作

优先级：`P2`

### 9.5 Windows 下 LangGraph Checkpointer 仍回退到 memory

`/health` 实测返回：

```text
fallback_reason: Psycopg cannot use the 'ProactorEventLoop' to run in async mode
```

影响：

- 当前 RAG observability 已落 PostgreSQL
- 但 LangGraph checkpoint 还没有稳定落 PostgreSQL
- Windows 本地重启后，图状态持久化能力仍不足

优先级：`P1`

---

## 10. 我建议下一步怎么做

### 10.1 立刻修的

- [ ] 修 `rag_query_runs.chunk_count` 与 materialized chunk 总数不一致
- [ ] 给 DeepSearch 的 gap 生成逻辑加更强约束，减少 query 漂移
- [ ] 给 SEC / transcript 来源补 `doc_type` 识别，别再一律落成 `web_page`
- [ ] 修 Inspector 顶部摘要卡的 24h 统计

### 10.2 第二阶段做的

- [ ] 给 `rag_source_docs` 增加“抓取结果质量标签”，例如 `ok / blocked / paywalled / parse_failed`
- [ ] 给 Inspector 加“按 source_type / doc_type / phase / blocked 状态”过滤
- [ ] 给命中列表增加“跳转到 source_doc / chunk / 原文”的联动定位
- [ ] 给 collection 页面增加“原文长度 / 平均 chunk 数 / 平均 chunk 长度”统计

### 10.3 第三阶段做的

- [ ] 做 `run replay`，允许一键回放某条历史查询
- [ ] 做 `query diff`，比较两次 DeepSearch query 和命中差异
- [ ] 做 `chunk diff`，比较不同 chunk 策略下的切片结果和命中结果
- [ ] 修复 Windows 本地 checkpointer postgres 化

---

## 11. 附：本地鉴权验证脚本

现有脚本：

- `scripts/verify_rag_observability_auth.ps1`

建议运行方式：

```powershell
./scripts/verify_rag_observability_auth.ps1 \
  -BaseUrl http://127.0.0.1:8001 \
  -AccessToken <用户 Bearer Token> \
  -RunId run_e33c31da70a940a9baba31aeeb93d238
```

脚本验证边界：

- 匿名读：应为 `401`
- Bearer 读：应为 `200`
- Bearer 软删除：应为 `403`
- 内部 API Key 软删除：应为 `200/404`

---

## 12. 最终判断

本地这套 DeepSearch / RAG / PostgreSQL / Inspector 链路，已经具备“能查库、能看原文、能看切片、能看命中、能看 query 来源”的完整观测能力。

还不能说“完全没有问题”，因为至少还有 5 个真实缺陷：

1. `chunk_count` 汇总不一致
2. gap query 漂移
3. SEC 文档类型识别不准
4. Inspector 顶部摘要卡不准
5. Windows checkpointer 仍回退 memory

但就“我到底搜了什么、存了什么、切了什么、命中了什么、原文是什么”这个核心目标而言，当前这版已经打通了。  
它已经足够支撑下一阶段把问题从“看不见”推进到“看得见并修得掉”。
