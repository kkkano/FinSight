# FinSight Design

## Source of truth

- Status: Draft, intended to become Active after the first Today/Ask usability review.
- Last refreshed: 2026-09-15
- Primary product surfaces: Today, Ask, Research, Portfolio, Library; `/ops/*` is an authenticated operations surface.
- Evidence reviewed: `frontend/src/App.tsx`, `frontend/src/components/Sidebar.tsx`, `frontend/src/components/layout/WorkspaceShell.tsx`, `frontend/src/pages/Workbench.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/welcome/WelcomePage.tsx`, `frontend/src/index.css`, `docs/01_ARCHITECTURE.md`, `docs/06a_LANGGRAPH_DESIGN_SPEC.md`, `docs/ux/IA_PROPOSAL_WORKBENCH.html`, `docs/design/` proposals, and the 2026-09-14 repository audit.
- Product premise: FinSight is a personalized financial research assistant for beginners and individual researchers. It helps a person find, organize, and understand public information; it does not trade or make decisions on the user's behalf.

## Brand

- Personality: calm, clear, trustworthy, curious, and human. The product should feel like a patient research companion rather than a trading terminal.
- Trust signals: source, publication time, retrieval time, freshness, uncertainty, opposing evidence, and a visible explanation of how a conclusion was formed.
- Avoid: terminal cosplay, unexplained agent jargon, blinking dashboards, fake live prices, unlabelled demo data, urgency language, and a wall of technical telemetry on the first screen.

## Product goals

- Goals:
  - Put relevant changes in front of the user before asking for a prompt.
  - Explain financial events in plain language while preserving professional evidence.
  - Remember user interests, preferences, and past judgments with explicit user control.
  - Let users move from a digest or event card into a focused question or deeper research run.
  - Make every important conclusion traceable to dated evidence and an explicit quality state.
- Non-goals:
  - Automated order execution, portfolio custody, or guaranteed buy/sell signals.
  - A millisecond trading terminal or institution-grade research replacement in the first release.
  - Adding agents merely to demonstrate multi-agent technology.
  - Silent rewriting of a user's historical judgment.
- Success signals:
  - A new user can find one relevant insight without first opening a chat.
  - A beginner can state what happened, why it matters, and the main risk after reading a card.
  - Users repeat less context, can correct memory, and can review how a judgment changed.
  - Evidence quality and response consistency improve without unbounded latency or token cost.

## Personas and jobs

- Primary persona: a financially interested beginner who follows a few companies or themes, has limited time, and does not understand many indicators or terms.
- Secondary persona: a technically capable individual researcher who wants source coverage, reproducibility, and a searchable research archive.
- Jobs:
  - “Tell me what changed since I last looked.”
  - “Explain this term or event as if I am new to finance.”
  - “Show me evidence for and against my previous view.”
  - “Remember what I care about, but let me inspect and change that memory.”
  - “Bring me important changes, then let me ask follow-up questions.”
- Key contexts: short mobile check-ins, a focused desktop research session, and occasional review of a past decision.

## Information architecture

- Primary navigation:
  1. Today — personalized digest, findings, pending reviews, and “since last visit”.
  2. Ask — one shared chat/composer for explanation, comparison, and follow-up research.
  3. Research — a company, theme, event, or judgment workspace with progressive detail.
  4. Portfolio — holdings, risk context, monitoring rules, and notification preferences.
  5. Library — reports, evidence, decision journal, and editable long-term memory.
- Operations navigation: `/ops/inspector`, `/ops/cost`, `/ops/traces`, `/ops/settings`; visible only to authorized roles.
- Core content hierarchy:
  1. What happened?
  2. Why is it relevant to this user?
  3. What supports or weakens the interpretation?
  4. What is uncertain or stale?
  5. What can the user do next (read, ask, save, mute, or review)?
- A report is an artifact inside Research or Library, not the default homepage layout.

## Design principles

1. Relevance before completeness: lead with the smallest useful explanation, then reveal detail.
2. Evidence before confidence: confidence without source, time, and uncertainty is not a trust signal.
3. User scope before thread scope: holdings, preferences, and memory belong to the person; messages and runs belong to a thread.
4. Progressive disclosure: hide implementation details until the user asks “how did you get this?”.
5. Explicit degradation: stale, partial, synthetic, cached, and failed states are visible and actionable.
6. Calm agency: the system may surface and challenge a view, but the user decides and can silence the system.
- Tradeoffs: the beginner surface may show fewer metrics than the existing terminal-style dashboard; expert evidence remains available in an expandable layer. A slower, well-grounded answer is preferred to a fast answer that hides missing data, but every run still has an explicit deadline and cancellation path.

## Visual language

