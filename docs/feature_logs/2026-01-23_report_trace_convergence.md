# 2026-01-23 Report + Trace + Convergence Fixes

## Summary
- Restored report routing for “analyze/分析” queries when a ticker is present.
- Sync report path now invokes Supervisor when no event loop is active.
- Supervisor stream normalizes agent/plan traces to TraceEvent v1.
- ReportSection now preserves section-level confidence/agent_name/data_sources.
- SearchConvergence applied to News/Macro fallback flows with trace metadata.

## Key Changes
| Area | Files | Notes |
| --- | --- | --- |
| Report routing | `backend/conversation/router.py` | Added analysis keyword rule for REPORT intent. |
| Supervisor sync path | `backend/conversation/agent.py` | Safe `asyncio.run` fallback for Supervisor. |
| Trace normalization | `backend/api/streaming.py` | Normalize agent_outputs + plan_trace to v1. |
| ReportIR sections | `backend/report/ir.py`, `backend/report/validator.py`, `frontend/src/types/index.ts` | Section metadata preserved. |
| News/Macro convergence | `backend/agents/news_agent.py`, `backend/agents/macro_agent.py` | Convergence metrics + trace event. |

## Tests
```
pytest backend/tests/test_chat_async_supervisor.py -q
pytest backend/tests/test_chat_supervisor_sync.py -q
pytest backend/tests/test_streaming_sse.py -q
pytest backend/tests/test_search_convergence.py -q
pytest backend/tests/test_report_validator.py -q
```

# P0/P1 报告生成与 Trace 修复 (2026-01-23)

## 完成状态: DONE

---

## P0: 报告内容缺失修复

### 问题
- `_parse_forum_sections()` 正则表达式只支持 `### 1.` 格式
- 使用 `result.response` 而非 `forum_output.consensus`

### 修复
| 文件 | 修改 |
|------|------|
| `supervisor_agent.py:1265-1300` | 支持多种标题格式 (###/##/**) |
| `supervisor_agent.py:1083-1085` | 优先使用 `forum_output.consensus` |

---

## P1: Trace 不完整修复

### 问题
- `process_stream()` 只有 4 个固定步骤
- Agent 执行详细 trace 未传递到前端

### 修复
| 文件 | 修改 |
|------|------|
| `supervisor_agent.py:1011-1042` | 添加 `agent_traces` 到 done 事件 |
| `supervisor_agent.py:1018-1030` | 将 Agent 执行步骤插入 thinking_steps |

---

## 测试结果
```
单元测试: 19/19 通过 (100%)
- test_trace_schema.py: 8/8
- test_search_convergence.py: 11/11
```
