import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AxiosError } from 'axios';
import type { AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';
import { apiClient } from './client';
import { api } from './http';
import { useModelSelectionStore } from '../store/modelSelection';
import type { ModelCapabilities, ModelSelection } from '../store/modelSelection';

const { adapter, authSession } = vi.hoisted(() => ({ adapter: vi.fn(), authSession: { available: true } }));

vi.mock('axios', async () => {
  const original = await vi.importActual<typeof import('axios')>('axios');
  return {
    ...original,
    default: {
      ...original.default,
      create: (config: AxiosRequestConfig) => original.default.create({ ...config, adapter }),
    },
  };
});

vi.mock('./supabaseClient', () => ({
  getSupabaseClient: () => ({ auth: { getSession: async () => ({ data: {
    session: authSession.available ? { access_token: 'test-auth-token' } : null,
  } }) } }),
}));

const metadata: ModelCapabilities = {
  provider: 'stepfun', label: 'Step 5 Preview', icon_url: null,
  effort_options: ['low', 'medium', 'high'], default_effort: 'medium', docs_url: null,
};
const custom: ModelSelection = {
  source: 'custom', base_url: 'https://api.example.com/v1', api_key: 'test-only-secret', model: 'custom-model',
  context_acknowledged: true,
};

function decodeHeader(value: string): unknown {
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(value), (character) => character.charCodeAt(0))));
}

beforeEach(() => {
  authSession.available = true;
  adapter.mockImplementation(async (config: InternalAxiosRequestConfig) => ({
    status: 200, statusText: 'OK', headers: {}, config, data: { models: [] },
  }));
  useModelSelectionStore.getState().clearSelection();
});

