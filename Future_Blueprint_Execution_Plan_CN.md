# FinSight × BettaFish 多Agent升级终极执行计划（2025-12-09）

本文档是 FinSight 项目对齐 BettaFish 架构的唯一执行依据。其他相关文档（BettaFish_Alignment_Plan_CN.md、FinSight_BettaFish_Final_Plan_2025-12-08.md、feature_logs/opus.md）归档为技术参考，不再单独维护。

---

## 一、项目愿景：从“股票助手”到“智能合伙人”

我们不仅仅是在做一个股票查询工具，而是构建一个全天候的**个人金融顾问平台**：
- **🌞 白天**：实时监控自选股，推送异动/关键消息（"RiskAgent" + "AlertSystem"）。
- **🌙 晚上**：复盘市场，生成个性化日报（"ForumHost" + "Personalized Memory"）。
- **📈 长期**：跟踪宏观趋势，提供资产配置建议（"MacroAgent" + "DeepSearchAgent"）。

**核心理念**：
- **Agent分工**：专业的人做专业的事（Price/News/Tech/Fund Agent）。
- **MCP驱动**：底层数据源插件化，业务层只关注逻辑。
- **主动服务**：从"用户问我才答"升级为"主动发现并推送"。

---

## 二、BettaFish 核心机制速览（必须理解）
bettaFish 项目地址：
https://github.com/batfish/batfish
bettaFish 项目 README：
C:\Users\Administrator\Downloads\README.md

### 2.1 论坛式多Agent协作
- **四个专职Agent**：QueryAgent（新闻搜索）、MediaAgent（多模态）、InsightAgent（历史舆情）、ReportAgent（报告整合）
- **ForumEngine**：中央论坛，Agent不直接通信，通过forum.log异步交流
- **ForumHost**：独立LLM主持人，输出四段式引导（事件时间线→观点整合→深度分析→讨论指引）

### 2.2 反思循环（Reflection Loop）
每个Agent内部：初始搜索 → 首次总结 → [ReflectionNode识别知识空白 → 精炼搜索 → ReflectionSummaryNode更新总结] × 2-3轮

### 2.3 高召回+KV缓存
- 多源并行搜索（Tavily+DDG+爬虫）
- LLM仅做2-5句摘要，保留Markdown链接
- 结果写入KV（key=ticker:field，含as_of/source/text/links/ttl）

### 2.4 中间表示（IR）
报告先生成结构化JSON（sections/evidence/confidence/risks），校验后再渲染Markdown/HTML

---

## 三、FinSight目标架构

```
User → Orchestrator (LangGraph + UserContext)
       ├── PriceAgent        [常驻] 实时行情，TTL=30秒
       ├── TechnicalAgent    [常驻] 技术指标，TTL=5分钟
       ├── FundamentalAgent  [常驻] 财报估值，TTL=1小时
       ├── NewsAgent         [常驻] 新闻舆情，TTL=10分钟
       ├── MacroAgent        [按需] 宏观事件，复杂问题触发
       ├── DeepSearchAgent   [按需] 长文研究，信息不足触发
       │
       ├── RiskAgent         [NEW] 风险控制与持仓建议 (Phase 3)
       │
       → ForumHost（冲突消解+观点融合+个性化注入）
       → IR校验 → ReportRenderer（Markdown/HTML/PDF）
```

**共享层：**
- **Memory (User Profile)**: 用户偏好、持仓、关注列表 `backend/services/memory.py`
- **KV缓存**: `backend/services/cache.py`
- **熔断器**: `backend/services/circuit_breaker.py`
- **诊断日志**: source/duration_ms/fail_reason/fallback_used/cache_hit

---

## 四、分阶段执行计划

### 阶段0：基座强化（第1-2周） - ✅ 基本完成

*   ✅ 工具输出标准化 (`tools.py`)
*   ✅ KV缓存层 (`cache.py`)
*   ✅ 独立熔断器 (`circuit_breaker.py`)
*   ✅ 搜索兜底
*   ⚠️ LangGraph打点 - **待完善**
*   ✅ 前端诊断面板

---

