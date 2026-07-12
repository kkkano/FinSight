# synthesize 拆分迁移地图（WP3 Task 4）

> 原文件：`backend/graph/nodes/synthesize.py`（3202 行）。两块手术：
> ① `_stub_render_vars`（724-1941，1218 行 / 22 闭包 / 11 数据捕获）→ `backend/graph/render_vars/` 包；
> ② claim 验证五函数（372-560）→ `backend/report/verifier.py`。

## 结构事实与适配（对应 spec 偏差）

spec 草图假设 `vars["xxx"] = …` 键累积器 + 板块合并；**实际是 subject_type 分支树**，
每支直接 `return RenderVars(...).model_dump()`：

- news_item/news_set（479-496）
- macro（497-569）
- company（570-1188，含报告模式 _build_* 家族 8 闭包）
- filing/research_doc（1189-1207）
- unknown 兜底（1208-1216）

→ 适配为 **T2 同款 ctx 化闭包提升**：`RenderVarsCtx`（19 字段）承载捕获集，
主体分支树逐字搬运进 `render_vars/__init__.build_render_vars`（spec 接口名保留）。

## 对拍基准（spec Step 2 的落地形态）

- 冻结副本：`backend/tests/fixtures/render_vars_legacy.py`（原函数逐字节复制 + 宿主符号回接 import，仅测试用）
- 守护测试：`backend/tests/test_render_vars_keys.py` —— 6 条金样 query 的**完整图终态**上
  `build_render_vars(state) == _stub_render_vars_legacy(state)` 键集+逐键相等
  （覆盖 company/macro/news/doc/unknown 分支；multi_question 覆盖混合任务态）
- spec 说"拆完删除 legacy 副本"→ 副本保留在 tests/fixtures（非生产代码），T8 收尾评估删除

## 文件映射

- **render_vars/model.py**：RenderVars（类从 synthesize 迁出解环，宿主 import 回接）
- **render_vars/context.py**：RenderVarsCtx
- **render_vars/access.py**：_get_tool_output、_get_agent_output
- **render_vars/price.py**：_extract_price_behavior_snapshot、_fmt_price_claims、
  _fmt_price_snapshot_from_structured_data、_fmt_price_agent_output、_fmt_price_snapshot
- **render_vars/technical.py**：_fmt_technical_snapshot
- **render_vars/news.py**：_fmt_company_news_summary
- **render_vars/macro.py**：_fmt_macro_tool
- **render_vars/compare.py**：_parse_comparison_table、_find_row_for_ticker、_parse_pct
- **render_vars/report_agents.py**：_collect_conflict_disclosure + _build_{conclusion,investment_summary,
  investment_thesis,company_overview,catalysts,valuation,risks}_from_agents
- **render_vars/__init__.py**：build_render_vars（ctx init + 分支树主体）
- **report/verifier.py**：_normalize_verifier_claims、_apply_verifier_redactions、
  _contains_claim_after_redaction、_compute_unresolved_unsupported_claims、_run_deep_report_verifier

## 已知归档

- synthesize.py 保留 `_stub_render_vars` 一行委托（旧名调用方/测试不破，T8 删）。
- verifier 与 synthesize 共享的 helper（_normalize_for_match/_env_*/_extract_json_object/
  _is_deep_research_run/_HALLUCINATION_* 常量等）**留在 synthesize**（其余代码仍在用），
  verifier 经 `_synth()` 延迟解析取用——import 期破环、调用期取真身；物理归位 T8 评估。
- `backend.graph.__init__` 饿加载 runner：任何外部包首触 backend.graph.* 都会拉起全图 →
  verifier 的 GraphState 注解走 TYPE_CHECKING。
- spec "synthesize ≤900 行" 未达（现 1785）：剩余主体 = synthesize() 主函数 + _generate_narrative_draft
  （spec 明示保留）+ morning_brief + 共享 helper，无进一步拆分锚点，不臆拆。
- render_vars/report_agents.py 482 行小幅超限（8 个同族 builder，内聚优先不再切）。
