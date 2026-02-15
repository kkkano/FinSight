# FinSight 开发优先级路线图
> 📅 **制定日期**: 2026-01-09
> 📅 **更新日期**: 2026-01-23
> 🎯 **目标**: 从当前状态到项目完工的最现实、最犀利的优先级排序

---

## 📊 当前状态一览

| 阶段 | 进度 | 核心问题 |
|------|------|----------|
| Phase 0 (基座) | ✅ 100% | 无 |
| Phase 1 (Agent 团) | ✅ 100% | 核心 Agents 已齐 |
| Phase 2 (深度研报) | ✅ 100% | NEWS 子意图、ReportIR 优化完成 |
| Phase 3 (主动服务) | 🟡 10% | 订阅/告警基础已上线 |

---

## 📋 严肃版 TodoList（强验收标准）

> 每项必须同时满足：**代码提交 / 测试通过 / 指标输出 / 文档同步 / 可复现Mock**（不依赖外网）

### P1 - 质量闭环（近期必须）
- **P1-34 回归评估基线**：基准集10-30条 + 一键脚本 + 覆盖率/引用/耗时统计 + JSON/MD对比报告 | 验收=固定数据源Mock、CI<5分钟、每次改动前后有对比
- **P1-31 ReAct 搜索收敛**：信息增益评分 + 去重 + 停止条件(连续N次增益<阈值) | 验收=轮次降≥20%、引用不降、回归对比不退化(引用数/覆盖率/平均轮次)，覆盖 DeepSearch + News + Macro
- **P1-Trace 可观测性统一（已完成 2026-01-23）**：TraceEvent schema v1(event_type/duration/metadata) + supervisor_stream v1 normalize | 验收=前端统一展开trace详情、schema版本化(v1/v2兼容)

### P2 - 产品体验（保证可用性）
- **P2-研报前端分析视图（已完成 2026-01-22）**：章节导航 + 引用证据可展开 + 置信度/新鲜度可视 | 验收=引用点击跳转+原文展开(可解释性闭环)
- **P2-架构升级（已完成 2026-01-24）**：移除 ReportHandler，全面迁移至 Supervisor Agent + Forum Prompt-based 报告生成模式 | 验收=代码库移除旧 Handler，报告功能正常
- **P2-仪表盘/自选股监控（已完成 2026-01-22）**：实时涨跌 + 新闻流 + 提醒 + 本地存储 | 验收=刷新频率明确+缓存策略+数据源fallback
- **P2-RAG 集成 DeepSearch**：PDF研报入库 + 向量检索 + 引用追溯 | 验收=≥1份研报可检索+检索质量评估(Top-k命中率/引用正确率)
- **P2-用户长期记忆**：向量化偏好存储与召回 | 验收=连续对话正确复用偏好+测试用例

### P3 - 功能扩展（风险较高）
- **P3-RiskAgent**：VaR/仓位诊断 + 免责声明 | 验收=VaR有来源+合规免责声明固定模板(必须写入输出)+不输出确定性建议
- **P3-指数成分权重可视化**：treemap/饼图 + 来源可解释 | 验收=权重正确+来源可追溯+文档同步


## 🎯 优先级排序原则

1. **用户可感知 > 技术债务** - 先解决用户能直接看到的问题
2. **修复 > 新功能** - 先把现有功能做好
3. **核心路径 > 边缘功能** - 先搞定主流程
4. **低耦合任务先做** - 避免返工

---

## 📋 完整优先级列表（共 34 项）

### 🔴 P0 - 质量与合规门槛（新增 2026-01-20）

| # | 任务 | 拆分 | 验收标准 |
|---|------|------|----------|
| **25** | **计划/执行规范化 (PlanIR + Executor)（已完成 2026-01-20）** | 计划模板 + 依赖/超时状态机 + trace 记录 | 计划可验证；超时回退生效；trace 含 step 耗时 |
| **26** | **证据链硬约束 (EvidencePolicy)（已完成 2026-01-20）** | 关键结论≥2来源 + 覆盖率统计 | 覆盖率≥80% 否则降级/报错；日志输出覆盖率 |
| **27** | **数据一致性上下文 (DataContext)（已完成 2026-01-22）** | 统一 as_of/currency/adjustment | 所有数值含 as_of/currency；不一致自动标风险 |
| **28** | **预算/超时控制 (BudgetManager)（已完成 2026-01-22）** | 最大工具/轮次/耗时预算 | 超预算稳定降级；请求在预算内完成 |
| **29** | **安全与合规门禁（已完成 2026-01-22）** | API Key + 限流 + 免责声明模板 | 未鉴权拒绝；限流生效；报告含免责声明 |

