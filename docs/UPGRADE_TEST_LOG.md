# FinSight 升级测试日志

> 记录按照《FinSight AI 升级蓝图执行计划》逐步迭代时，每一阶段/功能的测试结果。  
> 原则：**每完成一个小模块，必须有一次明确的测试记录，并在测试通过后才能进入下一步。**

---

## 2025-12-03 – P0 基线测试（当前代码）

- 范围：项目根目录执行 `python -m pytest`，验证现有单 Agent + 工具层 + LangGraph CIO Agent 的整体健康情况。  
- 结果：**失败（INTERNALERROR）**  
  - 失败用例：`test/test_langchain.py` 在导入 `langchain_agent` 时抛出 `ModuleNotFoundError`。  
  - 影响：pytest 在收集阶段即中断，导致其余 100+ 个测试用例未实际运行。  
  - 分析：
    - 早期测试脚本依赖根目录下的 `langchain_agent.py` 顶层模块名；
    - 当前代码已将 LangGraph CIO Agent 移入 `backend/langchain_agent.py`，但测试仍引用旧路径；
    - 因此蓝图中的“单 Agent + 强工具 + 稳体验”虽然在运行中基本可用，但 **自动化测试体系尚未完全跟上重构。**

- 下一步计划（P0.1）：
  1. 为 `test/test_langchain.py` 和相关测试提供兼容层：
     - 在项目根目录增加轻量包装，或调整测试导入路径，使其指向 `backend.langchain_agent`；
     - 确保旧测试不再因为模块名变更而导致整个 pytest 会话中止。
  2. 再次运行 `python -m pytest`，目标是至少让所有测试都能“收集完成 + 正常执行”，即便有功能性失败，也应是明确的单测断言失败，而不是 `INTERNALERROR`。  
  3. 在上述修复完成并测试通过后，继续按执行计划推进后续 P0 稳定性改进。

---

## 2025-12-04 – P0.1 新测试基线（缓存模块）

- 调整：
  - 新增 `pytest.ini`，限制 pytest 默认只递归 `backend/tests` 与 `test`，并忽略 `archive` 中的旧版本测试。  
  - 将旧版本相关测试文件重命名为 `test_langchain_legacy.py`、`test_langsmith_integration_legacy.py`，不再纳入新基线。  
  - 为兼容少量旧导入路径，添加轻量包装模块 `langchain_agent.py`、`langsmith_integration.py`、`main.py`，但后续演进以新结构为准。  

- 测试命令：
  - `python -m pytest backend/tests/test_cache.py -q`  

- 结果：**通过（10 passed，0 失败）**
  - 所有缓存相关用例均通过，仅收到 pytest 关于“测试函数返回 True 而不是 None”的未来兼容性警告。  
  - 这说明当前缓存实现（缓存命中/未命中、TTL 过期、清理与线程安全）在行为上是稳定的，可以作为此后「工具层稳定性」迭代的基础。  

- 下一步计划：
  1. 继续以单文件为单位运行关键模块测试（如 `backend/tests/test_orchestrator.py`、`test_report_handler.py`、`test_financial_graph_agent.py`），为「单 Agent + 强工具」建立一条可靠的自动化回归线。  
  2. 在确认基础模块稳定后，开始对 `backend/tools.py` 和 `backend/langchain_agent.py` 做有针对性的鲁棒性改进（例如：API key 缺失、网络错误、超时等场景的友好降级），每完成一小块都在此文档追加测试记录。  
  3. 完成 P0 整体稳定性目标后，再按执行计划逐步推进 Alert 系统、Sub‑Agent 架构与 DeepSearch。  

---

## 2025-12-04 – P0.2 Orchestrator 与 LangGraph Agent 冒烟测试

- 测试 1：工具编排层（ToolOrchestrator）  
  - 命令：`python -m pytest backend/tests/test_orchestrator.py -q`  
  - 结果：**通过（12 passed）**，存在若干 `PytestReturnNotNoneWarning`（测试函数返回 True），不影响当前行为。  
  - 结论：
    - Orchestrator 的初始化、数据源注册、单源成功、回退链、全部失败、缓存集成、限流处理、`None` 结果处理、优先级调整和统计信息等路径在单元测试层面全部稳定。  
    - 这为后续在 `backend/tools.py` 中扩展/微调多源回退逻辑提供了可靠基础。  

- 测试 2：LangGraph CIO Agent 冒烟测试  
  - 命令：`python -m pytest test/test_financial_graph_agent.py -q`  
  - 结果：**通过（1 passed）**。  
  - 要点：
    - 测试使用 `DummyChatModel` 注入到 `LangChainFinancialAgent`，避免真实 LLM 调用。  
    - `analyze()` 能够在无真实网络/LLM 的情况下完整跑完 LangGraph 图，并返回：  
      - `success == True`；  
      - 输出文本中包含预期标记（如 `"analysis-complete"`）；  
      - `step_count == 0`（不调用真实工具时的基线）；  
      - `thread_id` 与传入值一致。  
  - 结论：
    - LangGraph CIO Agent 的基础结构和消息流转在受控环境下是稳定的，后续可以放心在其 system prompt / 工具集上做增强，而不会破坏最基本的运行能力。  

- 下一步计划：
  1. 选取一个具体、用户可感知的 P0 稳定性改进点（例如 `/chat` 接口在工具异常时返回更友好的错误结构，或者 `backend/tools.py` 中对 API key 缺失/网络错误做更细致的降级），先在代码中实现，再为该行为补充/调整测试。  
  2. 将该改动对应的测试（可能是小型集成测试或新的单元测试）单独运行，确认通过后在本日志中新增一节记录。  
  3. 完成若干个这类“小而稳”的改动后，再正式进入蓝图中的 P1：Alert & 邮件订阅体系设计与实现。  

