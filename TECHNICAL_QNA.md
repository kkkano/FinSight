# TECHNICAL_QNA

以下问答基于当前源码（静态推演），用于帮助理解 FinSight 的核心链路与关键设计点。

## Q1：`/chat` 与 `/chat/stream` 的主要差异是什么？
**A：**`/chat` 是一次性响应，`/chat/stream` 走 SSE 流式输出。入口都在 `backend/api/main.py`，其中 `/chat/stream` 会将 token 按 `data: {json}\n\n` 推送到前端，模拟 ChatGPT 的逐字效果。

## Q2：SSE 是由哪块代码实现的？
**A：**SSE 主要由两部分组成：
1) `backend/api/main.py` 里的 `/chat/stream`，使用 `StreamingResponse` 返回 `text/event-stream`。
2) `backend/api/streaming.py` 的 `stream_report_sse` 与 `stream_supervisor_sse`，负责将内部事件转为 SSE 行。

## Q3：REPORT 流式输出走哪条链路？
**A：**优先走 `AgentSupervisor.analyze_stream`（多 Agent 聚合），入口在 `/chat/stream`，由 `stream_supervisor_sse` 转成 SSE。若无 Supervisor，则回退到 `report_agent.analyze_stream`。

## Q4：意图是如何识别的？为什么会误判？
**A：**核心逻辑在 `backend/conversation/router.py`。先跑规则快速匹配，再走 LLM 分类（若启用）。误判通常来自关键词覆盖不足或上下文缺失，因此会不断补充中文关键词与上下文提示。

## Q5：无 ticker 的报告请求如何处理？
**A：**REPORT 意图仍会进入 `ReportHandler.handle`，若无法解析 ticker 会返回澄清提示，要求用户提供股票代码/公司名/指数或 ETF。

## Q6：多 Agent 输出如何汇总为报告？
**A：**Supervisor 并行调用 Price/News/DeepSearch/Macro Agent，最后由 `ForumHost.synthesize` 汇总输出，再转成 ReportIR（结构化报告）。

## Q7：ReportIR 是什么？
**A：**ReportIR 是前端可渲染的结构化报告格式，包含 `summary`、`sections`、`confidence`、`risks` 等字段，主要在 `backend/handlers/report_handler.py` 里构建。

## Q8：上下文与指代消解怎么工作？
**A：**`ContextManager` 维护当前焦点 `current_focus`，`resolve_reference` 会把“它/这个”等指代替换为当前 ticker。`/chat/stream` 已补齐该步骤以保持一致性。

## Q9：如何扩展新的 Agent？
**A：**实现 `BaseFinancialAgent` 的 `research/analyze_stream`，再在 `AgentSupervisor` 注册即可。若需要流式输出，覆盖 `_stream_summary` 即可实现 token 级输出。

## Q10：如何验证流式是否真正生效？
**A：**前端会逐 token 接收 `data: {"type":"token","content":"..."}`。后端测试在 `backend/tests/test_streaming_sse.py` 和 `backend/tests/test_streaming_chat_followup.py`。
