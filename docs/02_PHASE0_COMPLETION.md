# FinSight 阶段0：基座强化完成报告

> **更新日期**: 2026-01-22
> **状态**: 已完成 (100%)
>
> **近期同步**:
> - ReportIR citations 增加 confidence / freshness_hours 字段（P0-2）
> - News/Macro 回退结构化输出，避免 raw 文本进入报告（P0-3）
> - get_company_news 改为结构化列表，NewsAgent/ReportHandler/ChatHandler 同步适配（P1-1）
> - SSRF 防护扩展至 DeepSearch + fetch_url_content（P1-2）
> - pytest 收集 backend/tests + test/（不再标记 legacy）
> - PlanIR + Executor 与 EvidencePolicy 落地（计划模板/执行 trace/引用校验）
> - DataContext 统一 as_of/currency/adjustment 并输出一致性告警（P0-27）
> - BudgetManager 限制工具调用/轮次/耗时预算，预算快照可追溯（P0-28）
> - SecurityGate：鉴权 + 限流 + 免责声明模板落地（P0-29）
> - Cache 抖动 + 负缓存，CircuitBreaker 支持分源阈值
> - Trace 规范化输出 + /metrics 可观测性入口

> - Split backend/tools.py into backend/tools/ (search/news/price/financial/macro/web); keep backend.tools compatibility
> - Config entry unified: backend/llm_config.py uses user_config.json > .env; llm_service uses same source
> - Core backend logging migrated from print to logging (API/Agents/Services/Orchestration)
---

## 1. 目标回顾

Phase 0 的核心目标是**为多 Agent 架构打下坚实的地基**，解决早期版本中"工具不稳定"、"响应慢"、"无法观测"的三大痛点。

---

## 2. 核心成果交付

- **标准化输出**: 所有工具函数（Price, News, Search）现在返回统一的 `dict` 结构，包含 `source`, `duration_ms`, `fallback_used` 等元数据。
- **多源回退**: 实现了 `yfinance -> finnhub -> alpha_vantage -> tavily` 的自动降级策略。
- **市场新闻源**: Reuters RSS + Bloomberg RSS（默认列表，支持 `BLOOMBERG_RSS_URLS` 扩展）+ Finnhub `general_news` 48h；搜索回退保留 3d/7d 时效过滤。
- **搜索兜底**: 当所有 API 都挂掉时，自动调用 Search 工具抓取网页摘要，确保"永远有回复"。
- **连接池/重试**: 统一 Session + Retry，减少握手开销并提升稳定性。

### 2.2 KV 缓存系统 (`backend/services/cache.py`)
- **实现**: 基于内存的 TTL 缓存。
- **策略**:
    - **Price**: 30s (保证实时性)
    - **News**: 600s (平衡时效与 Token)
    - **Fundamental**: 1h (财报数据不常变)
- **抖动/负缓存**: TTL 抖动避免雪崩，负缓存减少穿透（`CACHE_JITTER_RATIO` / `CACHE_NEGATIVE_TTL`）。
- **效果**: 热门股票（如 AAPL）的重复查询响应时间从 3s 降至 <10ms。

### 2.3 可观测性 (`backend/langchain_agent.py`)
- **LangSmith 集成**: 实现了全链路 Tracing。
- **前端诊断**: 新增 `DiagnosticsPanel.tsx`，用户可以在前端实时看到：
    - 哪个工具被调用了？
    - 耗时多少？
    - 是否命中了缓存？
    - 是否触发了熔断？
- **Prometheus 指标**: 提供 `/metrics` 入口（可选依赖 `prometheus-client`）。

### 2.4 路由与意图识别优化 (`backend/conversation/router.py`)
- **已知 Ticker 白名单**: 修复了 `AAPL` 被错误翻译为中文导致 API 调取失败的 Bug。
- **泛化推荐识别**: 修复了"推荐股票"被粘连到上文 `AAPL` 的问题，现在可以正确识别为通用意图。

### 2.5 独立熔断器服务 (`backend/services/circuit_breaker.py`)
- **实现**: 完整的 Circuit Breaker 模式 (CLOSED/OPEN/HALF_OPEN)。
- **集成**: 集成至 `ToolOrchestrator`，自动隔离不稳定的 API 源。
- **分源阈值**: 支持按源配置 failure/recovery 参数（`CB_<SOURCE>_FAILURE_THRESHOLD` / `CB_<SOURCE>_RECOVERY_TIMEOUT`）。
- **状态机**:
    - 失败阈值触发熔断
    - 冷却期后允许试探性请求 (Half-Open)
    - 试探成功自动恢复

---

## 3. 遗留问题与补救

| 问题 | 状态 | 补救计划 |
|------|------|----------|
| **LangGraph 迁移** | 进行中 | 目前仍是混合架构，Phase 1 将完全迁移到 Graph |

---

## 4. 结论

基座已完全稳固，可以直接进入 **Phase 1: Agent 专家团** 的开发。

---

## 5. 补充更新（2026-01-10）

- 本阶段无新增功能变更，仅同步整体进度与文档更新日期。