### 🟠 P1 - 质量增强（新增 2026-01-20）

| # | 任务 | 拆分 | 验收标准 |
|---|------|------|----------|
| **30** | **Reflection 可检验审校（基础版已完成 2026-01-22）** | schema/数值/引用一致性审校 | 审校输出问题清单；不合格自动返工 |
| **31** | **ReAct 搜索收敛（已完成 2026-01-23）** | 信息增益阈值 + 去重 + 停止规则（DeepSearch + News + Macro） | 轮次 ≤ 上限；重复来源显著减少 |
| **32** | **结论冲突融合（基础版已完成 2026-01-22）** | 来源权重 + 冲突标注 | 冲突必标注；低可信不进主结论 |
| **33** | **可观测性与自动降级（部分完成 2026-01-22）** | 源成功率/延迟/错误统计 | 输出源健康概览；故障自动降级 |
| **34** | **回归评估基线（已完成 2026-01-22）** | 基准集 + 自动回归 | 每次迭代通过阈值；产出对比报告 |

### 🔴 P0 - 已完成（2026-01-09）

| # | 任务 | 工时 | 理由 | 阻塞项 |
|---|------|------|------|--------|
| **1** | **真正的流式输出（已完成 2026-01-09）** | 4-6h | 用户直接抱怨"一次性吐出来"，体验最差的一环 | 无 |
| **2** | **修复 Supervisor asyncio 问题（已完成 2026-01-09）** | 3-4h | 阻塞多 Agent 协作，当前被迫禁用 | 依赖 #1 |

### 🟠 P1 - 高优先级（1-2 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **3** | **TechnicalAgent 实现（已完成 2026-01-10）** | 4-5h | 技术分析是金融产品刚需（MA/RSI/MACD） | #2 |
| **4** | **FundamentalAgent 实现（已完成 2026-01-10）** | 4-5h | 估值分析是投资决策核心（PE/PB/DCF） | #2 |
| **5** | **前端 Report 卡片优化（已完成 2026-01-11）** | - | 对齐 design_concept_v2.html，视觉升级 | #1 |
| **6** | **Agent 协作进度指示器（已完成 2026-01-12）** | 2h | 用户知道后台在干嘛，减少等待焦虑 | #2 |

### 🟡 P2 - 中优先级（2-4 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **7** | **ReportIR Schema 完善（已完成 2026-01-10）** | 3h | 标准化报告结构，前后端解耦 | #3, #4 |
| **8** | **IR Validator 实现（已完成 2026-01-10）** | 2h | 防止畸形数据到前端 | #7 |
| **9** | **NewsAgent 反思循环增强** | 3h | 自动识别信息空白并补充搜索 | #2 |
| **10** | **DeepSearchAgent 真实检索 + PDF + Self-RAG（已完成 2026-01-11）** | - | 真实检索与反思检索落地 | #9 |
| **11** | **MacroAgent 升级（已完成 2026-01-12）** | 3h | 集成 FRED API 获取宏观经济数据 | #2 |
| **12** | **前端章节折叠/滚动高亮交互（已完成 2026-01-11）** | - | 报告太长需要折叠与定位 | #7 |
| **13** | **证据链接可点击 + 图表渲染 + Chart 规范（已完成 2026-01-11）** | - | 引用联动与图表可视化 | #7 |

### 🟢 P3 - 低优先级（4-6 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **14** | **RAG 基础架构（已完成 2026-01-12）** | 6-8h | ChromaDB + Sentence Transformers 向量检索 | #10 |
| **15** | **PDF 研报解析入库** | 4h | DeepSearchAgent 读取 PDF 并向量化 | #14 |
| **16** | **用户长期记忆** | 4h | 向量化存储用户偏好 | #14 |
| **17** | **PDF 报告导出** | 3h | 生成专业 PDF 文件 | #7 |
| **18** | **RiskAgent 实现** | 5h | VaR 计算、仓位诊断 | #3, #4 |

