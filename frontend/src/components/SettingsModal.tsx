import React, { useState, useEffect } from 'react';
import { X, Settings, Sun, Moon, Activity, CheckCircle, XCircle, RefreshCw, Plus, Trash2 } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface LlmEndpointConfig {
  name?: string;
  provider?: string;
  api_base?: string;
  api_key?: string;
  model?: string;
  weight?: number;
  enabled?: boolean;
  cooldown_sec?: number;
}

interface UserConfig {
  llm_provider?: string;
  llm_model?: string;
  llm_api_key?: string;
  llm_api_base?: string;
  llm_endpoints?: LlmEndpointConfig[];
  layout_mode?: 'centered' | 'full';
}

const DEFAULT_COOLDOWN_SEC = 90;

const createDefaultEndpoint = (): LlmEndpointConfig => ({
  name: '',
  provider: 'openai_compatible',
  api_base: '',
  api_key: '',
  model: '',
  weight: 1,
  enabled: true,
  cooldown_sec: DEFAULT_COOLDOWN_SEC,
});

const normalizeLoadedConfig = (input: UserConfig): UserConfig => {
  const baseConfig = input || {};
  const currentEndpoints = Array.isArray(baseConfig.llm_endpoints)
    ? baseConfig.llm_endpoints
    : [];

  if (currentEndpoints.length > 0) {
    return {
      ...baseConfig,
      llm_endpoints: currentEndpoints.map((item) => ({
        ...createDefaultEndpoint(),
        ...item,
        provider: item?.provider || 'openai_compatible',
        weight: Number(item?.weight || 1),
        enabled: item?.enabled !== false,
        cooldown_sec: Number(item?.cooldown_sec || DEFAULT_COOLDOWN_SEC),
      })),
    };
  }

  if ((baseConfig.llm_api_key || '').trim()) {
    return {
      ...baseConfig,
      llm_endpoints: [
        {
          ...createDefaultEndpoint(),
          name: 'legacy-single',
          provider: baseConfig.llm_provider || 'openai_compatible',
          api_base: baseConfig.llm_api_base || '',
          api_key: baseConfig.llm_api_key || '',
          model: baseConfig.llm_model || '',
          weight: 1,
          enabled: true,
          cooldown_sec: DEFAULT_COOLDOWN_SEC,
        },
      ],
    };
  }

  return {
    ...baseConfig,
    llm_endpoints: [],
  };
};