- Color: light neutral surfaces by default, with one restrained indigo accent. Use semantic colors for positive, negative, warning, unknown, stale, and blocked states; never encode meaning by color alone.
- Typography: system sans-serif for prose, 14–16px body text, 20–32px page headings. Use a monospace face only for tickers, prices, timestamps, IDs, and raw diagnostics.
- Spacing/layout rhythm: 8px base scale; 16–24px card padding; content column capped at a readable width; avoid three simultaneous dense panels on narrow screens.
- Shape/radius/elevation: modest 10–14px radius, one border and one low shadow level. Avoid gradients and neon terminal decoration in user-facing views.
- Motion: short opacity/height transitions for disclosure; no motion for urgency. Honour `prefers-reduced-motion` and do not use animation to imply that a background process is still live.
- Imagery/iconography: use the existing logo and Lucide icons with text labels. Charts must carry units, time range, source, and as-of timestamp.

## Components

- Existing components to reuse: `Card`, `Badge`, `Button`, `Dialog`, `Input`, `ErrorBoundary`, report evidence cards, source trust badges, and the existing chart primitives after their state contracts are normalized.
- New/changed components:
  - `TodayDigest`, `FindingCard`, `WhyRelevant`, `EvidenceDrawer`, `FreshnessBadge`, `ResourceStateView`, `DecisionJournalCard`, `MemoryControlPanel`, `ResearchRunStatus`, and a shared `ResearchComposer`.
  - `WorkspaceShell` becomes a layout shell; it must not own remote fetching or domain-specific business rules.
- Variants and states: every remote card supports loading, ready, partial, empty, stale, degraded, error, and blocked states. Every action supports idle, pending, success, failure, and retry feedback.
- Token/component ownership: semantic tokens live in `frontend/src/index.css` (or a dedicated tokens module after migration). Feature folders may compose tokens but may not introduce a second `--bb-*` or page-local color system.

## Accessibility

- Target standard: WCAG 2.2 AA for primary flows.
- Keyboard/focus behavior: dialogs trap focus, close on Escape, restore focus to the opener, and expose labelled descriptions. Tabs implement roving focus, arrow-key navigation, `aria-controls`, and a matching `tabpanel`.
- Contrast/readability: normal text ≥4.5:1, large text ≥3:1; do not use the current low-contrast muted tokens for body copy. Minimum interactive target is 44×44px.
- Screen-reader semantics: headings follow document hierarchy; live run updates use a polite status region; charts have text summaries and table alternatives.
- Reduced motion and sensory considerations: disable ticker marquees and decorative loops under reduced motion; avoid flashing and auto-advancing content.

## Responsive behavior

- Supported breakpoints/devices: 375px, 768px, 1024px, and 1440px reference widths.
- Layout adaptations: mobile shows one primary content surface at a time; context, evidence, and run details open as sheets. Desktop may show a secondary context panel, but it must be collapsible.
- Touch/hover differences: no essential information is hover-only; source and status controls remain reachable by touch and keyboard.
- Performance: Today/Ask should not load charts, inspector, or cost modules until requested.

## Interaction states

- Loading: show what is being loaded and retain prior valid data when possible.
- Empty: explain why there is no content and provide one useful next action, such as adding a watch item or starting a research question.
- Error: state whether retry is safe, preserve user input, and avoid exposing stack traces or provider secrets.
- Success: confirm the durable effect, such as “已保存到资料库” or “提醒已关闭”.
- Disabled: explain the missing permission, data, or configuration instead of silently disabling a control.
- Offline/slow network: display stale data with its timestamp, pause polling, allow retry, and never invent completion.

## Content voice

- Tone: concise, respectful, plain Chinese by default; technical detail is available on demand.
- Terminology: translate or explain the first occurrence of every specialist term. Prefer “截至 10:30 的公开数据” over “live snapshot” and “可能性/依据不足” over unexplained confidence scores.
- Microcopy rules:
  - Separate “事实”“系统推断”“用户观点”“风险”“数据缺失”.
  - Never say “买入/卖出” as an imperative; use “可能值得进一步研究” and state uncertainty.
  - Every proactive notification explains relevance and offers mute/feedback controls.

## Implementation constraints

- Framework/styling system: React 19 + TypeScript + Vite, with the existing Tailwind setup consolidated to one version.
- Design-token constraints: one semantic token source; no page-local palette; no unlabelled static market values.
- Performance constraints: initial Today/Ask business JavaScript gzip ≤300KB; LCP <2.5s and INP <200ms on a representative mid-range mobile device.
- Compatibility constraints: preserve `/chat/supervisor`, `/chat/supervisor/stream`, report replay, and legacy URL redirects during migration; version new contracts.
- Test/screenshot expectations: unit tests for state reducers and formatting, Playwright flows at all four breakpoints, axe critical/serious violations at zero, and visual snapshots for Today, Ask, Research, Portfolio, and Library.

## Open questions

- [ ] First supported market set (US only, CN/HK only, or both) / product owner / affects source and calendar contracts.
- [ ] Retention and hosting policy for memory, decision journal, and raw evidence / owner / affects schema and privacy controls.
- [ ] Default proactive notification levels and quiet hours / owner / affects scheduler and onboarding.
- [ ] Minimum trusted source registry per market / research owner / affects quality gates.
- [ ] Threshold for automatic multi-agent escalation / engineering owner / affects budget and latency.
- [ ] Whether user-facing memory should be editable Markdown, structured forms, or both / UX owner / validate in prototype.
