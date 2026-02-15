import React, { useState, useEffect } from 'react';
import { X, Settings, Sun, Moon, Activity, CheckCircle, XCircle, RefreshCw, Plus, Trash2, Eye, EyeOff } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
// 共享 UI 组件
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { Card } from './ui/Card';
import { AgentControlPanel } from './settings/AgentControlPanel';

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

const isMaskedSecret = (value: string): boolean => {
  const raw = String(value || '').trim();
  if (!raw) return false;
  return raw.includes('***') || /^\*+$/.test(raw);
};

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

const PRIMARY_ENDPOINT_NAME = 'legacy-single';

const ensurePrimaryEndpoint = (
  endpoints: LlmEndpointConfig[],
  base?: Partial<UserConfig>,
): { endpoints: LlmEndpointConfig[]; index: number } => {
  const rows = Array.isArray(endpoints) ? [...endpoints] : [];
  let idx = rows.findIndex((item) => String(item?.name || '').trim() === PRIMARY_ENDPOINT_NAME);

  if (idx < 0) {
    rows.unshift({
      ...createDefaultEndpoint(),
      name: PRIMARY_ENDPOINT_NAME,
      provider: String(base?.llm_provider || 'openai_compatible').trim() || 'openai_compatible',
      api_base: String(base?.llm_api_base || '').trim(),
      api_key: String(base?.llm_api_key || '').trim(),
      model: String(base?.llm_model || '').trim(),
      enabled: true,
    });
    idx = 0;
  }

  return { endpoints: rows, index: idx };
};

const resolvePrimaryEndpointIndex = (endpoints: LlmEndpointConfig[]): number => {
  const rows = Array.isArray(endpoints) ? endpoints : [];
  if (rows.length === 0) return -1;
  const enabledIdx = rows.findIndex((item) => item?.enabled !== false);
  return enabledIdx >= 0 ? enabledIdx : 0;
};

