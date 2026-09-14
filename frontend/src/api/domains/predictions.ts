import { buildApiUrl } from '../../config/runtime';
import type { components } from '../schema';
import { buildAuthHeaders } from '../http';

export type GeneratePredictionResponse = components['schemas']['GeneratePredictionResponse'];
export type PredictionHistoryItem = components['schemas']['PredictionHistoryItem'];
export type PredictionHistoryResponse = components['schemas']['PredictionHistoryResponse'];
export type PredictionOutcomeView = components['schemas']['PredictionOutcomeView'];
export type PredictionResponse = components['schemas']['PredictionResponse'];
export type PredictionRunView = components['schemas']['PredictionRunView'];
export type PredictionStatBucket = components['schemas']['PredictionStatBucket'];
export type PredictionStatsResponse = components['schemas']['PredictionStatsResponse'];
export type PredictionView = components['schemas']['PredictionView'];

export type PredictionFailure = {
  code: string;
  message: string;
  status: number | null;
};

export type LatestPredictionApiResult =
  | { status: 'ready'; payload: PredictionResponse }
  | { status: 'not_found' };

const FAILURE_MESSAGES: Record<string, string> = {
  auth_required: '登录后才能生成和查看 AI 判断。',
  market_data_unavailable: '当前标的缺少可信 K 线，AI 判断未生成。',
  llm_timeout: 'AI 分析超过时间预算，请稍后重试。',
  llm_authentication_failed: 'AI 服务认证配置异常，请联系管理员。',
  llm_quota_exceeded: 'AI 调用额度已用完，请稍后再试。',
  llm_policy_rejected: '本次请求被 AI 安全策略拒绝。',
  prediction_validation_failed: 'AI 返回内容未通过 Prediction 合同校验。',
  prediction_not_found: '未找到这条 AI 判断。',
  prediction_run_not_found: '未找到这次生成任务。',
  store_unavailable: 'Prediction 存储服务暂时不可用。',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function describePredictionFailure(
  code: string | null | undefined,
  detail?: string | null,
  status: number | null = null,
): PredictionFailure {
  const normalizedCode = String(code || '').trim() || 'prediction_unavailable';
  const knownMessage = FAILURE_MESSAGES[normalizedCode];
  const safeDetail = String(detail || '').trim();
  return {
    code: normalizedCode,
    message: knownMessage || safeDetail || 'AI 判断暂时无法完成，请稍后重试。',
    status,
  };
}

export class PredictionApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(failure: PredictionFailure & { status: number }) {
    super(failure.message);
    this.name = 'PredictionApiError';
    this.code = failure.code;
    this.status = failure.status;
  }
}

export function toPredictionFailure(error: unknown): PredictionFailure {
  if (error instanceof PredictionApiError) {
    return { code: error.code, message: error.message, status: error.status };
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return { code: 'request_cancelled', message: '请求已取消。', status: null };
  }
  return describePredictionFailure(
    'prediction_unavailable',
    error instanceof Error ? error.message : null,
  );
}

async function parseErrorResponse(response: Response): Promise<PredictionApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const detail = isRecord(payload) ? payload.detail : null;
  const detailRecord = isRecord(detail) ? detail : null;
  const code = String(detailRecord?.code || '').trim()
    || (response.status === 401 ? 'auth_required' : 'prediction_unavailable');
  const message = typeof detailRecord?.message === 'string'
    ? detailRecord.message
    : typeof detail === 'string'
      ? detail
      : null;
  const failure = describePredictionFailure(code, message, response.status);
  return new PredictionApiError({ ...failure, status: response.status });
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const authHeaders = await buildAuthHeaders();
  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...authHeaders,
      ...init.headers,
    },
  });
  if (!response.ok) throw await parseErrorResponse(response);
  return response.json() as Promise<T>;
}

function appendQuery(path: string, params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && String(value).trim() !== '') query.set(key, String(value));
  }
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export const predictionsApi = {
  async generatePrediction(
    symbol: string,
    signal?: AbortSignal,
  ): Promise<GeneratePredictionResponse> {
    return requestJson('/api/predictions/generate', {
      method: 'POST',
      body: JSON.stringify({ symbol, timeframe: '1d' }),
      signal,
    });
  },

  async getPredictionRun(runId: string, signal?: AbortSignal): Promise<PredictionRunView> {
    const payload = await requestJson<{ run: PredictionRunView }>(
      `/api/predictions/runs/${encodeURIComponent(runId)}`,
      { signal },
    );
    return payload.run;
  },

  async getPrediction(predictionId: string, signal?: AbortSignal): Promise<PredictionResponse> {
    return requestJson(
      `/api/predictions/${encodeURIComponent(predictionId)}`,
      { signal },
    );
  },

  async getLatestPrediction(symbol: string, signal?: AbortSignal): Promise<LatestPredictionApiResult> {
    const payload = await requestJson<PredictionResponse>(
      appendQuery('/api/predictions/latest', { symbol }),
      { signal },
    );
    return payload.prediction
      ? { status: 'ready', payload }
      : { status: 'not_found' };
  },

  async getPredictionHistory(
    params: {
      symbol?: string;
      direction?: 'long' | 'short' | 'neutral';
      limit?: number;
      offset?: number;
    } = {},
    signal?: AbortSignal,
  ): Promise<PredictionHistoryResponse> {
    return requestJson(
      appendQuery('/api/predictions/history', {
        symbol: params.symbol,
        direction: params.direction,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      }),
      { signal },
    );
  },

  async getPredictionStats(
    params: { symbol?: string; days?: number } = {},
    signal?: AbortSignal,
  ): Promise<PredictionStatsResponse> {
    return requestJson(
      appendQuery('/api/predictions/stats', {
        symbol: params.symbol,
        days: params.days ?? 90,
      }),
      { signal },
    );
  },
};
