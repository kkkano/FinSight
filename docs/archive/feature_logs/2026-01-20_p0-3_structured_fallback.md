# 2026-01-20 P0-3 News/Macro 回退结构化

## 目标
- 在回退路径中输出结构化字段，避免 raw 文本直接进入报告与 IR。

## 变更范围
- `backend/agents/macro_agent.py`
  - 回退返回 `indicators` 列表（占位结构）。
  - 回退摘要改为结构化说明，避免直接拼接 raw 文本。
  - 回退证据低置信度占位，避免空证据链。
- `backend/agents/news_agent.py`
  - 搜索回退补齐 `published_at`/`confidence` 字段。
  - EvidenceItem 传递 confidence。
- `backend/tests/test_deep_research.py`
  - 新增宏观回退结构化测试。

## 测试
- `pytest backend/tests/test_deep_research.py -q`

## 备注
- 该改动为后续 News 结构化改造（P1-1）提供可回滚的最小保障。