const normalizeLoadedConfig = (input: UserConfig): UserConfig => {
  const baseConfig = input || {};
  const currentEndpoints = Array.isArray(baseConfig.llm_endpoints)
    ? baseConfig.llm_endpoints
    : [];

  const primaryEndpoint =
    currentEndpoints.find((item) => String(item?.name || '').trim() === PRIMARY_ENDPOINT_NAME) ||
    currentEndpoints.find((item) => item?.enabled !== false) ||
    currentEndpoints[0];
  const mergedLegacy = primaryEndpoint
    ? {
        llm_provider: primaryEndpoint.provider || baseConfig.llm_provider,
        llm_model: primaryEndpoint.model || baseConfig.llm_model,
        llm_api_base: primaryEndpoint.api_base || baseConfig.llm_api_base,
      }
    : {
        llm_provider: baseConfig.llm_provider,
        llm_model: baseConfig.llm_model,
        llm_api_base: baseConfig.llm_api_base,
      };

  if (currentEndpoints.length > 0) {
    return {
      ...baseConfig,
      ...mergedLegacy,
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
      ...mergedLegacy,
      llm_endpoints: [
        {
          ...createDefaultEndpoint(),
          name: PRIMARY_ENDPOINT_NAME,
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
    ...mergedLegacy,
    llm_endpoints: [],
  };
};

const sanitizeEndpointsForSave = (endpoints: LlmEndpointConfig[] | undefined): LlmEndpointConfig[] => {
  const rows = Array.isArray(endpoints) ? endpoints : [];
  return rows
    .map((endpoint, index) => {
      const apiKeyRaw = String(endpoint.api_key || '').trim();
      const apiKey = isMaskedSecret(apiKeyRaw) ? '' : apiKeyRaw;
      const apiBase = String(endpoint.api_base || '').trim();
      const model = String(endpoint.model || '').trim();
      const name = String(endpoint.name || '').trim();

      return {
        _hasPersistableConfig: Boolean(apiKey || apiKeyRaw || apiBase || model || name),
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
    .filter((item) => item._hasPersistableConfig)
    .map((item) => item.value);
};

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [config, setConfig] = useState<UserConfig>({});
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showLegacyApiKey, setShowLegacyApiKey] = useState(false);
  const [showEndpointApiKeys, setShowEndpointApiKeys] = useState<Record<number, boolean>>({});

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

      const primaryByName = next.findIndex((item) => String(item?.name || '').trim() === PRIMARY_ENDPOINT_NAME);
      const primaryIdx = primaryByName >= 0 ? primaryByName : resolvePrimaryEndpointIndex(next);
      const primary = primaryIdx >= 0 ? next[primaryIdx] : undefined;
      return {
        ...prev,
        llm_provider: primary?.provider || prev.llm_provider,
        llm_model: primary?.model || prev.llm_model,
        llm_api_base: primary?.api_base || prev.llm_api_base,
        llm_api_key: primary?.api_key || prev.llm_api_key,
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
    setShowEndpointApiKeys((prev) => {
      const next: Record<number, boolean> = {};
      Object.keys(prev).forEach((key) => {
        const idx = Number(key);
        if (Number.isNaN(idx) || idx === index) return;
        const nextIdx = idx > index ? idx - 1 : idx;
        next[nextIdx] = prev[idx];
      });
      return next;
    });
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
    setConfig((prev) => {
      const nextState: UserConfig = { ...prev, [key]: value };

      if (key === 'llm_provider' || key === 'llm_model' || key === 'llm_api_base' || key === 'llm_api_key') {
        const ensured = ensurePrimaryEndpoint(prev.llm_endpoints || [], prev);
        const endpoints = ensured.endpoints;
        const primaryIdx = ensured.index;
        if (primaryIdx >= 0) {
          const current = endpoints[primaryIdx] || createDefaultEndpoint();
          const nextPrimary: LlmEndpointConfig = {
            ...current,
            name: PRIMARY_ENDPOINT_NAME,
            enabled: true,
          };
          if (key === 'llm_provider') nextPrimary.provider = value;
          if (key === 'llm_model') nextPrimary.model = value;
          if (key === 'llm_api_base') nextPrimary.api_base = value;
          if (key === 'llm_api_key') nextPrimary.api_key = value;
          endpoints[primaryIdx] = nextPrimary;
        }

        nextState.llm_endpoints = endpoints;
      }

      return nextState;
    });

    if (key === 'layout_mode') {
      const mode = (value || 'centered') as 'centered' | 'full';
      setLayoutMode(mode);
    }
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      const legacyProvider = String(config.llm_provider || '').trim();
      const legacyModel = String(config.llm_model || '').trim();
      const legacyApiBase = String(config.llm_api_base || '').trim();
      const legacyApiKeyRaw = String(config.llm_api_key || '').trim();
      const legacyApiKey = isMaskedSecret(legacyApiKeyRaw) ? '' : legacyApiKeyRaw;

      const ensured = ensurePrimaryEndpoint(config.llm_endpoints || [], config);
      const endpointsWithPrimary = [...ensured.endpoints];
      const currentPrimary = endpointsWithPrimary[ensured.index] || createDefaultEndpoint();
      endpointsWithPrimary[ensured.index] = {
        ...currentPrimary,
        name: PRIMARY_ENDPOINT_NAME,
        provider: legacyProvider || String(currentPrimary.provider || '').trim() || 'openai_compatible',
        api_base: legacyApiBase || String(currentPrimary.api_base || '').trim(),
        api_key: legacyApiKey || String(currentPrimary.api_key || '').trim(),
        model: legacyModel || String(currentPrimary.model || '').trim(),
        enabled: true,
      };

      const normalizedEndpoints = sanitizeEndpointsForSave(endpointsWithPrimary);

      const payload: UserConfig = {
        ...config,
        llm_endpoints: normalizedEndpoints,
        llm_provider: legacyProvider || 'openai_compatible',
        llm_model: legacyModel,
        llm_api_base: legacyApiBase,
        llm_api_key: legacyApiKey,
      };

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
          {/* 关闭按钮 — 使用共享 Button ghost 变体 */}
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="关闭设置"
            className="p-1"
          >
            <X size={20} className="text-fin-muted" />
          </Button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* LLM 配置 — 使用共享 Card 组件 */}
          <Card className="p-4 bg-fin-bg/40">
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
              {/* 自定义模型名称 — 使用共享 Input 组件 */}
              <Input
                label="自定义模型名称"
                type="text"
                value={config.llm_model || ''}
                onChange={(e) => handleChange('llm_model', e.target.value)}
                placeholder="如 gpt-4-turbo"
                className="py-2 rounded"
              />
              {/* API Endpoint — 使用共享 Input 组件 */}
              <div className="md:col-span-2">
                <Input
                  label="完整 API Endpoint (URL)"
                  type="text"
                  value={config.llm_api_base || ''}
                  onChange={(e) => handleChange('llm_api_base', e.target.value)}
                  placeholder="如 https://new.123nhh.xyz/v1/chat/completions"
                  className="py-2 rounded font-mono"
                />
              </div>
              {/* API Key — 使用共享 Input 组件 */}
              <div className="md:col-span-2">
                <label className="block text-xs text-fin-muted mb-1">API Key</label>
                <div className="relative">
                  <input
                    type={showLegacyApiKey ? 'text' : 'password'}
                    value={config.llm_api_key || ''}
                    onChange={(e) => handleChange('llm_api_key', e.target.value)}
                    placeholder="留空使用默认配置"
                    className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 pr-10 text-fin-text text-sm focus:border-fin-primary outline-none"
                  />
                  <button
                    type="button"
                    aria-label={showLegacyApiKey ? '隐藏 API Key' : '显示 API Key'}
                    onClick={() => setShowLegacyApiKey((v) => !v)}
                    className="absolute inset-y-0 right-2 flex items-center text-fin-muted hover:text-fin-primary"
                  >
                    {showLegacyApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>
          </Card>

          {/* LLM 多 Endpoint 轮换 — 使用共享 Card 组件 */}
          <Card className="p-4 bg-fin-bg/40" data-testid="settings-endpoints-section">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-fin-text">LLM Endpoints（轮换池）</h3>
              {/* 新增 Endpoint 按钮 — 使用共享 Button secondary 变体 */}
              <Button
                size="sm"
                data-testid="settings-endpoint-add"
                onClick={addEndpoint}
              >
                <Plus size={12} /> 新增 Endpoint
              </Button>
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
                      {/* 删除 Endpoint 按钮 — 使用共享 Button danger 变体 */}
                      <Button
                        variant="danger"
                        size="sm"
                        data-testid={`settings-endpoint-remove-${index}`}
                        onClick={() => removeEndpoint(index)}
                      >
                        <Trash2 size={12} /> 删除
                      </Button>
                    </div>

                    <div className="grid md:grid-cols-2 gap-3 text-sm">
                      {/* 名称 — 使用共享 Input 组件 */}
                      <Input
                        label="名称"
                        type="text"
                        data-testid={`settings-endpoint-name-${index}`}
                        value={endpoint.name || ''}
                        onChange={(e) => updateEndpoint(index, { name: e.target.value })}
                        placeholder={`endpoint-${index + 1}`}
                        className="py-2 rounded"
                      />

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

                      {/* API Base — 使用共享 Input 组件 */}
                      <div className="md:col-span-2">
                        <Input
                          label="API Base"
                          type="text"
                          data-testid={`settings-endpoint-api-base-${index}`}
                          value={endpoint.api_base || ''}
                          onChange={(e) => updateEndpoint(index, { api_base: e.target.value })}
                          placeholder="https://example.com/v1"
                          className="py-2 rounded font-mono"
                        />
                      </div>

                      {/* Model — 使用共享 Input 组件 */}
                      <Input
                        label="Model"
                        type="text"
                        data-testid={`settings-endpoint-model-${index}`}
                        value={endpoint.model || ''}
                        onChange={(e) => updateEndpoint(index, { model: e.target.value })}
                        placeholder="gemini-2.5-flash"
                        className="py-2 rounded"
                      />

                      {/* API Key — 使用共享 Input 组件 */}
                      <div>
                        <label className="block text-xs text-fin-muted mb-1">API Key</label>
                        <div className="relative">
                          <input
                            type={showEndpointApiKeys[index] ? 'text' : 'password'}
                            data-testid={`settings-endpoint-api-key-${index}`}
                            value={endpoint.api_key || ''}
                            onChange={(e) => updateEndpoint(index, { api_key: e.target.value })}
                            placeholder="sk-***"
                            className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 pr-10 text-fin-text text-sm focus:border-fin-primary outline-none"
                          />
                          <button
                            type="button"
                            aria-label={showEndpointApiKeys[index] ? '隐藏 Endpoint API Key' : '显示 Endpoint API Key'}
                            onClick={() =>
                              setShowEndpointApiKeys((prev) => ({
                                ...prev,
                                [index]: !prev[index],
                              }))
                            }
                            className="absolute inset-y-0 right-2 flex items-center text-fin-muted hover:text-fin-primary"
                          >
                            {showEndpointApiKeys[index] ? <EyeOff size={16} /> : <Eye size={16} />}
                          </button>
                        </div>
                      </div>

                      {/* 权重 — 使用共享 Input 组件 */}
                      <Input
                        label="权重"
                        type="number"
                        min={1}
                        step={1}
                        data-testid={`settings-endpoint-weight-${index}`}
                        value={endpoint.weight ?? 1}
                        onChange={(e) => updateEndpoint(index, { weight: Number(e.target.value || 1) })}
                        className="py-2 rounded"
                      />

                      {/* 冷却秒数 — 使用共享 Input 组件 */}
                      <Input
                        label="冷却秒数"
                        type="number"
                        min={1}
                        step={1}
                        data-testid={`settings-endpoint-cooldown-${index}`}
                        value={endpoint.cooldown_sec ?? DEFAULT_COOLDOWN_SEC}
                        onChange={(e) => updateEndpoint(index, { cooldown_sec: Number(e.target.value || DEFAULT_COOLDOWN_SEC) })}
                        className="py-2 rounded"
                      />
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
              保存时会写入 `llm_endpoints[]`。主用 endpoint（优先启用中的第一个）会同步回填到 legacy 字段以保持兼容。
            </p>
          </Card>

          {/* Agent 控制面板 */}
          <AgentControlPanel />

          {/* 界面布局 — 使用共享 Card 组件 */}
          <Card className="p-4 bg-fin-bg/40">
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
          </Card>

          {/* 外观 — 使用共享 Card 组件 */}
          <Card className="p-4 bg-fin-bg/40">
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
          </Card>

          {/* Trace 可见性 — 使用共享 Card 组件 */}
          <Card className="p-4 bg-fin-bg/40">
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
          </Card>

          {/* 系统诊断 — 使用共享 Card 组件 */}
          <Card className="p-4 bg-fin-bg/40">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-fin-text flex items-center gap-2">
                <Activity size={16} className="text-fin-primary" />
                系统状态 & 诊断
              </h3>
              {/* 刷新按钮 — 使用共享 Button ghost 变体 */}
              <Button
                variant="ghost"
                size="sm"
                onClick={loadDiagnostics}
                disabled={diagLoading}
                className="text-xs text-fin-muted hover:text-fin-primary"
              >
                <RefreshCw size={12} className={diagLoading ? 'animate-spin' : ''} />
                刷新
              </Button>
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
          </Card>

          {/* 提示 */}
          <div className="p-3 bg-fin-bg border border-fin-border rounded text-xs text-fin-muted">
            💡 <strong>提示</strong>：所有配置项都是可选的。如果不填写，系统将使用后端默认配置。
            <br />
            API Key 仅存储在浏览器本地，不会上传到服务器。
          </div>
        </div>

        {/* Footer — 使用共享 Button 组件 */}
        <div className="flex items-center justify-end gap-3 p-4 border-t border-fin-border sticky bottom-0 bg-fin-panel">
          <Button
            variant="ghost"
            size="md"
            data-testid="settings-cancel-btn"
            onClick={onClose}
            className="px-4 py-2 text-fin-muted hover:text-fin-text"
          >
            取消
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={handleSave}
            disabled={loading}
            className="px-4 py-2"
          >
            {saved ? '✓ 已保存' : loading ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>
    </div>
  );
};
