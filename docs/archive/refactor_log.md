# FinSight Refactor Log

## What changed
- Modernized the LangChain tool registry and agent to align with the current LangGraph patterns.
- Fixed the dark/light theme toggle, moved colors to CSS variables, and refreshed the front-end chrome.

## Backend — LangChain/LangGraph
- Reasoning (≈35 min): audited the old agent/tools, noted `create_agent` usage without graph control, missing tool typing, and difficult testability because of live LLM calls.
- Changes:
  - Rebuilt `backend/langchain_agent.py` with `StateGraph`, `ToolNode`, `tools_condition`, and a memory checkpointer; added prompt templating via `ChatPromptTemplate` and a clear system prompt.
  - Hardened callbacks and tool binding, plus a helper to coerce model outputs into graph state for safer custom LLM stubs.
  - Refreshed `langchain_tools.py` with typed Pydantic schemas, variable-safe imports, and consistent ASCII docs to keep tool wiring predictable.
  - Added `test/test_financial_graph_agent.py` using a dummy chat model so the graph can be smoke-tested without real API keys.
  - Added optional `llm` injection and `thread_id` handling for resumable runs.
  - Optimization ideas: plug in LangGraph checkpoints beyond in-memory when persistence is needed; add streaming inspectors for LangSmith once keys are available; consider a data-validation node before report generation.
- Test: `pytest test/test_financial_graph_agent.py` ✅

## Frontend — Theme fix & polish
- Reasoning (≈30 min): theme toggle failed because Tailwind colors were hard-coded per theme and classes never changed color tokens; some UI strings were garbled and TS build was failing.
- Changes:
  - Introduced CSS variables for all finance colors and swapped Tailwind palette to reference them; added light/dark tokens plus gradient/grain background.
  - Rebuilt theme handling in `useStore` with persistence (localStorage) and system preference fallback; fixed the toggle button copy and styling.
  - Cleaned `InlineChart` and `ThinkingProcess` components (English labels, safer chart logic), simplified charts, and fixed TS compile issues.
  - Added subtle UI accents (glow overlays, sharper buttons) without altering layout.
- Test: `npm run build` ✅ (note: Vite reports large bundle warning; consider chunking later if desired).

## Next suggestions
1) Add a LangGraph guardrail node to validate tool outputs (e.g., price × shares ≈ market cap) before report generation.  
2) Split the front-end bundle (lazy-load charts/settings) to quiet the size warning and improve first paint.  
3) Record theme preference server-side for multi-device consistency and add a “follow system” option.  
4) Add a thin integration test that exercises one real tool with a mock LLM to catch API regressions early.
