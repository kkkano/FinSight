# FinSight 阶段1：专家 Agent 团与记忆构建

> 📅 **计划周期**: Week 3 - Week 4
> 📅 **更新日期**: 2026-01-10
> 🎯 **核心目标**: 从"单体大模型"进化为"分工明确的专家团队"

---

## 1. 核心任务拆解

### 1.1 基础设施补全 (Week 3.0)
- [x] **CircuitBreaker**: 实现滑动窗口熔断器 `backend/services/circuit_breaker.py`。 (Phase 0 完成)
- [x] **Memory Service**: 实现用户画像存储 `backend/services/memory.py`。
- [x] **API Integration**: 集成 Memory Service 到 FastAPI 主服务，提供用户画像接口。

### 1.2 专家 Agent 实现 (Week 3.5)
- [x] **BaseAgent**: 定义标准接口与 `AgentOutput` 数据类。
- [x] **PriceAgent**: 极速行情专家，不仅查价，还能看盘口（Bid/Ask）。
- [x] **NewsAgent**: 舆情专家，集成 **Reflection Loop**（反思循环），官方 RSS（Reuters/Bloomberg）+ Finnhub 48h 优先，自动去重、验证新闻源。

### 1.3 编排与决策 (Week 4.0)
- [x] **Supervisor**: 实现 `AgentSupervisor` (backend/orchestration/supervisor.py) 负责调度 Agent。
- [x] **ForumHost**: 实现 `ForumHost` (backend/orchestration/forum.py) 负责冲突消解和结果综合。
- [x] **Integration**: 将 Supervisor 集成到 `ConversationAgent` (backend/conversation/agent.py)，支持多 Agent 报告生成。
- [x] **UserContext 注入**: 让 ForumHost 根据用户是"激进型"还是"保守型"调整建议口吻。

---

## 2. 关键技术难点

### 2.1 反思循环 (Reflection Loop)
如何让 NewsAgent 自己意识到"信息不够"？
- **方案**: 第一轮搜索后，让 LLM 自评："我是否找到了具体的发布日期？是否找到了竞品对比？"
- **Prompt**: "Identify missing key information from the summary. If critical data is missing, generate a targeted search query."

### 2.2 记忆注入 (Context Injection)
如何在不污染上下文的前提下注入用户偏好？
- **方案**: 在 System Prompt 中动态插入 User Profile Section。
- **示例**:
  ```text
  You are advising a [Conservative] investor who holds [AAPL, MSFT].
  Focus on downside risk and dividend stability.
  ```

---

## 3. 验收标准

1.  **NewsAgent 独立测试**: 给定模糊查询（"苹果最近那个头显怎样"），能自动进行 2 轮以上搜索，输出包含具体参数和发售日期的报告。
2.  **个性化测试**: 同一个问题（"现在能买英伟达吗"），对保守型用户提示"估值过高风险"，对激进型用户提示"突破买入机会"。
3.  **并行性能**: 4 个 Agent 并行执行总耗时不超过最慢 Agent 的 1.2 倍。

---

## 4. 补充更新（2026-01-09）

- /chat 使用 `chat_async`，Supervisor 异步链路稳定
- /chat/stream 支持 ReportAgent 真实流式，SSE done 事件带 ReportIR
- /chat/stream 已接入 resolve_reference，与 /chat 链路一致

---

## 5. 补充更新（2026-01-10）

- 新增 TechnicalAgent（MA/RSI/MACD）与 FundamentalAgent（财务指标/现金流/杠杆）并接入 Supervisor
- 新增单测覆盖 Technical/Fundamental 输出与 Supervisor 注册
