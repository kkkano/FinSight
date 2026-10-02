export * from './contracts';
export { RATE_LIMIT_EVENT, rateLimitEvents } from './http';
export { parseSSEStream, withStreamGuards } from './sse';
export type { StreamOpts } from './sse';

import { chatApi } from './domains/chat';
import { reportsApi } from './domains/reports';
import { marketApi } from './domains/market';
import { predictionsApi } from './domains/predictions';
import { modelsApi } from './domains/models';
import { trackRecordApi } from './domains/trackRecord';

export const apiClient = {
  ...modelsApi,
  ...trackRecordApi,
  ...chatApi,
  ...reportsApi,
  ...marketApi,
  ...predictionsApi,
};
