import React, { useState, useEffect } from 'react';
import { X, Settings, Sun, Moon, Activity, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface UserConfig {
  llm_provider?: string;
  llm_model?: string;
  llm_api_key?: string;
  llm_api_base?: string;
  layout_mode?: 'centered' | 'full';
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [config, setConfig] = useState<UserConfig>({});
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  const { theme, setTheme, setLayoutMode } = useStore();

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
        setConfig(response.config || {});
      }
    } catch (e) {
      console.error('加载配置失败:', e);
    }
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
      await apiClient.saveConfig(config);
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
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-fin-panel border border-fin-border rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-fin-border sticky top-0 bg-fin-panel z-10">
          <div className="flex items-center gap-2">
            <Settings size={20} className="text-fin-primary" />
            <h2 className="text-lg font-semibold text-fin-text">设置</h2>
          </div>
          <button
            onClick={onClose}
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
                  <option value="">使用默认 (Gemini Proxy)</option>
                  <option value="gemini_proxy">Gemini Proxy</option>
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