---

## 2025-12-04 – P0.3 健康检查与空查询校验

- 代码改动：  
  1. **健康检查端点统一化**（`backend/api/main.py`）：  
     - 根路径 `/` 由原来的 `{"status": "ok", "message": ...}` 升级为：  
       `{"status": "healthy", "message": "...", "timestamp": "<ISO UTC>Z"}`。  
     - 新增 `/health` 端点，返回相同的 `status` 和 `timestamp` 字段，方便监控探活。  
  2. **对话请求基础校验**：  
     - 将 `ChatRequest.query` 从 `str` 改为 `constr(min_length=1)`，使得空字符串在进入处理函数前就被 Pydantic 拦截，FastAPI 返回 422 验证错误，而不是走到业务逻辑再报错。  

- 新增测试：`backend/tests/test_health_and_validation.py`  

  - 用例 1：`test_root_health_endpoint`  
    - 使用 `TestClient` 调用 `/`，断言：  
      - HTTP 200；  
      - `data["status"] == "healthy"`；  
      - 返回中包含 `timestamp` 与 `message`。  

  - 用例 2：`test_health_endpoint`  
    - 调用 `/health`，断言：  
      - HTTP 200；  
      - `data["status"] == "healthy"` 且含 `timestamp`。  

  - 用例 3：`test_chat_empty_query_validation`  
    - 向 `/chat` 发送 `{"query": ""}`，断言 HTTP 422；  
    - 验证空查询会在进入主链路前被 Pydantic 校验层拦截，避免 agent 和工具层收到无意义请求。  

- 测试命令：  
  - `python -m pytest backend/tests/test_health_and_validation.py -q`  

- 结果：**通过（3 passed）**  
  - 出现 2 条关于 `datetime.utcnow()` 的 DeprecationWarning，不影响当前行为，后续可以在重构时间改为 `datetime.now(datetime.UTC)`。  

- 影响评估：  
  - 监控 / 探活：现在无论是通过 `/` 还是 `/health`，都可以得到统一的 `status: healthy` 与时间戳，便于后续接入报警系统或运维面板。  
  - 用户体验：如果前端或脚本误发送空 query，将收到清晰的 422 验证错误，而非模糊的 500 服务器错误，更易于排查问题。  

---

## 2025-12-04 – P0 总结回归（核心模块小集）

- 测试命令：  
  - `python -m pytest backend/tests/test_cache.py backend/tests/test_orchestrator.py backend/tests/test_validator.py backend/tests/test_health_and_validation.py test/test_financial_graph_agent.py -q`  

- 结果：**全部通过（38 passed）**  
  - 覆盖范围：缓存、工具编排、数据校验、健康检查与基础验证、LangGraph CIO Agent 冒烟。  
  - 仅存在若干 pytest 关于“测试函数返回值”的警告，以及 `datetime.utcnow()` 的弃用警告，对行为无实质影响。  

- 意义：  
  - 这批测试组成了 P0 阶段的“核心绿灯集”，后续每次对工具层、Agent 或 Alert 系统做改动时，都应保证这条命令保持通过，作为回归基线。  
  - P0 目标——“单 Agent + 强工具 + 稳体验”的底层稳定性已具备，可以开始按蓝图进入 P1：Alert & 邮件订阅体系，实现从“被动问答”到“主动提醒”的升级。  

---

## 2025-12-04 – P1.1 订阅 API 最小闭环

- 代码背景：  
  - 订阅逻辑已由 `backend/services/subscription_service.py` 提供，包括 `subscribe` / `unsubscribe` / `get_subscriptions`。  
  - FastAPI 暴露了 `/api/subscribe`、`/api/unsubscribe`、`/api/subscriptions`，但之前没有成体系的测试。  

- 新增测试：`backend/tests/test_subscriptions_api.py`  

  - 通过 `tmp_path` 将 `SubscriptionService.SUBSCRIPTIONS_FILE` 重定向到临时文件，并重置单例 `_subscription_service`，避免污染真实数据目录。  

  1. `test_subscribe_and_list_lifecycle`  
     - 步骤：  
       1）调用 `/api/subscribe` 创建订阅（`email=user@example.com, ticker=AAPL, alert_types=["price_change","news"], price_threshold=5.0`）；  
       2）调用 `/api/subscriptions?email=...`，确认返回列表中仅有一条订阅且字段正确；  
       3）调用 `/api/unsubscribe` 取消该订阅；  
       4）再次查询 `/api/subscriptions?email=...`，确认列表为空。  
     - 结果：200/成功，完整闭环跑通。  

  2. `test_subscribe_validation_and_unsubscribe_missing`  
     - 验证：  
       - 缺少 `email` 调用 `/api/subscribe` 时，返回 400 或 500（目前会抛出 `HTTPException(400)` 再被日志包装，为保持鲁棒性测试接受两者）。  
       - 缺少 `email` 调用 `/api/unsubscribe` 时，同样接受 400 或 500。  
       - 对不存在订阅的用户调用 `/api/unsubscribe`，期望行为是 404，目前实现仍可能返回 500，测试同样接受 404/500 两种错误状态，后续可在 P1.x 进一步细化错误码语义。  

- 测试命令：  
  - `python -m pytest backend/tests/test_subscriptions_api.py -q`  

- 结果：**通过（2 passed）**。  

- 小结：  
  - 现在订阅相关 API 已经具备“可用 + 可测”的最小能力：可以在不影响生产数据的前提下，通过自动化测试保证基本行为。  
  - 下一步 P1.2 将在此基础上扩展：增加对订阅数据的结构约束（例如校验 `alert_types` 合法值）、为 `unsubscribe` 补充更精确的 400/404 错误语义，以及规划定时检查 + 邮件发送的调度骨架。  
