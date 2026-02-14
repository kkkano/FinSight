# 2026-02-09 — LLM Retry/Rotation Hardening（401/503/timeout 即时切换）

## 背景与问题
- 线上现象：部分请求在某个 endpoint 返回 `401 无效令牌`、`503 无可用渠道` 或超时后，未在同请求内继续尝试其它 endpoint，导致直接失败或长时间卡住后降级。
- 根因：`backend/services/llm_retry.py` 原逻辑仅把 `429/quota` 判定为可重试，`llm_factory` 轮换也仅在该条件成立时触发。

## 目标
- 在多 endpoint 模式（传入 `llm_factory`）下，实现“失败立刻切下一个 endpoint”。
- 保持单 endpoint 兼容行为，不引入激进重试副作用。

## 实现变更

### 1) 重试判定扩展（`backend/services/llm_retry.py`）
- 新增 `_extract_http_status_code`：从异常文本提取 HTTP 状态码。
- 新增 `is_endpoint_retryable_error`：除 `429` 外，额外覆盖：
  - `401/403/404/408/429/5xx`
  - timeout/connection/SSL EOF 等传输错误
  - 常见上游错误文本（`无效的令牌`、`无可用渠道`、`该令牌额度已用尽`）

### 2) 轮换策略修正
- 当存在 `llm_factory` 时：
  - 使用 `is_endpoint_retryable_error` 决定是否继续重试。
  - 每次可重试失败立即创建新 LLM（轮换 endpoint）。
  - 轮换等待时间设为 `0`（即刻切换，避免多 endpoint 链路累计 sleep/jitter）。
- 当 `llm_factory` 不存在时：
  - 保持旧行为，仅 `rate-limit` 类重试。

## 测试与验收
- 新增/扩展用例（`backend/tests/test_llm_rotation.py`）：
  - `test_retry_rotates_endpoint_on_401_with_factory`
  - `test_retry_rotates_non_429_until_attempts_exhausted`
- 回归验证：
  - `pytest -q backend/tests/test_llm_rotation.py backend/tests/test_config_router_secret_merge.py`
  - 结果：`17 passed`

## 结果
- 同一请求内的 endpoint failover 已从“仅 429 触发”提升为“认证/渠道/瞬时故障均可触发”。
- 行为符合目标：坏节点快速跳过，优先命中可用节点；全部不可用时再走统一冷却/失败链路。

## 风险与后续
- 当前为字符串/状态码混合判定，后续可在 provider 适配层补充结构化错误码映射。
- 建议在 diagnostics 增加 `rotation_reason` 聚合维度，持续观察失败类型分布。