### 🔵 P4 - 锦上添花（6-8 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **19** | **WebSocket 实时推送** | 5h | 替代 SSE，更可靠的双向通信 | #1 |
| **20** | **AlertSystem 后台轮询** | 4h | 无交互情况下主动监控 | #18 |
| **21** | **异动检测** | 3h | 价格/新闻突变预警 | #20 |
| **22** | **多语言支持** | 4h | 英文/中文报告切换 | #7 |
| **23** | **移动端适配** | 4h | 响应式 UI | #5 |
| **24** | **端到端测试全覆盖** | 5h | 保证系统稳定性 | 全部 |

---

## 📈 里程碑规划

```
Week 0 (Now) ────────────────────────────────────────────────
  ├─ #25 计划/执行规范化（已完成 2026-01-20）
  ├─ #26 证据链硬约束（已完成 2026-01-20）
  ├─ #27 数据一致性上下文（已完成 2026-01-22）
  ├─ #28 预算/超时控制（已完成 2026-01-22）
  └─ #29 安全与合规门禁（已完成 2026-01-22）

Week 1-2 (Now+) ─────────────────────────────────────────────
  ├─ #30 Reflection 可检验审校（基础版完成 2026-01-22）
  ├─ #31 ReAct 搜索收敛
  ├─ #32 结论冲突融合（基础版完成 2026-01-22）
  ├─ #33 可观测性与自动降级（部分完成 2026-01-22）
  └─ #34 回归评估基线

Week 1 ──────────────────────────────────────────────────────
  ├─ #1 真正的流式输出（已完成 2026-01-09）
  ├─ #2 修复 Supervisor 异步（已完成 2026-01-09）
  └─ #5 前端卡片优化

Week 2 ──────────────────────────────────────────────────────
  ├─ #3 TechnicalAgent（已完成 2026-01-10）
  ├─ #4 FundamentalAgent（已完成 2026-01-10）
  └─ #6 Agent 进度指示器

Week 3-4 ────────────────────────────────────────────────────
  ├─ #7 ReportIR Schema（已完成 2026-01-10）
  ├─ #8 IR Validator（已完成 2026-01-10）
  ├─ #9 NewsAgent 反思循环
  └─ #10 DeepSearchAgent 升级

Week 5-6 ────────────────────────────────────────────────────
  ├─ #11 MacroAgent 升级
  ├─ #12 章节折叠
  ├─ #13 证据链接
  └─ #14 RAG 基础架构

Week 7-8 ────────────────────────────────────────────────────
  ├─ #15 PDF 研报解析
  ├─ #16 用户长期记忆
  ├─ #17 PDF 导出
  └─ #18 RiskAgent

Week 9+ ─────────────────────────────────────────────────────
  └─ P4 锦上添花功能...
```

---

## 🔥 如果只能做 3 件事

如果时间极其有限，**只做这 3 件**就能让产品“可信且可控”：

| 优先级 | 任务 | 理由 |
|--------|------|------|
| **#1** | 证据链硬约束 | 关键结论必须可追溯，否则报告不可用 |
| **#2** | 计划/执行规范化 | 防止流程漂移，确保执行可审计 |
| **#3** | 安全与合规门禁 | 未鉴权/无免责声明即不可对外 |

**下一步重点**：
| 优先级 | 任务 | 理由 |
|--------|------|------|
| **#1** | 数据一致性上下文 | 统一口径，避免报告前后矛盾 |
| **#2** | 预算/超时控制 | 降低成本与时延风险 |
| **#3** | Reflection 可检验审校 | 把“反思”从感性变成可验证 |

---

## ⚠️ 风险提示

| 风险 | 影响 | 应对 |
|------|------|------|
| 流式输出改动大 | 可能影响现有稳定性 | 保留回退开关 |
| Supervisor 异步化复杂 | 可能引入新 bug | 充分测试 |
| RAG 学习曲线陡 | 可能超时 | 先 Mock，再真实 |
| 多 Agent 并行限流 | API 调用失败 | 熔断器已就位 |

---

## 🧭 静态推演测试与体验风险（基于现有源码）