### 阶段1：子Agent雏形 + 个性化记忆（第3-4周）

#### Week 3.0: 基础设施补全
- ✅ 实现 `backend/services/circuit_breaker.py` (Phase 0 补全)
- 完善 LangSmith Tracing

#### Week 3.5: UserContext & Memory (新增)
- ✅ **文件**: `backend/services/memory.py`
- **功能**:
    - 存储用户风险偏好 (Conservative/Balanced/Aggressive)
    - 存储 Watchlist (关注股票)
    - 提供 `get_user_profile(user_id)` 接口供 Agent 使用

#### Week 4: BaseAgent + NewsAgent + PriceAgent + Orchestrator
- ✅ **BaseAgent**: 定义标准 `AgentOutput`
- ✅ **PriceAgent**: 多源回退 + 极速行情
- ✅ **NewsAgent**: 实现 Reflection Loop (反思循环)
- **Orchestrator**: 集成 `Memory` 模块，将用户偏好注入 Prompt

**验收标准**:
- ✅ NewsAgent 可独立运行且会自我反思
- ✅ Agent 能根据用户风险偏好调整语气（激进用户推成长股，保守用户推防御股）

---

### 阶段2：IR + 深度分析 + 前端展示（第5-6周）

#### Week 5: IR Schema + DeepSearch + Macro
- **ReportIR**: 结构化报告定义
- **DeepSearchAgent**: 长文抓取与深度研报分析
- **MacroAgent**: 宏观经济数据接入

#### Week 6: 前端可视化与交互
- 报告章节折叠
- 置信度进度条
- 引用来源点击跳转
- **"智能合伙人"模式**: 侧边栏显示 User Profile 设置

---

### 阶段3：主动服务与风控（第7-8周） - [NEW]

此阶段旨在实现“智能合伙人”的主动性。

#### Week 7: RiskAgent (风控专家)
- **文件**: `backend/agents/risk_agent.py`
- **职责**:
    - 计算 VaR (Value at Risk)
    - 结合用户持仓，给出仓位调整建议 (Rebalancing)
    - 检测持仓集中度风险

#### Week 8: AlertSystem (主动推送)
- **文件**: `backend/services/alert_system.py`
- **功能**:
    - 后台轮询 Watchlist 价格/新闻
    - 触发异动阈值时，生成简报
    - 模拟推送 (Log/Email/Webhook)

**验收标准**:
- ✅ 系统能在后台自动发现异动并记录日志
- ✅ 针对模拟持仓给出具体的调仓建议（如：减仓 AAPL，加仓 债券）

---

## 五、关键代码路径汇总

```
backend/
├── agents/
│   ├── base_agent.py         # AgentOutput
│   ├── price_agent.py
│   ├── news_agent.py         # 含 Reflection
│   ├── technical_agent.py
│   ├── fundamental_agent.py
│   ├── macro_agent.py
│   ├── deep_search_agent.py
│   └── risk_agent.py         # [NEW Phase 3]
├── orchestration/
│   ├── orchestrator.py
│   └── forum.py              # ForumHost
├── report/
│   └── ir.py                 # ReportIR
├── services/
│   ├── cache.py
│   ├── circuit_breaker.py
│   ├── memory.py             # [NEW Phase 1.5] User Profile & Watchlist
│   └── alert_system.py       # [NEW Phase 3] Background Monitor
└── tools.py

frontend/src/
├── components/
│   ├── Diagnostics.tsx
│   ├── ReportView.tsx
│   └── UserProfile.tsx       # [NEW] 用户偏好设置
```

---

## 六、风险与应对

| 风险 | 应对 |
|------|------|
| 多Agent并行API限流 | 熔断器 + 优先级队列 + 免费源轮询 |
| 主动推送噪音过大 | 设置严格的阈值 + "重要性"评分模型 |
| 记忆模块隐私问题 | 本地存储 + 敏感数据脱敏 |
| 复杂计算(VaR)性能 | 异步计算 + 预计算缓存 |

---

**完成以上全部，FinSight 将不仅仅是一个工具，而是真正懂你的 AI 投资合伙人。**
