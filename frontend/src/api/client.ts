export * from './contracts';
export { RATE_LIMIT_EVENT, rateLimitEvents } from './http';
export { parseSSEStream, withStreamGuards } from './sse';
export type { StreamOpts } from './sse';

import { chatApi } from './domains/chat';
import { reportsApi } from './domains/reports';
import { marketApi } from './domains/market';
import { predictionsApi } from './domains/predictions';

export const apiClient = {
  ...chatApi,
  ...reportsApi,
  ...marketApi,
  ...predictionsApi,
};
