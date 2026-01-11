# FinSight 开发优先级路线图
> 📅 **制定日期**: 2026-01-09
> 📅 **更新日期**: 2026-01-11
> 🎯 **目标**: 从当前状态到项目完工的最现实、最犀利的优先级排序

---

## 📊 当前状态一览

| 阶段 | 进度 | 核心问题 |
|------|------|----------|
| Phase 0 (基座) | ✅ 100% | 无 |
| Phase 1 (Agent 团) | ✅ 100% | 核心 Agents 已齐 |
| Phase 2 (深度研报) | 🟡 75% | Macro 升级/向量 RAG/交互优化 待落地 |
| Phase 3 (主动服务) | 🔵 5% | 订阅/告警能力尚未落地 |

---

## 🎯 优先级排序原则

1. **用户可感知 > 技术债务** - 先解决用户能直接看到的问题
2. **修复 > 新功能** - 先把现有功能做好
3. **核心路径 > 边缘功能** - 先搞定主流程
4. **低耦合任务先做** - 避免返工

---

## 📋 完整优先级列表（共 24 项）

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
| **6** | **Agent 协作进度指示器** | 2h | 用户知道后台在干嘛，减少等待焦虑 | #2 |

### 🟡 P2 - 中优先级（2-4 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **7** | **ReportIR Schema 完善（已完成 2026-01-10）** | 3h | 标准化报告结构，前后端解耦 | #3, #4 |
| **8** | **IR Validator 实现（已完成 2026-01-10）** | 2h | 防止畸形数据到前端 | #7 |
| **9** | **NewsAgent 反思循环增强** | 3h | 自动识别信息空白并补充搜索 | #2 |
| **10** | **DeepSearchAgent 真实检索 + PDF + Self-RAG（已完成 2026-01-11）** | - | 真实检索与反思检索落地 | #9 |
| **11** | **MacroAgent 升级** | 3h | 集成 FRED API 获取宏观经济数据 | #2 |
| **12** | **前端章节折叠/滚动高亮交互（已完成 2026-01-11）** | - | 报告太长需要折叠与定位 | #7 |
| **13** | **证据链接可点击 + 图表渲染 + Chart 规范（已完成 2026-01-11）** | - | 引用联动与图表可视化 | #7 |

### 🟢 P3 - 低优先级（4-6 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **14** | **RAG 基础架构** | 6-8h | LlamaIndex + Chroma 向量检索 | #10 |
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

如果时间极其有限，**只做这 3 件**就能让产品"能用"：

| 优先级 | 任务 | 理由 |
|--------|------|------|
| **#1** | MacroAgent 升级 | 宏观数据联动报告判断 |
| **#2** | 向量 RAG 基础 | LlamaIndex + Chroma 入库与检索 |
| **#3** | Agent 进度指示器 | 提升等待过程的透明度 |

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

## 📌 结论（2026-01-11 更新）

当前核心痛点转向“MacroAgent 未升级 + 向量 RAG 未落地 + 協调等待体验待优化”。
优先级应聚焦在 **MacroAgent 升级 + 向量 RAG 基础 + Agent 进度指示器**，同时保持交互体验优化：
- /chat/stream 已完成 token 流、Supervisor 聚合与指代消解。
- TechnicalAgent 与 FundamentalAgent 已补齐（2026-01-10）。
- DeepSearchAgent 真实检索 + PDF + Self-RAG 已完成（2026-01-11）。
- 前端 Report 卡片 UI 已对齐 design_concept_v2.html（2026-01-11）。
- ReportIR Schema + Validator 已完成（2026-01-10）。
- 中期引入 DeepSearch 真实检索与 Self-RAG，提升报告可信度与可追溯性。

---

*本路线图基于 01-05 文档 + README + 当前代码状态综合分析*
