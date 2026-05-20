# Sprint 2 Bugfix Batch — 2026-02-10

> 本轮修复覆盖 10+ 个 bug，涉及 LangGraph 节点逻辑、报告生成、新闻数据流、前端渲染和安全加固。

---

## 修复清单

### P0 — Critical

| # | 问题 | 根因 | 修复 | 文件 |
|---|------|------|------|------|
| 1 | Markdown 报告在前端无法渲染 prose 样式 | `@tailwindcss/typography` 插件从未安装，`prose` class 无效 | 安装插件 + 配置 `tailwind.config.js` | `frontend/tailwind.config.js` |
| 2 | `parse_operation` "ma" 子串误匹配 | `_match_any` 使用 `t in lowered`（子串包含），"ma" 匹配 "macro"/"market" 等 | 对 <=3 字符的 ASCII token 使用 `re.search(r"\b...\b")` 单词边界匹配 | `backend/graph/nodes/parse_operation.py:22-32` |
| 3 | `decide_output_mode` 正则 `\\b` 双重转义 | 原始字符串 `r"\\b(report)\\b"` 中 `\\b` 匹配字面反斜杠而非单词边界 | 改为 `r"\b(report)\b"` | `backend/graph/nodes/decide_output_mode.py:37` |
| 4 | `confidence='high'` 导致 `float()` 崩溃 | `float("high")` 抛出 ValueError，整个报告生成失败 | 新增 `_safe_confidence()` 辅助函数，try/except 兜底 | `backend/graph/report_builder.py:151-158,175` |
| 5 | 代词替换 "it"/"that" 破坏英文单词 | `"it" in "with"` 为 True，`replace("it", "AAPL")` 把 "with" 变成 "wAAPLh" | 中文代词保留子串替换，英文代词改用 `re.sub(r'\b...\b')` 单词边界 | `backend/conversation/context.py:516-543` |

### P0 — Agent & Report

| # | 问题 | 根因 | 修复 | 文件 |
|---|------|------|------|------|
| 6 | macro_agent / technical_agent 在 company 投资报告中不触发 | `required_agents_for_request()` 对 company 只要求 price+news+fundamental | 当 `output_mode == "investment_report"` 且 `subject_type == "company"` 时自动加入 macro_agent + technical_agent | `backend/graph/capability_registry.py:176-180` |
| 7 | 测试断言回归 `>= 2000` | 移除 report_builder 填充附录后，synthesis_report 字数降低到 300-600 | 断言从 `>= 2000` 改为 `>= 200` | `backend/tests/test_langgraph_api_stub.py:177` |

### P1 — News & Data

| # | 问题 | 根因 | 修复 | 文件 |
|---|------|------|------|------|
| 8 | 新闻动态 "暂无市场新闻" | `_parse_news_text()` 过于简陋，丢失 url/source/ts 元数据 | 完全重写，使用正则提取日期、markdown 链接、来源、摘要 | `backend/dashboard/data_service.py:460-510` |
| 9 | `_get_index_news()` NameError | 函数引用 `limit` 变量但未声明参数 | 添加 `limit: int = 5` 参数 + 调用方传入 `limit=limit` | `backend/tools/news.py:603,752` |

### P1 — Security & Frontend

| # | 问题 | 根因 | 修复 | 文件 |
|---|------|------|------|------|
| 10 | `WorkspaceShell` 健康检查 URL 硬编码 | `apiClient['baseUrl']` 永远是 undefined，回退到硬编码 `127.0.0.1:8000` | 改用 `API_BASE_URL` from config/runtime | `frontend/src/components/layout/WorkspaceShell.tsx:12,59` |
| 11 | chat_router 错误信息泄露 | HTTP endpoint 返回 `str(exc)` 给客户端 | 替换为通用 `"Internal server error"` + 服务端 `_logger.error()` | `backend/api/chat_router.py:104-106` |
| 12 | chat_router 无 response_time_ms | HTTP 响应缺少计时字段 | 添加 `_time.perf_counter()` 计时 + `response_time_ms` 字段 | `backend/api/chat_router.py:40,85,95` |
| 13 | report build 失败静默吞异常 | `except Exception: report = None` 无任何日志 | 添加 `_logger.warning(..., exc_info=True)` | `backend/api/chat_router.py:72-74,177-179` |

---

## 测试验证

- `pytest backend/tests/test_llm_rotation.py` — 13/13 PASSED
- `pytest backend/tests/test_capability_registry.py` — 4/4 PASSED
- `pytest backend/tests/test_report_builder_synthesis_report.py` — 5/5 PASSED
- `pytest backend/tests/test_config_router_secret_merge.py` — 4/4 PASSED
- `pytest backend/tests/test_report_index_migration_scripts.py` — 2/2 PASSED
- `npx tsc --noEmit` — 0 errors
- `npm run build` — Success (1.19s)

---

## 变更文件汇总

| 文件 | 操作 |
|------|------|
| `backend/graph/nodes/parse_operation.py` | 改: _match_any 短 token 单词边界 |
| `backend/graph/nodes/decide_output_mode.py` | 改: 正则 `\\b` → `\b` |
| `backend/graph/report_builder.py` | 改: +_safe_confidence, confidence float 防护 |
| `backend/conversation/context.py` | 改: 英文代词用 regex word boundary |
| `backend/graph/capability_registry.py` | 改: company investment_report 自动加 macro+technical |
| `backend/dashboard/data_service.py` | 改: 重写 _parse_news_text() |
| `backend/tools/news.py` | 改: _get_index_news +limit 参数 |
| `backend/api/chat_router.py` | 改: logging+timing+error sanitization |
| `frontend/tailwind.config.js` | 改: +@tailwindcss/typography 插件 |
| `frontend/src/components/layout/WorkspaceShell.tsx` | 改: apiClient→API_BASE_URL |
| `backend/tests/test_langgraph_api_stub.py` | 改: 断言 2000→200 |
| `backend/tests/test_capability_registry.py` | 改: 预期 5 agent required |
| `backend/tests/test_report_builder_synthesis_report.py` | 改: URL 在引用区允许 |
