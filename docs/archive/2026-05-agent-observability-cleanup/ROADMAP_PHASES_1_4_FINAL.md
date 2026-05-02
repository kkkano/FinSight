# FinSight Phase 1-4 最终执行看板（审计修正版）

更新时间：2026-03-01  
分支：`feat/roadmap-phase1-4`

---

## 0. 总览状态
- [x] Phase 1 已完成
- [x] Phase 2 已完成
- [x] Phase 3 已完成
- [x] Phase 4 已完成
- [x] 文档格式已切换为“执行看板 + 问题日志 + 验证证据”
- [x] 已补齐审计提出的 5 个缺口（①~⑤）

---

## 1. 全局钉死决策（固定）
- [x] `direction` 仅允许 `above|below`，不保留 `either`
- [x] ticker 提取优先级：`subject.tickers[0] > ui_context.active_symbol > None`
- [x] `alert_types` 合并责任在 `alert_action`，`subscribe()` 保持“传什么存什么”
- [x] `price_change_pct` 使用冷却窗口：`PRICE_ALERT_COOLDOWN_MINUTES`
- [x] `price_target` 使用一次性触发：`price_target_fired`
- [x] Phase 4 的 CN/HK 回测行情依赖 Phase 3 的 `fetch_cn_hk_kline`

---

## 2. Phase 1（对话式价格提醒闭环）

### 2.1 功能实施清单
- [x] `backend/api/schemas.py`：`ChatContext.user_email` + 订阅新字段
- [x] `backend/api/main.py`：`_build_ui_context()` 提取 `request.context.user_email`
- [x] `backend/graph/state.py`：增加 `user_email/alert_params/alert_valid`
- [x] `backend/graph/nodes/parse_operation.py`：增加 `alert_set`
- [x] 新建 `backend/graph/nodes/alert_extractor.py`
- [x] 新建 `backend/graph/nodes/alert_action.py`
- [x] `backend/graph/runner.py`：
  - [x] `parse_operation` 后改条件路由（`alert_set -> alert_extractor`）
  - [x] `alert_extractor -> alert_action` 条件路由
  - [x] `GraphRunner.ainvoke()` 注入 `state["user_email"]`
- [x] `backend/services/subscription_service.py`：
  - [x] 存储 `alert_mode/price_target/direction/price_target_fired`
  - [x] 新增 `set_price_target_fired(email, ticker)`
- [x] `backend/services/alert_scheduler.py`：
  - [x] `price_change_pct` 冷却窗口
  - [x] `price_target` 一次性触发
- [x] `backend/api/subscription_router.py` 透传新字段
- [x] `frontend/src/components/ChatInput.tsx` 注入 `context.user_email`
- [x] `frontend/src/components/MiniChat.tsx` 注入 `context.user_email`
- [x] `frontend/src/components/SubscribeModal.tsx` 支持 `%/到价`，移除 `either`

### 2.2 测试文件清单
- [x] `backend/tests/test_alert_intent.py`
- [x] `backend/tests/test_alert_extractor.py`
- [x] `backend/tests/test_alert_action.py`
- [x] 扩展 `backend/tests/test_alert_scheduler.py`
- [x] 回归 `backend/tests/test_graph_node_order.py`
- [x] 回归 `backend/tests/test_langgraph_skeleton.py`

### 2.3 验收场景覆盖确认（补齐审计点②）
- [x] 场景 A：有邮箱 + 到价 -> 落库 + 确认文案  
  对应：`test_alert_action_infers_direction_for_target_mode`
- [x] 场景 B：无邮箱 -> 不落库 + 提示  
  对应：`test_alert_action_requires_email`
- [x] 场景 C：已有 `news` -> merge 后 `news` 保留  
  对应：`test_alert_action_merges_alert_types_and_subscribes`
- [x] 场景 D：到价触发后不再重复  
  对应：`test_price_target_scheduler_triggers_once`
