# 2026-01-20 P2-1 DeepSearch 查询模板动态化

## 目标
- 根据查询意图自动生成更贴合的检索关键词，提升召回质量。

## 变更范围
- `backend/agents/deep_search_agent.py`
  - `_build_queries` 根据关键词动态拼接主题。
- `backend/tests/test_deep_research.py`
  - 新增动态查询模板单元测试。

## 测试
- `pytest backend/tests/test_deep_research.py -q`

## 备注
- 默认仍保留“investment thesis”兜底主题，避免空查询。
