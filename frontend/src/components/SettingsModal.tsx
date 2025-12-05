import React, { useState, useEffect } from 'react';
import { X, Save, Settings } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface UserConfig {
  // LLM 配置
  llm_provider?: string;
  llm_model?: string;
  llm_api_key?: string;
  llm_api_base?: string;
  
  // 数据源配置
  alpha_vantage_api_key?: string;
  finnhub_api_key?: string;
  massive_api_key?: string;
  iex_cloud_api_key?: string;
  tiingo_api_key?: string;

  // UI 设置
  layout_mode?: 'centered' | 'full';
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [config, setConfig] = useState<UserConfig>({});
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const { setLayoutMode } = useStore();
  const [subs, setSubs] = useState<any[]>([]);
  const [subsLoading, setSubsLoading] = useState(false);
  const [subsError, setSubsError] = useState<string | null>(null);
  const [subForm, setSubForm] = useState({
    email: '',
    tickers: '',
    price_threshold: 5,
    alert_types: ['price_change'] as string[],
  });
  const [subSubmitting, setSubSubmitting] = useState(false);

  // 加载配置
  useEffect(() => {
    if (isOpen) {
      loadConfig();
      loadSubscriptions();
    }
  }, [isOpen]);

  const loadConfig = async () => {
    try {
      const response = await apiClient.getConfig();
      if (response.success) {
        setConfig(response.config || {});
      }
    } catch (error) {
      console.error('加载配置失败:', error);
    }
  };

  const handleChange = (key: keyof UserConfig, value: string) => {
    setConfig(prev => ({ ...prev, [key]: value }));

    // 即时生效的本地 UI 设置
    if (key === 'layout_mode') {
      const mode = (value || 'centered') as 'centered' | 'full';
      setLayoutMode(mode);
    }
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      const response = await apiClient.saveConfig(config);
      if (response.success) {
        setSaved(true);
        setTimeout(() => {
          setSaved(false);
          onClose();
        }, 1500);
      } else {
        console.error('保存配置失败: success = false');
      }
    } catch (error) {
      // 后端没开/网络错误：布局已经在本地生效，不再弹出打断式警告
      console.error('保存配置失败(网络):', error);
    } finally {
      setLoading(false);
    }
  };

  const loadSubscriptions = async () => {
    setSubsLoading(true);
    setSubsError(null);
    try {
      const res = await apiClient.listSubscriptions();
      if (res.success) {
        setSubs(res.subscriptions || []);
      } else {
        setSubsError(res.detail || '加载订阅失败');
      }
    } catch (e) {
      setSubsError('加载订阅失败');
    } finally {
      setSubsLoading(false);
    }
  };

  const handleSubChange = (key: string, value: any) => {
    setSubForm((prev) => ({ ...prev, [key]: value }));
  };

  const toggleAlertType = (value: string) => {
    setSubForm((prev) => {
      const exists = prev.alert_types.includes(value);
      const next = exists
        ? prev.alert_types.filter((v) => v !== value)
        : [...prev.alert_types, value];
      return { ...prev, alert_types: next };
    });
  };

  const handleSubscribe = async () => {
    if (!subForm.email || !subForm.tickers) {
      setSubsError('请填写邮箱与股票代码');
      return;
    }
    // 支持逗号/空格/换行分隔多只股票
    const tickerList = subForm.tickers
      .split(/[,\\s]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);
    if (!tickerList.length) {
      setSubsError('请输入至少一个股票代码');
      return;
    }
    setSubSubmitting(true);
    setSubsError(null);
    try {
      for (const t of tickerList) {
        await apiClient.subscribe({
          email: subForm.email.trim(),
          ticker: t,
          alert_types: subForm.alert_types,
          price_threshold: subForm.price_threshold ?? null,
        });
      }
      await loadSubscriptions();
    } catch (e) {
      setSubsError('订阅失败，请稍后再试');
    } finally {
      setSubSubmitting(false);
    }
  };

  const handleUnsubscribe = async (email: string, ticker?: string) => {
    setSubsLoading(true);
    setSubsError(null);
    try {
      await apiClient.unsubscribe({ email, ticker });
      await loadSubscriptions();
    } catch (e) {
      setSubsError('取消订阅失败');
    } finally {
      setSubsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-fin-panel border border-fin-border rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-fin-border">
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
          {/* 订阅管理 */}
          <section className="border border-fin-border rounded-lg p-4 bg-fin-bg/60">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-fin-text">订阅管理</h3>
              {subsLoading && (
                <span className="text-[11px] text-fin-muted">刷新中…</span>
              )}
            </div>
            <div className="grid md:grid-cols-2 gap-3 text-sm">
              <div className="space-y-2">
                <label className="text-xs text-fin-muted">邮箱</label>
                <input
                  type="email"
                  value={subForm.email}
                  onChange={(e) => handleSubChange('email', e.target.value)}
                  placeholder="you@example.com"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs text-fin-muted">股票代码（可多只，逗号/空格分隔）</label>
                <textarea
                  rows={2}
                  value={subForm.tickers}
                  onChange={(e) => handleSubChange('tickers', e.target.value)}
                  placeholder="如 AAPL, MSFT, TSLA"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm uppercase resize-none"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs text-fin-muted">触发阈值(涨跌幅%)</label>
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  value={subForm.price_threshold}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    handleSubChange('price_threshold', isNaN(v) ? null : v);
                  }}
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-fin-text text-sm"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs text-fin-muted">提醒类型</label>
                <div className="flex gap-2 text-xs">
                  <label className="inline-flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={subForm.alert_types.includes('price_change')}
                      onChange={() => toggleAlertType('price_change')}
                    />
                    价格波动
                  </label>
                  <label className="inline-flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={subForm.alert_types.includes('news')}
                      onChange={() => toggleAlertType('news')}
                    />
                    新闻
                  </label>
                </div>
              </div>
            </div>
            {subsError && (
              <p className="text-xs text-trend-down mt-2">{subsError}</p>
            )}
            <div className="flex justify-end mt-3">
              <button
                onClick={handleSubscribe}
                disabled={subSubmitting}
                className="px-3 py-2 rounded bg-fin-primary text-white text-sm hover:bg-blue-600 disabled:opacity-60"
              >
                {subSubmitting ? '提交中…' : '保存订阅'}
              </button>
            </div>
            <div className="mt-4 border-t border-fin-border pt-3">
              <h4 className="text-xs font-medium text-fin-muted mb-2">已订阅</h4>
              <div className="space-y-2 max-h-48 overflow-auto pr-1">
                {subs.map((sub) => (
                  <div
                    key={`${sub.email}-${sub.ticker}`}
                    className="flex items-center justify-between text-xs border border-fin-border rounded px-3 py-2 bg-fin-panel/60"
                  >
                    <div className="space-y-1">
                      <div className="text-fin-text font-medium">{sub.ticker}</div>
                      <div className="text-fin-muted">{sub.email}</div>
                      <div className="text-fin-muted">
                        {sub.alert_types?.join(', ')} | 阈值 {sub.price_threshold ?? '-'}%
                      </div>
                    </div>
                    <button
                      onClick={() => handleUnsubscribe(sub.email, sub.ticker)}
                      className="text-trend-down hover:underline"
                    >
                      取消
                    </button>
                  </div>
                ))}
                {!subs.length && !subsLoading && (
                  <p className="text-xs text-fin-muted">暂无订阅</p>
                )}
              </div>
            </div>
          </section>
          {/* UI 布局设置 */}
          <section>
            <h3 className="text-sm font-medium text-fin-text mb-3">界面布局</h3>
            <div className="space-y-2 text-xs text-fin-muted">
              <p className="mb-1">选择聊天窗口在屏幕中的占用方式：</p>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => handleChange('layout_mode', 'centered')}
                  className={`border rounded-lg px-3 py-2 text-left transition-colors ${
                    (config.layout_mode || 'centered') === 'centered'
                      ? 'border-fin-primary bg-fin-panel/70 text-fin-text'
                      : 'border-fin-border bg-fin-bg hover:border-fin-primary/60'
                  }`}
                >
                  <div className="font-medium text-[11px]">居中布局</div>
                  <div className="text-[10px] text-fin-muted mt-0.5">
                    左右留出呼吸空间，适合大屏和专注阅读。
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => handleChange('layout_mode', 'full')}
                  className={`border rounded-lg px-3 py-2 text-left transition-colors ${
                    config.layout_mode === 'full'
                      ? 'border-fin-primary bg-fin-panel/70 text-fin-text'
                      : 'border-fin-border bg-fin-bg hover:border-fin-primary/60'
                  }`}
                >
                  <div className="font-medium text-[11px]">铺满宽度</div>
                  <div className="text-[10px] text-fin-muted mt-0.5">
                    聊天 + 图表横向拉伸，适合多窗口并排或小屏。
                  </div>
                </button>
              </div>
            </div>
          </section>
          {/* LLM 配置 */}
          <section>
            <h3 className="text-sm font-medium text-fin-text mb-3">LLM 配置（可选）</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-fin-muted mb-1">提供商</label>
                <select
                  value={config.llm_provider || ''}
                  onChange={(e) => handleChange('llm_provider', e.target.value)}
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                >
                  <option value="">使用默认 (Gemini Proxy)</option>
                  <option value="gemini_proxy">Gemini Proxy</option>
                  <option value="openai">OpenAI</option>
                  <option value="anyscale">AnyScale</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">模型</label>
                <input
                  type="text"
                  value={config.llm_model || ''}
                  onChange={(e) => handleChange('llm_model', e.target.value)}
                  placeholder="留空使用默认模型"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">API Key</label>
                <input
                  type="password"
                  value={config.llm_api_key || ''}
                  onChange={(e) => handleChange('llm_api_key', e.target.value)}
                  placeholder="留空使用默认配置"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">API Base URL</label>
                <input
                  type="text"
                  value={config.llm_api_base || ''}
                  onChange={(e) => handleChange('llm_api_base', e.target.value)}
                  placeholder="留空使用默认端点"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
              </div>
            </div>
          </section>

          {/* 数据源配置 */}
          <section>
            <h3 className="text-sm font-medium text-fin-text mb-3">数据源 API Key（可选）</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-fin-muted mb-1">Alpha Vantage API Key</label>
                <input
                  type="password"
                  value={config.alpha_vantage_api_key || ''}
                  onChange={(e) => handleChange('alpha_vantage_api_key', e.target.value)}
                  placeholder="留空使用默认配置"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">Finnhub API Key</label>
                <input
                  type="password"
                  value={config.finnhub_api_key || ''}
                  onChange={(e) => handleChange('finnhub_api_key', e.target.value)}
                  placeholder="留空使用默认配置"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">Massive.com API Key</label>
                <input
                  type="password"
                  value={config.massive_api_key || ''}
                  onChange={(e) => handleChange('massive_api_key', e.target.value)}
                  placeholder="留空使用默认配置"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">IEX Cloud API Key</label>
                <input
                  type="password"
                  value={config.iex_cloud_api_key || ''}
                  onChange={(e) => handleChange('iex_cloud_api_key', e.target.value)}
                  placeholder="留空使用默认配置"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
              </div>
              <div>
                <label className="block text-xs text-fin-muted mb-1">Tiingo API Key</label>
                <input
                  type="password"
                  value={config.tiingo_api_key || ''}
                  onChange={(e) => handleChange('tiingo_api_key', e.target.value)}
                  placeholder="留空使用默认配置"
                  className="w-full bg-fin-bg border border-fin-border rounded px-3 py-2 text-sm text-fin-text"
                />
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
        <div className="flex items-center justify-end gap-3 p-4 border-t border-fin-border">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-fin-muted hover:text-fin-text transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={loading}
            className="px-4 py-2 bg-fin-primary text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center gap-2 transition-colors"
          >
            {saved ? (
              <>
                <span>✓</span> 已保存
              </>
            ) : (
              <>
                <Save size={16} />
                保存
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

