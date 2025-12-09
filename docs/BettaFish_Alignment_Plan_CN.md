# FinSight × BettaFish 多 Agent 升级对齐指引（2025-12）

> 目的：借鉴 BettaFish 的「论坛式多 Agent + 中间表示 + 高召回抓取」落地方法，修补 FinSight 现有缺口（单链路、缓存薄弱、可观测性不足），在 4–6 周内完成一次可验证的体系化升级。

---

## 1. BettaFish 关键做法（可直接复用）
- **论坛式多 Agent 协作**：Query / Media / Insight / Report 四条专职链路并行，ForumEngine 主持人收敛/辩论，避免单模型幻觉与视角单一。
- **节点化流水线**：每个 Agent 拆成 nodes（搜索/格式化/总结/布局），有明确的 state 流转与重试钩子，便于插拔与加速单节点。
- **报告中间表示（IR）**：先生成结构化 IR（章节 JSON + 校验），再渲染 HTML/PDF；输出可靠且可回溯。
- **高召回抓取 + 缓存**：多源搜索/爬虫（Tavily+DDG+爬虫）→ 2–5 句摘要 → 落 KV / 文件 → IR/RAG 复用，降低重复调用与成本。
- **可观测性与回归**：论坛监控、节点日志、retry helper、端到端测试（forum/report 流程），确保多 Agent 不失控。

---

## 2. FinSight 现状主要短板（基于 docs/Future_Blueprint_Execution_Plan_CN.md 与代码）
- 单 CIO Agent + 工具层，缺少**显式子 Agent 分工与冲突消解**；LangGraph 可视化/诊断薄弱。
- **缓存与搜索兜底不足**：行情/新闻限流频繁；KV 仅规划未落地，DeepSearch 触发与过期策略欠缺。
- **长文/IR 缺位**：报告直出长文，无中间表示，前端难以结构化展示或复用历史研究。
- **可观测性缺口**：工具调用来源/耗时/失败原因未统一打点，健康面板与前端提示缺失。
- 文档分散：执行蓝图与现状混杂，缺“落地步骤+验收”对应代码路径。

---

## 3. 目标架构（对齐 BettaFish，金融场景裁剪）
```
User -> Orchestrator(CIO Hub, LangGraph)
       |- Price/Tech Agent    (行情+技术指标，多源回退+短缓存)
       |- News/Media Agent    (Tavily/DDG/爬虫，高召回摘要+KV)
       |- Fundamental Agent   (财报/估值/经营要点，结构化提取)
       |- Macro/Risk Agent    (宏观日历+情绪+风险暴露)
       |- Research Agent      (长文抓取+向量检索，IR 片段)
       -> Forum/Host          (收敛/辩论/去重，产出统一 schema)
       -> Report Renderer     (IR 校验 -> Markdown/HTML/PDF)

Shared:
- KV 层（ticker+field+as_of，TTL）：行情片段/新闻摘要/估值要点
- Vector/RAG（长文、研报、DeepSearch 摘要切分）
- Diagnostics：source/duration/fail_reason/fallback_used + 健康面板
```

---

## 4. 两阶段落地路线（4–6 周）

### 阶段 A（1–2 周，BettaFish Lite 基座）
- `backend/tools.py`：统一输入/输出 schema（value、as_of、source、fallback_used、fail_reason），补短缓存（30–60s）与可配置优先级；新增搜索兜底节点（Tavily/Serper/DDG 限时）。
- `backend/langchain_agent.py`：在 LangGraph 节点打 tracing tag，补 `max_iterations/timeout`；输出 `observations/risks/recommendation` 结构化字段。
- `backend/api/main.py`：统一错误包装，暴露 `data_origin` / `fallback_used` 给前端；健康检查显示各源 fail_rate。
- `frontend`：Thinking/Diagnostics 面板显示工具调用、KV 命中/重搜标记、数据来源。
- 文档：在 `docs/` 添加本指引，旧蓝图保留但标注“执行进度”入口。

### 阶段 B（3–4 周，多 Agent + IR）
- `backend/agents/` 新建子 Agent：`price_agent.py`、`news_agent.py`、`fundamental_agent.py`、`macro_agent.py`、`research_agent.py`，每个绑定独立 prompt 与工具子集，输出统一 JSON（summary/evidence/links/confidence）。
- `backend/orchestration/orchestrator.py`：Forum/Host 节点并行调用子 Agent，做去重/冲突消解/排序，形成合并 state。
- `backend/report/ir.py`：定义 IR Schema + 校验器，ReportHandler 将合并 state 转为 IR，再渲染 Markdown/HTML（可先跳过 PDF）。
- DeepSearch 最小闭环：主链路不足时触发 news_agent/research_agent，高召回摘要后写 KV（带 TTL），下次先查 KV。
- 测试：新增端到端用例（行情失败→搜索兜底成功；news KV 命中；multi-agent 输出包含至少 2 个维度）。
- 前端：在消息旁展示“由哪些 Agent 贡献”，长文报告展示 IR 结构（章节/要点/链接），保留 PDF 导出。

---

## 5. 数据抓取与缓存策略（BettaFish 方法移植）
- **多源轮换 + 熔断**：行情/新闻按 fail_rate 与耗时动态排序，坏源冷却后再恢复；指数走独立优先级表。
- **高召回 + 瘦摘要**：搜索/爬虫返回原文链接 + 2–5 句摘要，强制带 Markdown 链接；摘要写入 KV/RAG。
- **过期策略**：KV key=`{ticker}:{field}`，字段含 `as_of/source/text/links/ttl/last_refresh_reason`；主链路命中过期时自动重搜。
- **IR/RAG**：报告前先检索 RAG 片段（news/fund/macro），再补实时工具，降低长报告幻觉。

---

## 6. 前端与运维改进
- Diagnostics 面板：展示工具顺序、耗时、失败原因、fallback_used、KV 状态；为异动行情标红提示“搜索兜底可能偏差”。
- Agent 视图：在对话气泡或侧栏标记贡献的子 Agent，提供“只看某 Agent 结论”切换。
- 仪表盘与订阅：保留现有 Alerts，新增源健康摘要、热门标的卡片（命中缓存时 2–3 秒首屏）。
- 运维：保留 `logs/alerts.log`，新增 `logs/diagnostics.log` 结构化 JSON 便于 ELK/LangSmith；每周导出 fail_rate/耗时分布。

---

## 7. 文档与验收建议
- 文档分层：`Future_Blueprint_Execution_Plan_CN.md` 继续记录阶段目标；本文件作为“对齐 BettaFish 的实施手册”；在 README 补充“一页式状态”链接。
- 阶段 A 验收：工具失败不 500；Diagnostics 可见 data_origin/fallback_used；搜索兜底可用；KV 命中率/过期重搜可观察。
- 阶段 B 验收：典型查询触发 ≥2 个子 Agent；输出包含分维度结论与链接；IR 校验通过率 >95%；端到端用例覆盖多 Agent 与兜底。

---

## 8. 对现有蓝图的快速调整建议
- 将现有 P0/P1 任务映射到“阶段 A/B”并关联文件路径；新增“诊断面板”和“IR 校验”作为硬验收项。
- 在 `backend/tools.py` 与 `backend/langchain_agent.py` 的 TODO 上添加具体日志字段（source/duration/fail_reason/fallback_used）与缓存 TTL，减少空洞描述。
- 文档中单独列出“限流/坏源”处理规范与测试用例，避免反复踩坑。