- [x] 场景 E：冷却窗口内不重复  
  对应：`test_price_change_scheduler_respects_cooldown`
- [x] 场景 F：无 ticker -> 返回澄清  
  对应：`test_alert_extractor_missing_ticker_returns_clarify`

---

## 3. Phase 2（智能选股 MVP）

### 3.1 后端
- [x] 新建 `backend/tools/screener.py`
- [x] 新建 `backend/api/screener_router.py`
- [x] `backend/langchain_tools.py` 注册 `screen_stocks`
- [x] `backend/tools/manifest.py` 增加 `screen` 选择
- [x] `backend/graph/nodes/parse_operation.py` 增加 `screen` 意图
- [x] `backend/graph/nodes/policy_gate.py` / `planner_stub.py` 增加 `screen` 路由
- [x] `backend/api/main.py` 挂载 `screener_router`

### 3.2 前端
- [x] 新建 `frontend/src/components/screener/ScreenerResultPanel.tsx`
- [x] 新增 `/phase-labs` 页面入口，挂载 Phase 2-4 面板

### 3.3 能力边界（补齐审计点④）
- [x] `screen_stocks` 响应增加 `capability_note`（CN/HK 覆盖边界提示）
- [x] 前端面板显示 `capability_note` 提示文案

### 3.4 测试
- [x] `backend/tests/test_screener_tool.py`
- [x] `backend/tests/test_screener_router.py`
- [x] `backend/tests/test_parse_operation_screen.py`
- [x] `frontend/e2e/screener.spec.ts`

---

## 4. Phase 3（A股市场扩展）

### 4.1 后端
- [x] 新建 `backend/tools/cn_market_flow.py`
- [x] 新建 `backend/tools/cn_market_board.py`
- [x] 新建 `backend/tools/concept_map.py`
- [x] 新建 `backend/api/cn_market_router.py`
- [x] `backend/langchain_tools.py` 注册 CN 市场工具
- [x] `backend/tools/manifest.py` 增加 `cn_market` 选择
- [x] `backend/graph/nodes/parse_operation.py` 增加 `cn_market` 意图
- [x] `backend/graph/nodes/policy_gate.py` / `planner_stub.py` 增加 `cn_market` 路由
- [x] `backend/api/main.py` 挂载 `cn_market_router`

### 4.2 前端
- [x] 新建 `frontend/src/components/cn-market/CNMarketPanel.tsx`
- [x] `/phase-labs` 可访问

### 4.3 测试
- [x] `backend/tests/test_cn_market_flow.py`
- [x] `backend/tests/test_cn_market_board.py`
- [x] `backend/tests/test_cn_market_router.py`
- [x] `backend/tests/test_parse_operation_cn_market.py`
- [x] `frontend/e2e/cn-market-tab.spec.ts`

---

## 5. Phase 4（策略回测）

### 5.1 后端
- [x] 新建 `backend/services/backtest_strategies.py`
- [x] 新建 `backend/services/backtest_engine.py`
- [x] 新建 `backend/api/backtest_router.py`
- [x] `backend/langchain_tools.py` 注册 `run_strategy_backtest`
- [x] `backend/tools/manifest.py` 增加 `backtest` 选择
- [x] `backend/graph/nodes/parse_operation.py` 增加 `backtest` 意图
- [x] `backend/graph/nodes/policy_gate.py` / `planner_stub.py` 增加 `backtest` 路由
- [x] `backend/api/main.py` 挂载 `backtest_router`

### 5.2 前端
- [x] 新建 `frontend/src/components/backtest/BacktestPanel.tsx`
- [x] `/phase-labs` 可访问

### 5.3 合规项覆盖（补齐审计点⑤）
- [x] 无未来函数（look-ahead）：`t_plus_one` 下使用前一 bar 信号  
  对应：`test_backtest_engine_t_plus_one_uses_previous_bar_signal`
- [x] 交易成本/滑点参数化对收益有可验证差异  
  对应：`test_backtest_engine_cost_and_slippage_reduce_final_equity`