afterEach(() => {
  useModelSelectionStore.getState().clearSelection();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('model request headers', () => {
  it('preserves captured conversation authentication and cancellation through the API wrapper', async () => {
    const controller = new AbortController();
    await apiClient.createConversation('public:fixture:thread', { messages: [] }, {
      headers: { Authorization: 'Bearer captured-fixture-token' }, signal: controller.signal,
    });
    const config = adapter.mock.calls[0][0] as InternalAxiosRequestConfig;
    expect(config.headers.get('Authorization')).toBe('Bearer captured-fixture-token');
    expect(config.signal).toBe(controller.signal);
  });

  it('attaches the selected model only to generation requests while preserving authentication', async () => {
    useModelSelectionStore.getState().applySelection(custom, metadata);
    await api.post('/api/execute', { query: 'AAPL' });
    const config = adapter.mock.calls[0][0] as InternalAxiosRequestConfig;
    expect(decodeHeader(config.headers.get('X-FinSight-Model') as string)).toEqual(custom);
    expect(config.headers.get('Authorization')).toBe('Bearer test-auth-token');
  });

  it('does not send model credentials to health, config, history, portfolio or rebalance reads', async () => {
    useModelSelectionStore.getState().applySelection(custom, metadata);
    await api.get('/health');
    await api.get('/api/models');
    await apiClient.getConversation('fixture-session');
    await api.get('/api/watchlist');
    await api.get('/api/predictions/history');
    for (const [config] of adapter.mock.calls) {
      expect(config.headers.get('X-FinSight-Model')).toBeUndefined();
      expect(config.headers.get('Authorization')).toBe('Bearer test-auth-token');
    }
    expect(JSON.stringify(adapter.mock.calls)).not.toContain(custom.api_key);
  });

  it('does not attach a model override until a model is applied', async () => {
    await api.get('/api/models');
    expect(adapter.mock.calls[0][0].headers.get('X-FinSight-Model')).toBeUndefined();
  });

  it('keeps catalog, capability, and test calls independent of the active selection', async () => {
    useModelSelectionStore.getState().applySelection(custom, metadata);
    await apiClient.getModels();
    await apiClient.getModelCapabilities('step-5-preview', 'https://api.stepfun.com/step_plan/v1');
    await apiClient.testModel({ source: 'system', model_id: 'stepfun:step-5-preview', effort: 'medium' });
    for (const [config] of adapter.mock.calls) {
      expect(config.headers.get('X-FinSight-Model')).toBeUndefined();
      expect(config.headers.get('Authorization')).toBe('Bearer test-auth-token');
    }
    expect(JSON.parse(adapter.mock.calls[2][0].data)).toEqual({
      source: 'system', model_id: 'stepfun:step-5-preview', effort: 'medium',
    });
    expect(JSON.stringify(adapter.mock.calls)).not.toContain(custom.api_key);
  });

  it('includes the current selection and authentication on all three streaming calls', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('data: {"type":"done","response":"ok"}\n\n', {
      headers: { 'Content-Type': 'text/event-stream' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    useModelSelectionStore.getState().applySelection(custom, metadata);
    await apiClient.sendMessageStream({ query: 'hello' }, {});
    await apiClient.executeAgent({ query: 'hello' }, {});
    await apiClient.executeAgent({ query: 'hello' }, {}, { endpoint: '/api/execute/resume' });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const [, init] of fetchMock.mock.calls) {
      expect(decodeHeader(init.headers['X-FinSight-Model'])).toEqual(custom);
      expect(init.headers.Authorization).toBe('Bearer test-auth-token');
    }
  });

  it('uses the selected model for stock prediction generation but keeps run reads independent', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', { headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    useModelSelectionStore.getState().applySelection(custom, metadata);
    await apiClient.generatePrediction('AAPL');
    await apiClient.getPredictionRun('fixture-run');
    expect(decodeHeader(fetchMock.mock.calls[0][1].headers['X-FinSight-Model'])).toEqual(custom);
    expect(fetchMock.mock.calls[1][1].headers['X-FinSight-Model']).toBeUndefined();
  });

  it('rejects a failed model preflight before dispatching any streaming callbacks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'model_unavailable', message: 'Step 5 Preview 暂时不可用，请稍后重试。' },
    }), { status: 503, headers: { 'Content-Type': 'application/json' } })));
    const callbacks = { onDone: vi.fn(), onToken: vi.fn(), onThinking: vi.fn() };
    await expect(apiClient.sendMessageStream({ query: 'AAPL' }, callbacks)).rejects.toThrow('Step 5 Preview 暂时不可用');
    expect(callbacks.onDone).not.toHaveBeenCalled();
    expect(callbacks.onToken).not.toHaveBeenCalled();
    expect(callbacks.onThinking).not.toHaveBeenCalled();
  });

  it('requires login for an applied model without sending anonymous fallback requests, while data reads still work', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    useModelSelectionStore.getState().applySelection(custom, metadata);
    authSession.available = false;
    await expect(apiClient.sendMessageStream({ query: 'AAPL' }, {})).rejects.toThrow('登录状态已失效');
    await expect(apiClient.generatePrediction('AAPL')).rejects.toThrow('登录状态已失效');
    await expect(api.post('/api/execute', { query: 'AAPL' })).rejects.toThrow('登录状态已失效');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(adapter).not.toHaveBeenCalled();
    await api.get('/api/stock/price/AAPL');
    expect(adapter).toHaveBeenCalledTimes(1);
    expect(adapter.mock.calls[0][0].headers.get('X-FinSight-Model')).toBeUndefined();
  });

  it('removes model credentials from rejected Axios errors and logs', async () => {
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useModelSelectionStore.getState().applySelection(custom, metadata);
    adapter.mockImplementation(async (config: InternalAxiosRequestConfig) => {
      throw new AxiosError('Request failed', 'ERR_BAD_REQUEST', config, undefined, {
        config, status: 400, statusText: 'Bad Request', headers: {}, data: { detail: 'Invalid model' },
      });
    });

    await api.post('/api/execute', { query: 'AAPL' }).catch((error) => {
      expect(error.config.headers.get('X-FinSight-Model')).toBeUndefined();
      expect(error.response.config.headers.get('X-FinSight-Model')).toBeUndefined();
    });
    await apiClient.testModel(custom).catch((error) => {
      expect(error.config.data).toBe('[redacted]');
      expect(JSON.stringify(error)).not.toContain(custom.api_key);
    });
    expect(JSON.stringify(errorLog.mock.calls)).not.toContain(custom.api_key);
  });
});
