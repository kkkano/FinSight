# 2026-01-20 P1-2 DeepSearch SSRF 防护与重试

## 目标
- 深度抓取前增加 SSRF 校验，并统一 HTTP 重试策略，降低安全与稳定性风险。

## 变更范围
- `backend/agents/deep_search_agent.py`
  - 新增 `_is_safe_url` 规则与 DNS/IP 检查。
  - 引入 `requests.Session` + RetryAdapter。
  - 跳过不安全 URL/重定向。
- `backend/tests/test_deep_search_ssrf.py`
  - 覆盖常见 SSRF 场景的单元测试。

## 测试
- `pytest backend/tests/test_deep_search_ssrf.py -q`

## 备注
- SSRF 规则以“默认拒绝”策略为准，后续可按白名单放行特定域名。