- [x] A股 T+1：买卖不允许同日往返平仓  
  对应：`test_backtest_engine_t_plus_one_prevents_same_day_round_trip`

### 5.4 测试
- [x] `backend/tests/test_backtest_engine.py`
- [x] `backend/tests/test_backtest_router.py`
- [x] `backend/tests/test_parse_operation_backtest.py`
- [x] `frontend/e2e/backtest.spec.ts`

---

## 6. parse_operation 最终优先级（补齐审计点③）
最终顺序（高 -> 低）：

`compare > analyze_impact > backtest > alert_set > screen > cn_market > technical > price > summarize > extract_metrics > fetch > morning_brief > multi_ticker_default_compare > qa`

说明：`backtest` 已前移，避免被 `technical`（如 MACD/RSI 关键词）截胡。

---

## 7. 文档与配置同步项（补齐审计点①）
- [x] `.env.example` 增加 `PRICE_ALERT_COOLDOWN_MINUTES=60`
- [x] `.env.server.example` 增加 `PRICE_ALERT_COOLDOWN_MINUTES=60`
- [x] `docs/DEPLOYMENT.md` 增加提醒调度参数与开关说明
- [x] `AGENTS.md` 增加 Phase 1-4 新模块职责与依赖记录

---

## 8. 问题日志
1. `backtest MACD` 被误判为 `technical`  
   处理：`backtest` 分支前移；新增回归测试。
2. `alert_scheduler.py` 曾有语法损坏（f-string/注释污染）  
   处理：修复并通过回归。
3. `test_langgraph_skeleton.py` 历史编码/语法损坏  
   处理：重写为稳定 UTF-8 版本。
4. `execute_plan_stub.py` 曾触发重模型加载影响测试稳定性  
   处理：`RAG_ENABLE_RERANKER` 改为显式开关（默认关闭）。

---

## 9. 验证证据

### 9.1 Phase 2-4 + 分流回归
```bash
pytest -q backend/tests/test_screener_tool.py backend/tests/test_screener_router.py backend/tests/test_parse_operation_screen.py backend/tests/test_cn_market_flow.py backend/tests/test_cn_market_board.py backend/tests/test_cn_market_router.py backend/tests/test_parse_operation_cn_market.py backend/tests/test_backtest_engine.py backend/tests/test_backtest_router.py backend/tests/test_parse_operation_backtest.py backend/tests/test_parse_operation.py backend/tests/test_tool_manifest.py
```
结果：`32 passed`

### 9.2 Phase 1 回归
```bash
pytest -q backend/tests/test_alert_intent.py backend/tests/test_alert_extractor.py backend/tests/test_alert_action.py backend/tests/test_alert_scheduler.py backend/tests/test_graph_node_order.py backend/tests/test_langgraph_skeleton.py
```
结果：`26 passed`

### 9.3 语法与构建
```bash
python -m py_compile backend/tools/screener.py backend/api/screener_router.py backend/tools/cn_market_flow.py backend/tools/cn_market_board.py backend/tools/concept_map.py backend/api/cn_market_router.py backend/services/backtest_strategies.py backend/services/backtest_engine.py backend/api/backtest_router.py backend/graph/nodes/parse_operation.py backend/graph/nodes/alert_extractor.py backend/graph/nodes/alert_action.py
npm run build
npm run test:e2e -- e2e/screener.spec.ts e2e/cn-market-tab.spec.ts e2e/backtest.spec.ts
```
结果：`py_compile 通过`，`build 通过`，`e2e 3 passed`

---

## 10. 里程碑状态
- [x] M1：Phase 1 提醒闭环验收完成
- [x] M2：Phase 2 选股 MVP 完成
- [x] M3：Phase 3 A股市场扩展完成
- [x] M4：Phase 4 回测能力完成

结论：当前文档已可作为发布前核查依据（执行项、风险项、证据项齐全）。
