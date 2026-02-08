# 2026-02-07｜补充需求同步：LLM多密钥轮换 + Raw Trace开关

## 背景

用户新增两项明确需求：

1. LLM 侧希望支持多组 `api_key + base_url` 轮询/故障切换；
2. Trace/Raw Event 希望提供开关控制（当前希望先全量可见，后续再默认关闭）。

同时用户确认当前“Gemini”实际通过第三方 OpenAI-compatible 接口调用，建议统一命名避免歧义。

## 本次文档变更

1. 更新 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
   - 在 `13.Worklog` 追加“11.14 补充（LLM 多密钥轮换 + Raw Trace 开关）”记录；
   - 在 `11.14.2 可观测性` 新增 Raw SSE/Trace 采集总开关与默认策略条目；
   - 在 `11.14.5 数据库与会话记忆` 新增：
     - OpenAI-compatible 多 endpoint 池化；
     - 密钥轮换（轮询/失败切换/冷却恢复/审计）；
     - provider 命名去歧义（`openai_compatible` 主命名，`gemini_proxy` 兼容别名）。

## 执行口径（确认）

- 你的当前偏好：先“全部可见”；后续再切默认关闭。
- 建议落地策略：
  - `dev`: Raw Trace 默认 `on`；
  - `prod`: Raw Trace 默认 `off`；
  - UI 提供会话级临时强制 `on`。

## 验收方式

- 人工核对：
  - `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（11.14.2 / 11.14.5 / 13.Worklog）
  - `docs/feature_logs/2026-02-07_llm_rotation_trace_switch_addendum.md`
