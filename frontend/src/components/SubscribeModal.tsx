import React, { useState, useEffect } from 'react';
import { X, Bell, RefreshCw, ToggleLeft, ToggleRight, AlertTriangle } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

interface SubscribeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface Subscription {
  email: string;
  ticker: string;
  alert_types: string[];
  price_threshold: number | null;
  last_alert_at?: string;
  last_news_at?: string;
  disabled?: boolean;
  alert_failures?: number;
  last_alert_error?: string | null;
  last_alert_error_at?: string | null;
}

export const SubscribeModal: React.FC<SubscribeModalProps> = ({ isOpen, onClose }) => {
  const { subscriptionEmail, setSubscriptionEmail } = useStore();

  const [subs, setSubs] = useState<Subscription[]>([]);
  const [subsLoading, setSubsLoading] = useState(false);
  const [subsError, setSubsError] = useState<string | null>(null);
  const [subForm, setSubForm] = useState({
    email: '',
    tickers: '',
    price_threshold: 5,
    alert_types: ['price_change'] as string[],
  });
  const [subSubmitting, setSubSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadSubscriptions();
      if (subscriptionEmail && subscriptionEmail !== subForm.email) {
        setSubForm((prev) => ({ ...prev, email: subscriptionEmail }));
      }
    }
  }, [isOpen]);

  const loadSubscriptions = async () => {
    setSubsLoading(true);
    setSubsError(null);
    try {
      const scopedEmail = subscriptionEmail || subForm.email.trim();
      const res = await apiClient.listSubscriptions(scopedEmail || undefined);
      if (res?.success) {
        setSubs(res.subscriptions || []);
      } else {
        setSubsError(res?.detail || '加载订阅失败');
      }
    } catch {
      setSubsError('加载订阅失败');
    } finally {
      setSubsLoading(false);
    }
  };

  const handleSubChange = (key: string, value: any) => {
    setSubForm((prev) => ({ ...prev, [key]: value }));
    if (key === 'email') {
      setSubscriptionEmail(value);
    }
  };

  const toggleAlertType = (value: string) => {
    setSubForm((prev) => {
      const exists = prev.alert_types.includes(value);
      const next = exists ? prev.alert_types.filter((v) => v !== value) : [...prev.alert_types, value];
      return { ...prev, alert_types: next };
    });
  };

  const handleSubscribe = async () => {
    if (!subForm.email || !subForm.tickers) {
      setSubsError('请填写邮箱与股票代码');
      return;
    }
    const tickerList = subForm.tickers
      .split(/[,\s]+/)
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
      setSubscriptionEmail(subForm.email.trim());
      setSubForm((prev) => ({ ...prev, tickers: '' }));
      await loadSubscriptions();
    } catch {
      setSubsError('订阅失败，请稍后再试');
    } finally {
      setSubSubmitting(false);
    }
  };

  const handleUnsubscribe = async (email: string, ticker?: string) => {
    setSubsLoading(true);
    setSubsError(null);
    try {
      const res = await apiClient.unsubscribe({ email, ticker });
      if (res?.success) {
        setSubs(prev => prev.filter(s => !(s.email === email && s.ticker === ticker)));
      } else {
        setSubsError(res?.detail || '取消订阅失败');
      }
    } catch {
      setSubsError('取消订阅失败');
    } finally {
      setSubsLoading(false);
    }
  };

  const handleToggle = async (email: string, ticker: string, currentDisabled: boolean) => {
    setSubsLoading(true);
    setSubsError(null);
    try {
      const res = await apiClient.toggleSubscription({
        email,
        ticker,
        enabled: currentDisabled, // if currently disabled, we want to enable
      });
      if (res?.success) {
        setSubs(prev =>
          prev.map(s =>
            s.email === email && s.ticker === ticker
              ? { ...s, disabled: !currentDisabled, alert_failures: currentDisabled ? 0 : s.alert_failures }
              : s
          )
        );
      } else {
        setSubsError(res?.detail || '切换订阅状态失败');
      }
    } catch {
      setSubsError('切换订阅状态失败');
    } finally {
      setSubsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4 backdrop-blur-sm">
      <div className="bg-fin-panel border border-fin-border rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-fin-border sticky top-0 bg-fin-panel z-10 rounded-t-2xl">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-fin-primary/10 rounded-lg">
              <Bell size={18} className="text-fin-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-fin-text">订阅管理</h2>
              <p className="text-xs text-fin-muted">管理股票价格提醒和新闻订阅</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadSubscriptions}
              disabled={subsLoading}
              className="p-1.5 hover:bg-fin-hover rounded-lg transition-colors text-fin-muted hover:text-fin-text"
              title="刷新"
            >
              <RefreshCw size={16} className={subsLoading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 hover:bg-fin-hover rounded-lg transition-colors text-fin-muted hover:text-fin-text"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5">
          {/* 订阅表单 */}
          <div className="grid md:grid-cols-2 gap-4 text-sm">
            <div className="space-y-2">
              <label className="text-xs text-fin-muted">邮箱</label>
              <input
                type="email"
                value={subForm.email}
                onChange={(e) => handleSubChange('email', e.target.value)}
                placeholder="you@example.com"
                className="w-full bg-fin-bg border border-fin-border rounded-lg px-3 py-2.5 text-fin-text text-sm focus:border-fin-primary focus:ring-2 focus:ring-fin-primary/20 outline-none transition-all"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs text-fin-muted">股票代码（可多只，逗号/空格分隔）</label>
              <textarea
                rows={2}
                value={subForm.tickers}
                onChange={(e) => handleSubChange('tickers', e.target.value)}
                placeholder="如 AAPL, MSFT, TSLA"
                className="w-full bg-fin-bg border border-fin-border rounded-lg px-3 py-2.5 text-fin-text text-sm uppercase resize-none focus:border-fin-primary focus:ring-2 focus:ring-fin-primary/20 outline-none transition-all"
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
                className="w-full bg-fin-bg border border-fin-border rounded-lg px-3 py-2.5 text-fin-text text-sm focus:border-fin-primary focus:ring-2 focus:ring-fin-primary/20 outline-none transition-all"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs text-fin-muted">提醒类型</label>
              <div className="flex gap-4 text-sm pt-1">
                <label className="inline-flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={subForm.alert_types.includes('price_change')}
                    onChange={() => toggleAlertType('price_change')}
                    className="accent-fin-primary"
                  />
                  <span className="text-fin-text">价格波动</span>
                </label>
                <label className="inline-flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={subForm.alert_types.includes('news')}
                    onChange={() => toggleAlertType('news')}
                    className="accent-fin-primary"
                  />
                  <span className="text-fin-text">新闻</span>
                </label>
              </div>
            </div>
          </div>

          {subsError && <p className="text-xs text-red-400">{subsError}</p>}

          <div className="flex justify-end">
            <button
              onClick={handleSubscribe}
              disabled={subSubmitting}
              className="px-5 py-2.5 rounded-lg bg-fin-primary text-white text-sm font-medium hover:bg-blue-600 disabled:opacity-60 transition-colors"
            >
              {subSubmitting ? '提交中…' : '保存订阅'}
            </button>
          </div>

          {/* 已订阅列表 */}
          <div className="border-t border-fin-border pt-5">
            <h4 className="text-xs font-medium text-fin-muted mb-3">
              已订阅 ({subs.length})
            </h4>
            <div className="space-y-2 max-h-60 overflow-auto">
              {subs.map((sub) => {
                const isDisabled = sub.disabled === true;
                const hasError = (sub.alert_failures ?? 0) > 0 || sub.last_alert_error;

                return (
                  <div
                    key={`${sub.email}-${sub.ticker}`}
                    className={`flex items-center justify-between text-xs border rounded-lg px-3 py-2.5 transition-colors ${
                      isDisabled
                        ? 'border-red-500/30 bg-red-500/5 opacity-70'
                        : hasError
                          ? 'border-amber-500/30 bg-amber-500/5'
                          : 'border-fin-border bg-fin-bg/60 hover:bg-fin-hover'
                    }`}
                  >
                    <div className="space-y-1 flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`font-medium ${isDisabled ? 'text-fin-muted line-through' : 'text-fin-text'}`}>
                          {sub.ticker}
                        </span>
                        {isDisabled && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-red-500/20 text-red-400 font-medium">
                            已禁用
                          </span>
                        )}
                        {hasError && !isDisabled && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-400 font-medium flex items-center gap-1">
                            <AlertTriangle size={10} />
                            失败 {sub.alert_failures ?? 0} 次
                          </span>
                        )}
                      </div>
                      <div className="text-fin-muted truncate">{sub.email}</div>
                      <div className="text-fin-muted">
                        {sub.alert_types?.join(', ')} | 阈值 {sub.price_threshold ?? '-'}%
                      </div>
                      {sub.last_alert_error && (
                        <div className="text-[10px] text-red-400 truncate" title={sub.last_alert_error}>
                          错误: {sub.last_alert_error}
                        </div>
                      )}
                      {(sub.last_alert_at || sub.last_news_at) && (
                        <div className="text-[10px] text-fin-muted">
                          {sub.last_alert_at && <>最后价格提醒: {new Date(sub.last_alert_at).toLocaleString()}</>}
                          {sub.last_news_at && (
                            <>
                              {sub.last_alert_at ? ' · ' : ''}
                              最后新闻提醒: {new Date(sub.last_news_at).toLocaleString()}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 ml-3 shrink-0">
                      {/* Toggle Switch */}
                      <button
                        onClick={() => handleToggle(sub.email, sub.ticker, isDisabled)}
                        className={`p-1 rounded transition-colors ${
                          isDisabled
                            ? 'text-fin-muted hover:text-fin-success'
                            : 'text-fin-success hover:text-fin-muted'
                        }`}
                        title={isDisabled ? '点击启用' : '点击禁用'}
                      >
                        {isDisabled ? <ToggleLeft size={20} /> : <ToggleRight size={20} />}
                      </button>
                      {/* Unsubscribe */}
                      <button
                        onClick={() => handleUnsubscribe(sub.email, sub.ticker)}
                        className="text-red-400 hover:text-red-300 hover:underline"
                      >
                        取消
                      </button>
                    </div>
                  </div>
                );
              })}
              {!subs.length && !subsLoading && (
                <p className="text-xs text-fin-muted text-center py-4">暂无订阅</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
