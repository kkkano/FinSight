# Code Deletion Log

## [2026-02-25] P3-2 Dead Code Cleanup

### Unused Files Deleted

#### Tier 1: Directly orphaned (no importers)

| File | Lines | Reason |
|------|-------|--------|
| `src/components/right-panel/alertFeed.ts` | 89 | Exported types (`AlertFeedEvent`, `AlertFeedSource`) and functions (`reduceAlertFeedEvent`, `createPollingAlertFeedSource`) are never imported by any other file. The alert feed data is fetched directly via `apiClient.listAlertFeed` in `useRightPanelData.ts`. |
| `src/components/dashboard/DashboardWidgets.tsx` | 172 | Component `DashboardWidgets` is never imported or rendered. Dashboard v2 uses `StockHeader` + `MetricsBar` + `DashboardTabs` layout directly in `Dashboard.tsx`. |
| `src/components/dashboard/tabs/news/NewsFilterPills.tsx` | 45 | Component `NewsFilterPills` and type `NewsFilterType` are never imported. News filtering is handled internally by `NewsTab.tsx` and `NewsSubTabs.tsx`. |

#### Tier 2: Cascade orphaned (only importer was DashboardWidgets.tsx)

After deleting `DashboardWidgets.tsx`, these 9 files lost their sole consumer and became unreachable dead code. Verified by grep: zero `import` references remain in the codebase.

| File | Lines | Reason |
|------|-------|--------|
| `src/components/cards/SnapshotCard.tsx` | 223 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/cards/MarketChartCard.tsx` | 570 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/cards/RevenueTrendCard.tsx` | 104 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/cards/SegmentMixCard.tsx` | 102 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/cards/SectorWeightsCard.tsx` | 114 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/cards/TopConstituentsCard.tsx` | 91 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/cards/HoldingsCard.tsx` | 112 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/cards/MacroCard.tsx` | 58 | Only imported by deleted `DashboardWidgets.tsx`. |
| `src/components/dashboard/NewsFeed.tsx` | 322 | Only imported by deleted `DashboardWidgets.tsx`. |

#### Directory removed

| Directory | Reason |
|-----------|--------|
| `src/components/cards/` | All 8 files deleted; directory left empty. |

### Verification Method

For each file:
1. Searched all `.ts` and `.tsx` files for any `import` statement referencing the file
2. Searched for all exported symbol names across the entire `src/` directory
3. Confirmed zero references outside the file itself
4. Ran `npx tsc --noEmit` after each deletion batch -- zero errors both times

### Impact

- Files deleted: 12
- Directories removed: 1 (`src/components/cards/`)
- Lines of code removed: 2,002
- Dependencies removed: 0 (no npm packages affected)
- Bundle size reduction: estimated ~15-25 KB (12 unused component/module trees eliminated)

### Testing

- TypeScript compilation (`tsc --noEmit`): PASS (zero errors after all deletions)
- No imports broken: PASS (grep verified after each batch)
- Shared dependencies unaffected: `useExecuteAgent`, `useChartTheme`, `generateNewsId`, `useDashboardStore`, and all UI primitives remain referenced by other active files

### Items Investigated but Retained

| File | Reason for Keeping |
|------|-------------------|
| `src/hooks/usePortfolioPerformance.ts` | Used by `PortfolioPerformance.tsx` |
| `src/components/right-panel/types.ts` | Used by `RightPanel.tsx`, `useRightPanelData.ts`, and multiple sub-components |
| `src/components/right-panel/utils.ts` | Used by `RightPanel.tsx` |
| `src/config/breakpoints.ts` | Used by `useIsMobileLayout.ts` |
| All 15 hooks in `src/hooks/` | Each confirmed to have at least one external importer |
| All dashboard tab components | Active in current tab-based layout |

### Context

`DashboardWidgets.tsx` was a legacy "vertical scroll" container from Dashboard v1 that rendered all card widgets in a single column. Dashboard v2 replaced this with a tab-based layout (`DashboardTabs` -> `OverviewTab`, `FinancialTab`, `NewsTab`, etc.) where data is fetched and rendered per-tab. The v1 card components were never migrated into the v2 tabs and became orphaned dead code.
