# FinSight 开发优先级路线图
> 📅 **制定日期**: 2025-12-30
> 🎯 **目标**: 从当前状态到项目完工的最现实、最犀利的优先级排序

---

## 📊 当前状态一览

| 阶段 | 进度 | 核心问题 |
|------|------|----------|
| Phase 0 (基座) | ✅ 100% | 无 |
| Phase 1 (Agent 团) | ⚠️ 70% | Supervisor 异步问题、缺少 Technical/Fundamental Agent |
| Phase 2 (深度研报) | ⚠️ 30% | 流式输出假的、Report 卡片需优化 |
| Phase 3 (主动服务) | ❌ 5% | 仅有邮件订阅框架 |

---

## 🎯 优先级排序原则

1. **用户可感知 > 技术债务** - 先解决用户能直接看到的问题
2. **修复 > 新功能** - 先把现有功能做好
3. **核心路径 > 边缘功能** - 先搞定主流程
4. **低耦合任务先做** - 避免返工

---

## 📋 完整优先级列表（共 24 项）

### 🔴 P0 - 必须立即修复（本周）

| # | 任务 | 工时 | 理由 | 阻塞项 |
|---|------|------|------|--------|
| **1** | **真正的流式输出** | 4-6h | 用户直接抱怨"一次性吐出来"，体验最差的一环 | 无 |
| **2** | **修复 Supervisor asyncio 问题** | 3-4h | 阻塞多 Agent 协作，当前被迫禁用 | 依赖 #1 |

### 🟠 P1 - 高优先级（1-2 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **3** | **TechnicalAgent 实现** | 4-5h | 技术分析是金融产品刚需（MA/RSI/MACD） | #2 |
| **4** | **FundamentalAgent 实现** | 4-5h | 估值分析是投资决策核心（PE/PB/DCF） | #2 |
| **5** | **前端 Report 卡片优化** | 2-3h | 对齐 design_concept_v2.html，视觉升级 | #1 |
| **6** | **Agent 协作进度指示器** | 2h | 用户知道后台在干嘛，减少等待焦虑 | #2 |

### 🟡 P2 - 中优先级（2-4 周内）

| # | 任务 | 工时 | 理由 | 依赖 |
|---|------|------|------|------|
| **7** | **ReportIR Schema 完善** | 3h | 标准化报告结构，前后端解耦 | #3, #4 |
| **8** | **IR Validator 实现** | 2h | 防止畸形数据到前端 | #7 |
| **9** | **NewsAgent 反思循环增强** | 3h | 自动识别信息空白并补充搜索 | #2 |
| **10** | **DeepSearchAgent 升级** | 4h | 长文 PDF 解析能力 | #9 |
| **11** | **MacroAgent 升级** | 3h | 集成 FRED API 获取宏观经济数据 | #2 |
| **12** | **前端章节折叠交互** | 2h | 报告太长需要折叠 | #7 |
| **13** | **证据链接可点击** | 1h | 增加报告可信度 | #7 |

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
  ├─ #1 真正的流式输出 ✦ 用户体验关键
  ├─ #2 修复 Supervisor 异步
  └─ #5 前端卡片优化

Week 2 ──────────────────────────────────────────────────────
  ├─ #3 TechnicalAgent
  ├─ #4 FundamentalAgent
  └─ #6 Agent 进度指示器

Week 3-4 ────────────────────────────────────────────────────
  ├─ #7 ReportIR Schema
  ├─ #8 IR Validator
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
| **#1** | 真正的流式输出 | 解决用户直接抱怨的体验问题 |
| **#3 + #4** | Technical + Fundamental Agent | 补全核心分析能力 |
| **#7** | ReportIR Schema | 结构化输出，前后端稳定 |

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

    C2 --> E2[ConversationRouter.route]
    E2 --> F2{Intent}
    F2 -->|REPORT + report_agent| S1[report_agent.analyze_stream -> stream_report_sse]
    F2 -->|REPORT no report_agent| S1b[agent.chat -> 句子切块流式]
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
流式：/chat/stream 若有 report_agent 且支持 analyze_stream，则真实流式。

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
潜在问题：/chat/stream 未走 resolve_reference。

### 3) 体验缺陷 / 潜在纰漏 + task-stub

Issue 1: REPORT 意图对中文/模糊请求不稳定  
- 现状：部分中文“分析/研报/报告”可能路由为 CHAT。  
- 建议：补充中文关键词 + LLM/规则兜底，允许“分析/研报/报告 + 公司名/中文名/股票名词”触发 REPORT。

Issue 2: /chat/stream 非 REPORT 为伪流式  
- 现状：按句子切块输出，无法“逐 token”体验。  
- 建议：为 ChatHandler 与 FollowupHandler 接入真实模型流式，统一 SSE 事件协议。

Issue 3: /chat/stream 未接入 Supervisor  
- 现状：多 Agent 聚合仅在 /chat 生效，流式路径无法展示子 Agent 结果。  
- 建议：补一条 Supervisor streaming 路径或允许 /chat/stream 调用 chat_async 并输出 token。

Issue 4: /chat/stream 未做指代消解  
- 现状：短句指代（它/这个）在流式路径失效。  
- 建议：在 stream 入口调用 ContextManager.resolve_reference。

Issue 5: ALERT/订阅为占位  
- 现状：只返回“开发中”，用户预期落空。  
- 建议：最小可用版本先支持订阅写入 + 简单触发策略。

Issue 6: 深度新闻工具缺口  
- 现状：deepsearch_news 可选存在，缺失时直接降级。  
- 建议：明确实现或固定降级策略，并标记“来源/覆盖率”。

### 4) 缺失能力与子 Agent 缺陷

4.1 缺失能力  
- RAG/向量检索尚未落地。  
- Self-RAG（Self-Reflective RAG）未实现。  
- DeepSearchAgent 仍为 Mock（无真实搜索/PDF/财报阅读）。  
- 财报工具仅 yfinance，缺少多源回退与文档级检索。

4.2 子 Agent 缺陷  
- TechnicalAgent / FundamentalAgent 未落地。  
- DeepSearch / Macro 子 Agent 输出证据不足。  
- Supervisor 仅在 /chat 生效，/chat/stream 无法展示多 Agent 结果。

### 5) 优先级更新（结合现状）

P0  
1. 真正的流式输出（/chat/stream 全意图逐 token，统一 SSE 协议）。  
2. /chat/stream 接入 Supervisor 或提供等价的报告流式聚合路径。  
3. REPORT 意图与无 ticker 澄清优化 + /chat/stream 指代消解。

P1  
4. TechnicalAgent + FundamentalAgent。  
5. DeepSearchAgent 真实检索 + PDF 解析 + 新闻深度工具。

P2  
6. ReportIR Schema + Validator 稳定化。  
7. Self-RAG v1（反思式检索增强）。

P3  
8. RAG 基础架构 + 文档入库流程。

---

## 📌 结论（2026-01-09 更新）

当前对话体验的核心痛点来自“流式不真 + 路由/上下文不一致 + 占位功能落空”。
优先级应聚焦在 **真实流式 + Supervisor/上下文完整接入**，其次补齐子 Agent 与检索能力：
- 先打通 /chat/stream 的真正 token 流与多 Agent 聚合。
- 同步修复 REPORT 意图稳定性与无 ticker 澄清体验。
- 中期引入 DeepSearch 真实检索与 Self-RAG，提升报告可信度与可追溯性。

---

*本路线图基于 01-05 文档 + README + 当前代码状态综合分析*
