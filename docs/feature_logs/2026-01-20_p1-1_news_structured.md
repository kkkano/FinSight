# 2026-01-20 P1-1 News 结构化改造

## 目标
- 将 `get_company_news` 改为结构化列表输出，并同步所有消费方。

## 变更范围
- `backend/tools.py`
  - `get_company_news` 与 `_get_index_news` 返回结构化列表。
  - 新增 `format_news_items` 与 `_build_search_news_items`。
- `backend/agents/news_agent.py`
  - 直接消费结构化列表，兼容旧字符串解析。
- `backend/handlers/report_handler.py`
  - 保存 `news_raw`，并格式化后注入报告 Prompt。
- `backend/handlers/chat_handler.py`
  - 回退新闻输出统一格式化展示。
- `backend/orchestration/supervisor_agent.py`
  - 新闻意图输出改为结构化格式化文本。
- `langchain_tools.py`
  - Tool 返回 JSON 字符串以保留结构化信息。
- `backend/tests/test_news_parsing.py`
  - 新增结构化解析与格式化测试。

## 测试
- `pytest backend/tests/test_news_parsing.py -q`

## 备注
- 结构化返回会影响旧的字符串消费逻辑，已在关键入口做格式化兜底。
