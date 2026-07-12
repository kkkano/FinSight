# API Client 领域迁移地图

`frontend/src/api/client.ts` 原有 78 个方法已按后端契约边界迁入 11 个领域模块；兼容出口继续导出同名 `apiClient`，旧调用点无需改名。

| 领域模块 | 方法 |
|---|---|
| `chat.ts` | `sendMessage`、`createConversation`、`getConversation`、`patchConversation`、`deleteConversation`、`sendMessageStream`、`executeAgent`、`resumeExecution` |
| `reports.ts` | `listReportIndex`、`getReportReplay`、`setReportFavorite`、`checkPriceDrift`、`compareReports`、`exportPDF` |
| `portfolio.ts` | `getUserProfile`、`addWatchlist`、`removeWatchlist`、`getAgentPreferences`、`updateAgentPreferences`、`generateRebalanceSuggestion`、`listRebalanceSuggestions`、`patchRebalanceSuggestion`、`getPortfolioSummary`、`syncPortfolioPositions`、`updatePortfolioPosition`、`deletePortfolioPosition` |
| `monitor.ts` | `subscribe`、`unsubscribe`、`listSubscriptions`、`listAlertFeed`、`toggleSubscription`、`triggerMonitorScan`、`getMonitorTargets`、`createMonitorTarget`、`patchMonitorTarget`、`deleteMonitorTarget`、`getMonitorMacroCalendar`、`getMonitorSettings`、`updateMonitorSettings` |
| `dashboard.ts` | `getDailyTasks`、`generateMorningBrief`、`getDashboardInsights`、`getFindings`、`patchFindingStatus` |
| `market.ts` | `fetchKline`、`fetchStockPrice`、`addChartData`、`detectChartType`、`getChartData`、`getCNFundFlow`、`getCNNorthbound`、`getCNLimitBoard`、`getCNLhb`、`getCNConcept` |
| `screener.ts` | `runScreener`、`getScreenerFiltersMeta` |
| `backtest.ts` | `runBacktest`、`listBacktestStrategies` |
| `config.ts` | `getConfig`、`saveConfig` |
| `system.ts` | `getToolCapabilities`、`diagnosticsOrchestrator`、`healthCheck`、`getCostAudit`、`listSkills`、`listAgents` |
| `rag.ts` | `diagnosticsRagStatus`、`diagnosticsRagRuns`、`diagnosticsRagRunDetail`、`diagnosticsRagRunEvents`、`diagnosticsRagRunDocuments`、`diagnosticsRagRunChunks`、`diagnosticsRagRunHits`、`diagnosticsRagCollections`、`diagnosticsRagCollectionDocuments`、`diagnosticsRagCollectionChunks`、`diagnosticsRagDbBrowser`、`diagnosticsRagSearchPreview` |

公共层：

- `http.ts`：axios 实例、Supabase/dev token 鉴权、429 事件和流响应校验。
- `sse.ts`：SSE 解析、读超时、`withStreamGuards` 终态去重与空闲完成兜底。
- `contracts.ts`：跨领域请求/响应合同，并通过 `schema.d.ts` 绑定配置接口类型。
- `client.ts`：仅聚合领域对象并重导出公共合同。

`sendMessageStream` 已由 14 个位置参数改为 `(body, callbacks, opts)`；实际调用点为 `ChatInput`、`MiniChat` 和 SSE 限流测试，共 3 处，均已同步。
