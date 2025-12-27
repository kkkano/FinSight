# FinSight × BettaFish 多 Agent 升级决策稿（2025-12-08）

> 结论：借鉴 BettaFish 的“专业分工 + 论坛式协作 + 反思 + IR”，分三步落地：先把工具缓存与结构化输出打牢，再接入 3-4 个子 Agent 与轻量论坛聚合，最后补反思循环与 IR/RAG，避免一次性重构失控。

---

## A. BettaFish 要点（用于对齐）
- 专业分工：Query/Media/Insight/Report，ForumHost 收敛与辩论。
- 论坛式协作：Agent 通过 forum.log 异步交流，主持人提供时间线/观点整合/深度分析/指引。
- 反思循环：每个 Agent 2-3 轮“识别空白 → 定向补搜 → 更新总结”。
- 高召回 + 缓存：多源搜索/爬虫 → 2-5 句摘要 + Markdown 链接 → KV/Redis 缓存复用。
- IR 输出：各 Agent 报告 + forum 内容 → 模板化渲染 HTML/PDF，IR 可校验/回溯。

## B. FinSight 现状（关键差距）
- 单 CIO Agent + Router；无显式子 Agent 分工与论坛/辩论。
- 工具层限流多、缓存/兜底薄弱；缺统一日志字段（source/duration/fail_reason/fallback_used）。
- 长文报告无 IR，前端难结构化展示；可观测性不足。

---

## C. 最终路线（三阶段）

### 阶段 0（1 周）：稳态基座 + 结构化输出
- `backend/tools.py`：统一返回结构 `value/as_of/source/fallback_used/fail_reason`，补 30-60s 短缓存与可配置优先级；搜索兜底（Tavily/Serper/DDG，限时）。
- `backend/langchain_agent.py`：输出 `observations/risks/recommendation` 结构；设置 `max_iterations/timeout`，节点打 tracing tag。
- `backend/api/main.py`：统一错误包装，透出 `data_origin/fallback_used`，健康检查展示 fail_rate。
- 前端：Diagnostics 面板展示工具调用顺序、耗时、失败原因、KV 命中/重搜标记。
- 文档：保留旧蓝图，新增本决策稿链接（状态页）。

### 阶段 1（2-3 周）：子 Agent + 轻量论坛聚合
- 目录：`backend/agents/{base,technical,fundamental,macro,sentiment,orchestrator}.py`
- `AgentOutput` 统一 schema（summary/evidence/links/confidence/as_of/risks/data_sources）。
- Orchestrator（LangGraph 主图）：并行调用 3-4 子 Agent，做去重/冲突消解；轻量 `AgentForum`（内存队列）记录各 Agent 发现，供互相参考。
- DeepSearch 触发：工具不足/过期时调用 news/sentiment Agent，高召回摘要 + 写 KV（ticker+field+as_of，TTL）。
- E2E 用例：行情失败→搜索兜底成功；news KV 命中；典型问答触发 ≥2 个子 Agent。
- 前端：对话气泡旁标记“由哪些 Agent 贡献”，提示兜底来源。

### 阶段 2（4-6 周）：反思循环 + IR/RAG
- 反思：在子 Agent 内增加 1-2 轮“识别空白 → 定向补搜 → 更新总结”，高成本路径受限时长。
- IR：`backend/report/ir.py` 定义 IR Schema + 校验器；Orchestrator 合并 AgentOutput → IR → Markdown/HTML（PDF 可后置）。
- RAG：长文/研报摘要切分入向量库，报告前先检索片段，再补实时工具。
- 论坛强化：可选落地 forum.log 文件或诊断面板，保留主持人式引导（可用更小模型）。

---

## D. 关键实现清单（文件级指引）
- 缓存与兜底：`backend/services/cache.py`（短 TTL 内存缓存），`backend/tools.py`（source/duration/fail_reason/fallback_used），指数单独优先级表。
- 子 Agent：`backend/agents/base_agent.py`（AgentOutput dataclass +校验）；`technical_agent.py`（get_stock_price/kline/指标）；`fundamental_agent.py`（财报/估值/经营要点）；`macro_agent.py`（日历/利率/情绪）；`sentiment_agent.py`（新闻/Tavily/社交）；`orchestrator.py`（并行+冲突消解+forum）。
- 反思：在各 Agent 内增加 `_reflection_loop` 钩子（可配置 max_rounds），仅在报告/深度模式启用。
- IR：`backend/report/ir.py`（schema+校验），`handlers/report_handler.py` 将合并 state 渲染 Markdown/HTML。
- 可观测性：`logs/diagnostics.log` 结构化 JSON；前端 Diagnostics 面板读取 `data_origin/fallback_used/agent_contributors`。

---

## E. 验收标准（按阶段）
- 阶段 0：工具失败不 500；Diagnostics 可见 data_origin/fallback；搜索兜底可用；KV 命中/过期重搜可观察。
- 阶段 1：典型查询触发 ≥2 子 Agent；输出按 AgentOutput 分维度呈现，含链接与 as_of；DeepSearch 缺口场景能补数据。
- 阶段 2：反思循环能减少缺项；IR 校验通过率 >95%；报告可溯源引用（片段+来源）。

---

## F. 立即行动（今日起）
1) 追加短缓存与日志字段：`backend/tools.py`、`backend/langchain_agent.py`；API 透出 `data_origin/fallback_used`。  
2) 创建 `backend/agents/` 目录与 `AgentOutput` 基类，接入 Technical/Fundamental 两个最小子 Agent；Orchestrator 并行融合。  
3) 前端 Diagnostics 面板显示“数据来源/兜底/Agent 贡献”；文档在 `docs/Future_Blueprint_Execution_Plan_CN.md` 链接本决策稿。  
4) 新增 E2E 用例覆盖行情兜底与多 Agent 最小路径。  
