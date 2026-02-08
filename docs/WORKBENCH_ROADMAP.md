# FinSight Workbench Development Roadmap

> Development plan for the Workbench view — the analyst's daily workspace.

---

## Current State (v0.8.0)

**File**: `frontend/src/pages/Workbench.tsx` (282 lines)

### Existing Features

| Section | Description | Status |
|---------|-------------|--------|
| **Latest Reports** | List of generated investment reports, click to view | ✅ Functional |
| **Market News** | Real-time news feed with ranking/raw toggle | ✅ Functional |
| **Ask About News** | Click news item → send to chat for analysis | ✅ Functional |
| **Today's Tasks** | Static task list placeholder | ⚠️ Hardcoded |

### Current Layout

```
┌─────────────────────────────────────────────┐
│ Workbench Header                            │
├──────────────────┬──────────────────────────┤
│ Latest Reports   │ Market News              │
│ - Report cards   │ - Ranked / Raw toggle    │
│ - Click to view  │ - "Ask about this" btn   │
│                  │                          │
├──────────────────┴──────────────────────────┤
│ Today's Tasks (static placeholder)          │
└─────────────────────────────────────────────┘
```

---

## Sprint 1: Core Enhancement

### 1.1 Report Filtering & Management

- [ ] Filter reports by ticker, tag, date range
- [ ] Sort by date, confidence score, subject type
- [ ] Batch operations: delete, archive, export
- [ ] Report status indicators (draft / final / outdated)

### 1.2 News Enhancement

- [ ] Batch mark as read / archive
- [ ] Category filters (earnings, macro, sector, breaking)
- [ ] Highlight keywords matching watchlist tickers
- [ ] News sentiment badge (positive / negative / neutral)

### 1.3 Dynamic Task Generation

Replace hardcoded tasks with intelligent suggestions:
- [ ] "Review pending alerts" (from watchlist triggers)
- [ ] "N unread news items for [ticker]"
- [ ] "Report for [ticker] is N days old — refresh?"
- [ ] "Market opens in X hours — check overnight moves"

### 1.4 Loading States

- [ ] Skeleton loading for report cards
- [ ] Skeleton loading for news items
- [ ] Empty state illustrations

---

## Sprint 2: Analysis Workspace

### 2.1 Quick Analysis Entry

- [ ] "Deep Analyze" button on news items → generate full investment report
- [ ] One-click report generation from watchlist ticker
- [ ] Template selector: brief / full report / comparison

### 2.2 Comparison View

- [ ] Select 2-3 news items for side-by-side comparison
- [ ] Report version diff (current vs previous for same ticker)
- [ ] Cross-ticker comparison matrix

### 2.3 Data Overlay

- [ ] Mini price chart inline with report cards
- [ ] Sparkline indicators for watchlist tickers
- [ ] Macro indicator dashboard widget

---

## Sprint 3: Productivity & Collaboration

### 3.1 Notes & Annotations

- [ ] Add personal notes to reports
- [ ] Highlight and annotate news items
- [ ] Note persistence (localStorage → backend)

### 3.2 Favorites & Collections

- [ ] Star/favorite reports and news items
- [ ] Create named collections (e.g., "Q4 Earnings Watch")
- [ ] Cross-session persistence

### 3.3 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Quick search across reports & news |
| `N` | Next news item |
| `P` | Previous news item |
| `R` | Refresh current view |
| `Ctrl+Enter` | Generate report for selected item |
| `Esc` | Close panel / modal |

### 3.4 Workspace Layout Customization

- [ ] Resizable panel sections
- [ ] Toggle section visibility
- [ ] Layout presets (analyst / trader / researcher)

---

## Sprint 4: Advanced Features (Future)

### 4.1 Alert Integration

- [ ] Price alert triggers displayed inline
- [ ] News alert badges on relevant tickers
- [ ] Alert history timeline

### 4.2 Export & Share

- [ ] Export report as PDF
- [ ] Export news digest as email
- [ ] Share analysis link (read-only)

### 4.3 Workflow Automation

- [ ] Scheduled report generation
- [ ] Auto-refresh stale reports
- [ ] Daily morning briefing generation

---

## Technical Considerations

### State Management

Current: Workbench data fetched on mount, not persisted.
Target: Dedicated Zustand slice for workbench state with localStorage persistence.

### API Dependencies

| Feature | Required API | Status |
|---------|-------------|--------|
| Reports | `GET /api/reports` | ✅ Exists |
| News | `GET /api/market/news` | ✅ Exists |
| Tasks | `GET /api/workbench/tasks` | ❌ Needs creation |
| Favorites | `POST /api/user/favorites` | ❌ Needs creation |
| Notes | `POST /api/user/notes` | ❌ Needs creation |

### Component Architecture

Target refactoring:
```
pages/Workbench.tsx (container)
├── components/workbench/ReportSection.tsx
├── components/workbench/NewsSection.tsx
├── components/workbench/TaskSection.tsx
├── components/workbench/QuickActions.tsx
└── hooks/useWorkbenchData.ts
```