### 1) 调用链流程图（Mermaid）
```mermaid
flowchart TD
    A[User Input] --> B[/chat or /chat/stream]

    B -->|/chat| C[ConversationAgent.chat_async (fallback chat)]
    B -->|/chat/stream| C2[chat_stream_endpoint]

    C --> D[ContextManager.resolve_reference]
    D --> E[ConversationRouter.route]
    E --> F{Intent}

    F -->|CHAT| G[ChatHandler.handle]
    F -->|REPORT| H{Supervisor + ticker?}
    F -->|FOLLOWUP| I[FollowupHandler.handle]
    F -->|ALERT| J[_handle_alert (placeholder)]
    F -->|GREETING| K[_handle_greeting]
    F -->|CLARIFY| L[_handle_clarify]

    H -->|Yes| H1[_handle_report_async -> AgentSupervisor.analyze]
    H1 --> H1a[ForumHost.synthesize]
    H1a --> H1b[ReportIR convert]
    H -->|No| H2[ReportHandler.handle]

    G --> G1{Chat sub-branches}
    G1 -->|news| G2[_handle_news_query]
    G1 -->|price| G3[_handle_price_query]
    G1 -->|info| G4[_handle_info_query]
    G1 -->|composition| G5[_handle_composition_query]
    G1 -->|advice| G6[_handle_advice_query]
    G1 -->|comparison| G7[_handle_comparison_query]
    G1 -->|fallback| G8[_handle_with_search]

    C --> M[ContextManager.add_turn]
    M --> N[_add_chart_marker (CHAT/REPORT/FOLLOWUP)]

    C2 --> R2[ContextManager.resolve_reference]
    R2 --> E2[ConversationRouter.route]
    E2 --> F2{Intent}
    F2 -->|REPORT + supervisor + ticker| S0[supervisor.analyze_stream -> stream_supervisor_sse]
    F2 -->|REPORT + report_agent| S1[report_agent.analyze_stream -> stream_report_sse]
    F2 -->|REPORT fallback| S1b[agent.chat -> 句子切块流式]
    F2 -->|Others| S2[agent.chat -> 句子切块流式]
```

### 2) 静态 trace 示例（调用链推演）

2.1 问候/闲聊  
示例："你好"  
路径：Router quick match → GREETING → _handle_greeting  
潜在问题：包含金融关键词时可能被判为 CHAT。

2.2 简单行情查询  
示例："AAPL 现在多少钱"  
路径：Router 提取 ticker → CHAT → _handle_price_query。

2.3 深度报告  
示例："分析特斯拉"  
路径：REPORT → Supervisor（有 ticker）→ _handle_report_async → ReportIR。  
流式：/chat/stream 优先 Supervisor analyze_stream；无 Supervisor 时再走 report_agent。

2.4 报告但无 ticker  
示例："写一份详细分析"  
路径：REPORT → ReportHandler.handle → 澄清提示。  
潜在问题：用户可能误解为拒答。

2.5 追问（有上下文）  
示例："为什么"（上一轮有报告）  
路径：FOLLOWUP → _handle_report_followup。

2.6 追问（无上下文）  
示例："为什么"（无历史）  
路径：FOLLOWUP → CLARIFY。

2.7 订阅/提醒  
示例："帮我盯着 NVDA"  
路径：ALERT → _handle_alert（占位说明）。

2.8 新闻  
示例："英伟达最近有什么新闻"  
路径：CHAT → _handle_news_query（无 ticker 时退化到市场新闻/默认指数）。

2.9 多标的对比  
示例："AAPL vs MSFT 今年表现"  
路径：CHAT → metadata.is_comparison → _handle_comparison_query。

2.10 指代消解  
示例：上一轮问 "AAPL 股价"，本轮问 "它的新闻"  
路径：ContextManager.resolve_reference → CHAT → _handle_news_query。  
状态：/chat/stream 已走 resolve_reference。

### 3) 体验缺陷 / 潜在纰漏 + task-stub

Issue 1: REPORT 意图对中文/模糊请求不稳定（已优化）  
- 现状：已补充“研报/投研/估值/基本面”等关键词与金融上下文判断。  
- 建议：继续观察边界语句与误判率。

Issue 2: /chat/stream 非 REPORT 伪流式（已修复）  
- 现状：已接入 ChatHandler/FollowupHandler 真实 token 流式。  
- 建议：继续统一 SSE 事件语义与错误码格式。

Issue 3: /chat/stream Supervisor 接入（已完成）  
- 现状：REPORT 流式已优先走 Supervisor analyze_stream。  
- 建议：后续补充指代消解与无 ticker 的澄清体验。

Issue 4: /chat/stream 未做指代消解（已完成）  
- 现状：/chat/stream 已调用 ContextManager.resolve_reference。  
- 建议：补充跨轮多指代的测试覆盖。

Issue 5: ALERT/订阅为占位  
- 现状：只返回“开发中”，用户预期落空。  
- 建议：最小可用版本先支持订阅写入 + 简单触发策略。