const sanitizeEndpointsForSave = (endpoints: LlmEndpointConfig[] | undefined): LlmEndpointConfig[] => {
  const rows = Array.isArray(endpoints) ? endpoints : [];
  return rows
    .map((endpoint, index) => {
      const apiKey = String(endpoint.api_key || '').trim();
      const apiBase = String(endpoint.api_base || '').trim();
      const model = String(endpoint.model || '').trim();
      const name = String(endpoint.name || '').trim();

      return {
        _hasKey: Boolean(apiKey),
        value: {
          name: name || `endpoint-${index + 1}`,
          provider: String(endpoint.provider || 'openai_compatible').trim() || 'openai_compatible',
          api_base: apiBase,
          api_key: apiKey,
          model,
          weight: Math.max(1, Number(endpoint.weight || 1)),
          enabled: endpoint.enabled !== false,
          cooldown_sec: Math.max(1, Number(endpoint.cooldown_sec || DEFAULT_COOLDOWN_SEC)),
        },
      };
    })
    .filter((item) => item._hasKey)
    .map((item) => item.value);
};

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [config, setConfig] = useState<UserConfig>({});
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  const {
    theme,
    setTheme,
    setLayoutMode,
    traceRawEnabled,
    setTraceRawEnabled,
    traceViewMode,
    setTraceViewMode,
    traceRawShowRawJson,
    setTraceRawShowRawJson,
  } = useStore();

  // Diagnostics State
  const [orchestratorStats, setOrchestratorStats] = useState<any>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [diagError, setDiagError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadConfig();
      loadDiagnostics();
    }
  }, [isOpen]);

  const loadConfig = async () => {
    try {
      const response = await apiClient.getConfig();
      if (response?.success) {
        setConfig(normalizeLoadedConfig(response.config || {}));
      }
    } catch (e) {
      console.error('加载配置失败:', e);
    }
  };

  const updateEndpoint = (index: number, patch: Partial<LlmEndpointConfig>) => {
    setConfig((prev) => {
      const next = [...(prev.llm_endpoints || [])];
      const current = next[index] || createDefaultEndpoint();
      next[index] = {
        ...current,
        ...patch,
      };
      return {
        ...prev,
        llm_endpoints: next,
      };
    });
  };

  const addEndpoint = () => {
    setConfig((prev) => ({
      ...prev,
      llm_endpoints: [...(prev.llm_endpoints || []), createDefaultEndpoint()],
    }));
  };

  const removeEndpoint = (index: number) => {
    setConfig((prev) => ({
      ...prev,
      llm_endpoints: (prev.llm_endpoints || []).filter((_, idx) => idx !== index),
    }));
  };

  const loadDiagnostics = async () => {
    setDiagLoading(true);
    setDiagError(null);
    try {
      const orchRes = await apiClient.diagnosticsOrchestrator().catch(() => null);
      setOrchestratorStats(orchRes);
    } catch {
      setDiagError('诊断加载失败');
    } finally {
      setDiagLoading(false);
    }
  };

  const handleChange = (key: keyof UserConfig, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
    if (key === 'layout_mode') {
      const mode = (value || 'centered') as 'centered' | 'full';
      setLayoutMode(mode);
    }
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      const normalizedEndpoints = sanitizeEndpointsForSave(config.llm_endpoints);
      const payload: UserConfig = {
        ...config,
        llm_endpoints: normalizedEndpoints,
      };
      if (normalizedEndpoints.length > 0) {
        const primary = normalizedEndpoints[0];
        payload.llm_provider = primary.provider;
        payload.llm_model = primary.model;
        payload.llm_api_base = primary.api_base;
        payload.llm_api_key = primary.api_key;
      }

      await apiClient.saveConfig(payload);
      setSaved(true);
      setTimeout(() => {
        setSaved(false);
        onClose();
      }, 1500);
    } catch (error) {
      console.error('保存配置失败:', error);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true" aria-labelledby="settings-modal-title">
      <div className="bg-fin-panel border border-fin-border rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-fin-border sticky top-0 bg-fin-panel z-10">
          <div className="flex items-center gap-2">
            <Settings size={20} className="text-fin-primary" />
            <h2 id="settings-modal-title" className="text-lg font-semibold text-fin-text">设置</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭设置"
            className="p-1 hover:bg-fin-border rounded transition-colors"
          >
            <X size={20} className="text-fin-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* LLM 配置 */}
          <section className="border border-fin-border rounded-lg p-4 bg-fin-bg/40">
            <h3 className="text-sm font-medium text-fin-text mb-3">LLM 配置（可选）</h3>
            <div className="grid md:grid-cols-2 gap-4 text-sm">
              <div>
                <label className="block text-xs text-fin-muted mb-1">提供商</label>
                <select
                  value={config.llm_provider || ''}
                  onChange={(e) => handleChange('llm_provider', e.target.value)}
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                >
                  <option value="">使用默认 (OpenAI-compatible)</option>
                  <option value="openai_compatible">OpenAI-compatible</option>
                  <option value="gemini_proxy">Gemini Proxy (Alias)</option>
                  <option value="openai">OpenAI</option>
                  <option value="anyscale">AnyScale</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="custom">自定义</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">自定义模型名称</label>
                <input
                  type="text"
                  value={config.llm_model || ''}
                  onChange={(e) => handleChange('llm_model', e.target.value)}
                  placeholder="如 gpt-4-turbo"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                />
              </div>
              <div className="md:col-span-2">
                <label className="block text-xs text-fin-muted mb-1">完整 API Endpoint (URL)</label>
                <input
                  type="text"
                  value={config.llm_api_base || ''}
                  onChange={(e) => handleChange('llm_api_base', e.target.value)}
                  placeholder="如 https://new.123nhh.xyz/v1/chat/completions"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none font-mono"
                />
              </div>
              <div className="md:col-span-2">
                <label className="block text-xs text-fin-muted mb-1">API Key</label>
                <input
                  type="password"
                  value={config.llm_api_key || ''}
                  onChange={(e) => handleChange('llm_api_key', e.target.value)}
                  placeholder="留空使用默认配置"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                />
              </div>
            </div>
          </section>

          {/* LLM 多 Endpoint 轮换 */}
          <section className="border border-fin-border rounded-lg p-4 bg-fin-bg/40" data-testid="settings-endpoints-section">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-fin-text">LLM Endpoints（轮换池）</h3>
              <button
                type="button"
                data-testid="settings-endpoint-add"
                onClick={addEndpoint}
                className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-fin-border text-fin-text hover:border-fin-primary/60"
              >
                <Plus size={12} /> 新增 Endpoint
              </button>
            </div>

            {(config.llm_endpoints || []).length === 0 ? (
              <p className="text-xs text-fin-muted">
                当前未配置轮换池。可新增多个 endpoint（API Base/API Key/Model/权重/冷却秒数）后统一保存。
              </p>
            ) : (
              <div className="space-y-3">
                {(config.llm_endpoints || []).map((endpoint, index) => (
                  <div
                    key={`endpoint-${index}`}
                    data-testid={`settings-endpoint-row-${index}`}
                    className="border border-fin-border rounded p-3 bg-fin-panel/40 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-fin-muted">Endpoint #{index + 1}</p>
                      <button
                        type="button"
                        data-testid={`settings-endpoint-remove-${index}`}
                        onClick={() => removeEndpoint(index)}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-red-500/40 text-red-400 hover:bg-red-500/10"
                      >
                        <Trash2 size={12} /> 删除
                      </button>
                    </div>

                    <div className="grid md:grid-cols-2 gap-3 text-sm">
                      <div>
                        <label className="block text-xs text-fin-muted mb-1">名称</label>
                        <input
                          type="text"
                          data-testid={`settings-endpoint-name-${index}`}
                          value={endpoint.name || ''}
                          onChange={(e) => updateEndpoint(index, { name: e.target.value })}
                          placeholder={`endpoint-${index + 1}`}
                          className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                        />
                      </div>

                      <div>
                        <label className="block text-xs text-fin-muted mb-1">Provider</label>
                        <select
                          data-testid={`settings-endpoint-provider-${index}`}
                          value={endpoint.provider || 'openai_compatible'}
                          onChange={(e) => updateEndpoint(index, { provider: e.target.value })}
                          className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                        >
                          <option value="openai_compatible">OpenAI-compatible</option>
                          <option value="gemini_proxy">Gemini Proxy (Alias)</option>
                          <option value="openai">OpenAI</option>
                          <option value="anyscale">AnyScale</option>
                          <option value="anthropic">Anthropic</option>
                        </select>
                      </div>

                      <div className="md:col-span-2">
                        <label className="block text-xs text-fin-muted mb-1">API Base</label>
                        <input
                          type="text"
                          data-testid={`settings-endpoint-api-base-${index}`}
                          value={endpoint.api_base || ''}
                          onChange={(e) => updateEndpoint(index, { api_base: e.target.value })}
                          placeholder="https://example.com/v1"
                          className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none font-mono"
                        />
                      </div>

                      <div>
                        <label className="block text-xs text-fin-muted mb-1">Model</label>
                        <input
                          type="text"
                          data-testid={`settings-endpoint-model-${index}`}
                          value={endpoint.model || ''}
                          onChange={(e) => updateEndpoint(index, { model: e.target.value })}
                          placeholder="gemini-2.5-flash"
                          className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                        />
                      </div>

                      <div>
                        <label className="block text-xs text-fin-muted mb-1">API Key</label>
                        <input
                          type="password"
                          data-testid={`settings-endpoint-api-key-${index}`}
                          value={endpoint.api_key || ''}
                          onChange={(e) => updateEndpoint(index, { api_key: e.target.value })}
                          placeholder="sk-***"
                          className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                        />
                      </div>

                      <div>
                        <label className="block text-xs text-fin-muted mb-1">权重</label>
                        <input
                          type="number"
                          min={1}
                          step={1}
                          data-testid={`settings-endpoint-weight-${index}`}
                          value={endpoint.weight ?? 1}
                          onChange={(e) => updateEndpoint(index, { weight: Number(e.target.value || 1) })}
                          className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                        />
                      </div>

                      <div>
                        <label className="block text-xs text-fin-muted mb-1">冷却秒数</label>
                        <input
                          type="number"
                          min={1}
                          step={1}
                          data-testid={`settings-endpoint-cooldown-${index}`}
                          value={endpoint.cooldown_sec ?? DEFAULT_COOLDOWN_SEC}
                          onChange={(e) => updateEndpoint(index, { cooldown_sec: Number(e.target.value || DEFAULT_COOLDOWN_SEC) })}
                          className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none"
                        />
                      </div>
                    </div>

                    <label className="inline-flex items-center gap-2 text-xs text-fin-muted cursor-pointer">
                      <input
                        type="checkbox"
                        data-testid={`settings-endpoint-enabled-${index}`}
                        checked={endpoint.enabled !== false}
                        onChange={(e) => updateEndpoint(index, { enabled: e.target.checked })}
                        className="accent-fin-primary"
                      />
                      Endpoint 启用
                    </label>
                  </div>
                ))}
              </div>
            )}

            <p className="text-xs text-fin-muted mt-3">
              保存时会写入 `llm_endpoints[]`。若有配置，首条 endpoint 会同时回填到 legacy 字段以保持兼容。
            </p>
          </section>

          {/* 界面布局 */}
          <section className="border border-fin-border rounded-lg p-4 bg-fin-bg/40">
            <h3 className="text-sm font-medium text-fin-text mb-3">界面布局</h3>
            <div className="flex gap-4 text-sm">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="layout"
                  checked={config.layout_mode !== 'full'}
                  onChange={() => handleChange('layout_mode', 'centered')}
                  className="accent-fin-primary"
                />
                <span className="text-fin-text">居中布局</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="layout"
                  checked={config.layout_mode === 'full'}
                  onChange={() => handleChange('layout_mode', 'full')}
                  className="accent-fin-primary"
                />
                <span className="text-fin-text">铺满宽度</span>
              </label>
            </div>
          </section>

          {/* 外观 */}
          <section className="border border-fin-border rounded-lg p-4 bg-fin-bg/40">
            <h3 className="text-sm font-medium text-fin-text mb-3">外观主题</h3>
            <div className="flex gap-4">
              <button
                onClick={() => setTheme('light')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm ${theme === 'light'
                  ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                  : 'border-fin-border text-fin-text hover:border-fin-primary/50'
                  }`}
              >
                <Sun size={16} /> 浅色
              </button>
              <button
                onClick={() => setTheme('dark')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm ${theme === 'dark'
                  ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                  : 'border-fin-border text-fin-text hover:border-fin-primary/50'
                  }`}
              >
                <Moon size={16} /> 深色
              </button>
            </div>
          </section>

          {/* Trace 可见性 */}
          <section className="border border-fin-border rounded-lg p-4 bg-fin-bg/40">
            <h3 className="text-sm font-medium text-fin-text mb-3">Trace 可见性</h3>
            <div className="grid md:grid-cols-2 gap-3 text-sm">
              <button
                type="button"
                data-testid="settings-trace-raw-toggle"
                onClick={() => setTraceRawEnabled(!traceRawEnabled)}
                className={`flex items-center justify-between px-3 py-2 rounded border transition-colors ${
                  traceRawEnabled
                    ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                    : 'border-fin-border text-fin-text hover:border-fin-primary/50'
                }`}
              >
                <span>Raw 事件采集</span>
                <span className="text-xs">{traceRawEnabled ? 'ON' : 'OFF'}</span>
              </button>

              <button
                type="button"
                data-testid="settings-trace-json-toggle"
                onClick={() => setTraceRawShowRawJson(!traceRawShowRawJson)}
                className={`flex items-center justify-between px-3 py-2 rounded border transition-colors ${
                  traceRawShowRawJson
                    ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                    : 'border-fin-border text-fin-text hover:border-fin-primary/50'
                }`}
              >
                <span>控制台显示 Raw JSON</span>
                <span className="text-xs">{traceRawShowRawJson ? 'ON' : 'OFF'}</span>
              </button>
            </div>
            <div className="mt-3">
              <div className="text-xs text-fin-muted mb-2">Trace 展示层级</div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  data-testid="settings-trace-view-user"
                  onClick={() => setTraceViewMode('user')}
                  className={`px-3 py-1.5 rounded border text-xs transition-colors ${
                    traceViewMode === 'user'
                      ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                      : 'border-fin-border text-fin-text hover:border-fin-primary/50'
                  }`}
                >
                  用户
                </button>
                <button
                  type="button"
                  data-testid="settings-trace-view-expert"
                  onClick={() => setTraceViewMode('expert')}
                  className={`px-3 py-1.5 rounded border text-xs transition-colors ${
                    traceViewMode === 'expert'
                      ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                      : 'border-fin-border text-fin-text hover:border-fin-primary/50'
                  }`}
                >
                  专家
                </button>
                <button
                  type="button"
                  data-testid="settings-trace-view-dev"
                  onClick={() => setTraceViewMode('dev')}
                  className={`px-3 py-1.5 rounded border text-xs transition-colors ${
                    traceViewMode === 'dev'
                      ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                      : 'border-fin-border text-fin-text hover:border-fin-primary/50'
                  }`}
                >
                  开发
                </button>
              </div>
            </div>
            <p className="text-xs text-fin-muted mt-2">
              默认开启。采集开关会随请求透传到后端，并即时影响当前会话。
            </p>
          </section>

          {/* 系统诊断 */}
          <section className="border border-fin-border rounded-lg p-4 bg-fin-bg/40">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-fin-text flex items-center gap-2">
                <Activity size={16} className="text-fin-primary" />
                系统状态 & 诊断
              </h3>
              <button
                onClick={loadDiagnostics}
                disabled={diagLoading}
                className="text-xs text-fin-muted hover:text-fin-primary flex items-center gap-1"
              >
                <RefreshCw size={12} className={diagLoading ? 'animate-spin' : ''} />
                刷新
              </button>
            </div>

            {diagError && <p className="text-xs text-red-400 mb-2">{diagError}</p>}

            <div className="grid md:grid-cols-2 gap-4 text-xs">
              {/* Orchestrator */}
              <div className="border border-fin-border rounded p-3 bg-fin-panel/60">
                <div className="font-medium text-fin-text mb-2 flex items-center gap-1">
                  {orchestratorStats?.status === 'ok' ? (
                    <CheckCircle size={12} className="text-green-400" />
                  ) : (
                    <XCircle size={12} className="text-red-400" />
                  )}
                  Orchestrator
                </div>
                {orchestratorStats?.data ? (
                  <div className="space-y-1 text-fin-muted">
                    {(() => {
                      const sources = orchestratorStats.data.by_source?.stock_price || [];
                      const totalCalls = sources.reduce((sum: number, s: any) => sum + (s.total_calls || 0), 0);
                      const totalSuccesses = sources.reduce((sum: number, s: any) => sum + (s.total_successes || 0), 0);
                      return (
                        <>
                          <div>总请求: {totalCalls}</div>
                          <div>成功: {totalSuccesses}</div>
                          <div>缓存命中: {orchestratorStats.data.orchestrator_stats?.cache_hits ?? 0}</div>
                          <div>回退次数: {orchestratorStats.data.orchestrator_stats?.fallback_count ?? 0}</div>
                          {sources.length > 0 && (
                            <div className="pt-1 border-t border-fin-border mt-1">
                              数据源: {sources.map((s: any) => `${s.name}(${s.total_calls})`).join(', ')}
                            </div>
                          )}
                        </>
                      );
                    })()}
                  </div>
                ) : (
                  <div className="text-fin-muted">无数据</div>
                )}
              </div>
            </div>
          </section>

          {/* 提示 */}
          <div className="p-3 bg-fin-bg border border-fin-border rounded text-xs text-fin-muted">
            💡 <strong>提示</strong>：所有配置项都是可选的。如果不填写，系统将使用后端默认配置。
            <br />
            API Key 仅存储在浏览器本地，不会上传到服务器。
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-4 border-t border-fin-border sticky bottom-0 bg-fin-panel">
          <button
            type="button"
            data-testid="settings-cancel-btn"
            onClick={onClose}
            className="px-4 py-2 text-sm text-fin-muted hover:text-fin-text transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={loading}
            className="px-4 py-2 bg-fin-primary text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center gap-2 transition-colors text-sm"
          >
            {saved ? '✓ 已保存' : loading ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
};



