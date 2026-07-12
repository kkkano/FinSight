# planner_stub 拆分迁移地图（WP3 Task 2 Step 1）

> 原文件：`backend/graph/nodes/planner_stub.py`（2509 行 = 模块头 33 行 + **单个 2475 行巨型函数**，
> 内含 41 个闭包共享 20 个捕获变量，`step_id` 经 nonlocal 自增）。
> 变换方式：tokenize 精确改写（字符串/注释免疫）——闭包提升为模块级函数，首参 `ctx: PlanContext`；
> 20 个捕获变量 → PlanContext 字段；主体对它们的读写全部 ctx 化（含 market/output_mode/subject/request_frames 的中途重绑定）。

## 捕获变量 → PlanContext 字段（20 个）

query / query_lower / output_mode / subject / tickers / primary_ticker / market / policy /
allowed_tools / allowed_agents / news_disallowed / requires_links / is_deep_financial_report /
ready_tasks / ready_tasks_by_id / ready_task_id_set / request_frames / steps / step_id（原 nonlocal 计数器）/ step_index（步骤去重索引）

## 闭包 → 目标文件（41 个 + 模块级 2 个）

- **steps.py**：_append_tool_step、_append_agent_step、_has_step（+ context.py 的 StepFactory 为 spec 契约薄封装）
- **util.py**：_contains_any、_qa_needs_live_context、_macro_query_for_task、_task_operation_params、
  _task_required_evidence、_task_id、_task_operation_name、_task_tickers、_task_urls、
  _plan_task_summary、_plan_subject_payload、_compare_has_current_support、_should_use_performance_compare、
  （模块级迁入）_sec_holdings_enabled、_holder_cik_or_name_from_query、_SEC_HOLDINGS_ENABLED_VALUES
- **builders/company.py**：_append_evidence_steps_for_ticker、_append_company_task_steps
- **builders/earnings.py**：_append_earnings_performance_steps、_append_earnings_impact_steps
- **builders/valuation.py**：_append_valuation_sanity_steps
- **builders/macro.py**：_append_macro_task_steps
- **builders/portfolio.py**：_append_portfolio_task_steps
- **builders/holdings.py**：_append_holdings_task_steps
- **builders/theme.py**：_append_theme_task_steps
- **builders/url_docs.py**：_append_document_task_steps
- **frames.py**：_frame_id/_frame_subject/_frame_subject_type/_frame_tickers/_frame_required_evidence/
  _frame_required_results/_frame_workflow_action/_frame_evidence_profile、_append_macro_frame_steps、
  _append_performance_comparison_frame_step、_append_backtest_frame_steps、_append_request_frame_steps、
  _request_frames_authoritatively_need_no_plan_steps
- **report_mode.py**：_append_report_mode_enrichment_steps
- **rule_planner.py**：TASK_BUILDERS 注册表、_append_understanding_task_steps（调度）、rule_based_planner（主体）

## TASK_BUILDERS 行为保真备注

- holdings 按 **operation 名**、URL 存在性两个前置守卫不进表（原分支顺序保留在调度函数内）
- 未登记 subject_type（unknown 等）= 原 elif 链落空 no-op；**spec 草表的 `"unknown": company.build_steps` 与现实行为不符，未采纳**
- 单任务路径与多任务循环共用同一张表（原两条链的类型→函数映射一致，互斥性由 dict 语义保证）

## 已知归档

- 原函数内 `_task_operation_params` 定义两次（:313 与 :782，后者遮蔽前者）；两版语义等价
  （operation.params 为 dict 则返回否则 {}），保留后者，前者丢弃。
- 原主体有两段 PlanIR 组装出口（contract-lane 早退 + 末尾主出口），非拆分引入的重复。
- trace 标签字符串（"type": "stub"、"fallback": "planner_stub"）**保持原样**（运行时可见工件，零行为变更优先于命名洁癖；WP3-T8 收尾时随 shim 删除一并评估）。