Issue 6: 深度新闻工具缺口  
- 现状：deepsearch_news 可选存在，缺失时直接降级。  
- 补充：市场热点已接入 Reuters/Bloomberg RSS + Finnhub 48h，仍缺少深度检索与反思循环。  
- 建议：明确实现或固定降级策略，并标记“来源/覆盖率”。

### 4) 缺失能力与子 Agent 缺陷

4.1 缺失能力  
- RAG/向量检索尚未落地。  
- 向量 RAG（LlamaIndex + Chroma）仍未落地。  
- MacroAgent 宏观数据仍为 Mock。  
- 财报工具仅 yfinance，缺少多源回退与文档级检索。

4.2 子 Agent 缺陷  
- TechnicalAgent / FundamentalAgent 已完成（2026-01-10）。  
- DeepSearch / Macro 子 Agent 输出证据不足。  
- Supervisor 在 /chat 与 /chat/stream 均可用，指代消解已接入。

### 5) 优先级更新（结合现状）

P0  
1. ✅ 真正的流式输出（/chat/stream 全意图逐 token，统一 SSE 协议）。  
2. ✅ /chat/stream 接入 Supervisor 报告流式聚合路径。  
3. ✅ REPORT 意图与无 ticker 澄清优化 + /chat/stream 指代消解。  
4. ✅ TechnicalAgent + FundamentalAgent（2026-01-10）。  

P1  
5. ✅ ReportIR Schema + Validator（2026-01-10）。  
6. ✅ DeepSearchAgent 真实检索 + PDF + Self-RAG（2026-01-11）。

P2  
6. MacroAgent 升级（FRED）。  
7. 向量 RAG 基础（LlamaIndex + Chroma）。

P3  
8. RAG 基础架构 + 文档入库流程。

---

## 📌 结论（2026-01-22 更新）

**核心原则**：先建立"测量与回归"，再做"策略优化"。

**最新完成 (2026-01-22)**:
- ✅ P0-Fix 空壳修复（forum.py/news_agent.py/DataContext）
- ✅ 代码仓库清理（langchain 文件归位、legacy 目录整理）
- ✅ P0 质量门槛全部完成（#25-29）

---

## 📋 严肃版 TodoList（带验收标准）

### P1 - 质量闭环（近期必须）

| # | 任务 | 交付物 | 验收标准 |
|---|------|--------|----------|
| **34** | 回归评估基线（已完成 2026-01-22） | `tests/regression/` 基准集(25条) + 一键脚本 | 覆盖率/引用/耗时统计；JSON/MD对比报告；CI 0.4s |
| **31** | ReAct 搜索收敛 | 信息增益评分 + 去重 + 停止条件（DeepSearch + News + Macro） | 轮次降≥20%；引用不降；回归不退化 |
| **Trace** | 可观测性统一 | TraceEvent schema(event_type/duration/metadata) + supervisor_stream v1 normalize | 前端统一展开 trace 详情 |

### P2 - 产品体验（保证可用性）

| # | 任务 | 交付物 | 验收标准 |
|---|------|--------|----------|
| **FE** | 研报前端分析视图 | 章节导航 + 引用证据可展开 + 置信度/新鲜度可视 | 引用可点击；字段展示一致 |
| **Dashboard** | 仪表盘+自选股 | 实时涨跌/新闻流/提醒 + 本地存储 | 实时刷新；数量可配置 |
| **RAG** | DeepSearch 向量化 | PDF研报入库 + 向量检索 + 引用追溯 | ≥1份研报可检索并引用到具体段落 |

### P3 - 功能扩展（风险较高）

| # | 任务 | 交付物 | 验收标准 |
|---|------|--------|----------|
| **Memory** | 用户长期记忆 | 向量化偏好存储与召回 | 连续对话正确复用偏好 |
| **Risk** | RiskAgent | VaR计算 + 仓位诊断 + 免责声明 | VaR有来源；不输出确定性建议 |
| **Visual** | 指数成分权重可视化 | treemap/饼图 | 权重正确；来源可解释 |

### 关键原则（防空壳）

每个任务必须有：
- ✅ 代码实现
- ✅ 测试/回归验证
- ✅ 文档更新

**没有可运行的测试或可解释的指标 = 不算完成**

---

*本路线图基于 01-05 文档 + README + 当前代码状态综合分析*
