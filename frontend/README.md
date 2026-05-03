# FinSight Frontend

FinSight frontend is a React + TypeScript + Vite application for the chat workspace, dashboard, workbench, execution timeline, RAG inspector, and report views.

## Runtime Role

The frontend owns interaction state and rendering:

- conversation list, new chat, switch chat, delete chat
- chat input state, stream abort button, loading states
- explicit user options such as `output_mode`
- ephemeral UI context such as `active_symbol`, selections, and portfolio panel context
- SSE parsing and user-facing execution timeline

The frontend does not own financial semantics:

- no company-name-to-ticker dictionary
- no macro/company/portfolio classifier
- no tool or agent selection
- no planner or research routing

Those decisions belong to the backend LangGraph request understanding layer. The target contract is documented in:

```text
../docs/plans/2026-05-03_request_understanding_task_graph_spec.md
```

Conversation boundary:

- frontend localStorage is the MVP source for message history and conversation summaries
- `/api/conversations` owns backend session lifecycle and cleanup
- deleting a conversation should call the backend API, then clear local persisted messages
- stop generation should keep partial content and cancelled thinking steps

## Main Files

- `src/components/ChatInput.tsx`: chat composer, output mode controls, streaming lifecycle.
- `src/components/layout/ChatWorkspace.tsx`: chat layout and conversation rail.
- `src/store/useStore.ts`: chat messages, session id, conversation summaries.
- `src/store/executionStore.ts`: SSE execution state, timeline, streamed content.
- `src/api/client.ts`: API client and SSE parser.
- `src/components/agent-log/`: raw event stream and agent pipeline views.
- `src/components/execution/`: user-facing execution progress and interrupt UI.

## Development

```bash
npm install
npm run dev
npm run build
npx vitest run src
npx playwright test e2e/request-understanding-chat.spec.ts
```

Playwright starts Vite on `127.0.0.1:4273` from `playwright.config.ts`.

For frontend behavior changes, verify with Playwright against the running app. Chat UX changes must cover:

- empty input and normal input states
- brief/deep mode selection
- stream abort
- new/switch/delete conversation
- SSE thinking events and final answer rendering
