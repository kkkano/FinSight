export * from './contracts';
export { RATE_LIMIT_EVENT, rateLimitEvents } from './http';
export { parseSSEStream, withStreamGuards } from './sse';
export type { StreamOpts } from './sse';

import { chatApi } from './domains/chat';
import { reportsApi } from './domains/reports';
import { portfolioApi } from './domains/portfolio';
import { monitorApi } from './domains/monitor';
import { dashboardApi } from './domains/dashboard';
import { marketApi } from './domains/market';
import { screenerApi } from './domains/screener';
import { backtestApi } from './domains/backtest';
import { configApi } from './domains/config';
import { systemApi } from './domains/system';
import { ragApi } from './domains/rag';

export const apiClient = {
  ...chatApi,
  ...reportsApi,
  ...portfolioApi,
  ...monitorApi,
  ...dashboardApi,
  ...marketApi,
  ...screenerApi,
  ...backtestApi,
  ...configApi,
  ...systemApi,
  ...ragApi,
};
