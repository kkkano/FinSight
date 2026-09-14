# FinSight Frontend

FinSight frontend is a React + TypeScript + Vite application for Today, Dashboard, Chat, History, Welcome, and read-only shared reports.

## Runtime Role

The frontend owns interaction state and rendering:

- Today summary rendering for authenticated watchlists and Prediction history
- conversation list, new chat, switch chat, delete chat
- chat input state, stream abort button, loading states
- explicit user options such as `output_mode`
- ephemeral UI context such as `active_symbol` and selections
- SSE parsing and user-facing execution timeline

The frontend does not own financial semantics:

- no company-name-to-ticker dictionary
- no macro/company/portfolio classifier
- no tool or agent selection
- no planner or research routing

Those decisions belong to the backend six-node LangGraph pipeline. Current contracts are documented in:

```text
../docs/01_ARCHITECTURE.md
../docs/LANGGRAPH_FLOW.md
../docs/execution-event-contract.md
```

Conversation boundary:

- frontend localStorage is a browser cache, while PostgreSQL-backed APIs own durable user data
- `/api/conversations` owns backend session lifecycle and cleanup
- all Chat and Report generation uses `POST /api/execute`; replay and cancellation use the matching run endpoints
- stopping generation keeps partial content and cancelled steps, driven by stream abort and backend cancellation events

Route and identity boundary:

- `/` redirects to `/today`, or to `/dashboard/:symbol` when a `symbol` query is present
- `/today` and `/dashboard/:symbol?` pass through the welcome gate; personal Today data still requires a real user identity
- `/chat` and `/history` require an authenticated Supabase user
- `/share/r/:token` is the public read-only report surface
- authenticated Playwright flows install a Supabase client contract fixture (`getSession` and `onAuthStateChange`); they do not forge application auth state in localStorage
- the contract fixture is deterministic browser integration coverage, while release canaries still use a real isolated Supabase user

## Main Files

- `src/components/ChatInput.tsx`: chat composer, report toggle, streaming lifecycle.
- `src/pages/TodayPage.tsx`: personalized summary and anonymous state.
- `src/components/layout/ChatWorkspace.tsx`: chat layout and conversation rail.
- `src/components/layout/WorkspaceShell.tsx`: shared navigation and workspace layout.
- `src/store/useStore.ts`: chat messages, session id, conversation summaries.
- `src/store/executionStore.ts`: SSE execution state, timeline, streamed content.
- `src/api/client.ts`: API client and SSE parser.
- `src/components/agent-log/`: raw event stream and agent pipeline views.
- `src/components/execution/`: user-facing execution progress and interrupt UI.

## Development

```bash
npm install
npm run dev
npm run lint
npm run test:unit
npm run build
npm audit --omit=dev
npx playwright test
```

The 2026-09-15 lockfile baseline has zero known production dependency vulnerabilities. A full audit still reports 17 development-only findings; these remain tracked and must not be described as a complete dependency clean bill.

Playwright starts Vite on `127.0.0.1:4273` from `playwright.config.ts`.

For frontend behavior changes, verify with Playwright against the running app. Chat UX changes must cover:

- empty input and normal input states
- default conversational chat payload (`output_mode=chat`)
- report toggle payload (`output_mode=investment_report`)
- stream abort
- new/switch/delete conversation
- SSE thinking events and final answer rendering
