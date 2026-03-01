import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Bell, RefreshCw, ToggleLeft, ToggleRight, X } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Dialog } from './ui/Dialog';
import { Input } from './ui/Input';

interface SubscribeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface Subscription {
  email: string;
  ticker: string;
  alert_types: string[];
  price_threshold: number | null;
  alert_mode?: 'price_change_pct' | 'price_target';
  price_target?: number | null;
  direction?: 'above' | 'below' | null;
  price_target_fired?: boolean;
  last_alert_at?: string;
  last_news_at?: string;
  disabled?: boolean;
  alert_failures?: number;
  last_alert_error?: string | null;
  last_alert_error_at?: string | null;
}

interface FormState {
  email: string;
  tickers: string;
  alert_mode: 'price_change_pct' | 'price_target';
  price_threshold: number;
  price_target: number | null;
  alert_types: string[];
}

const DEFAULT_FORM: FormState = {
  email: '',
  tickers: '',
  alert_mode: 'price_change_pct',
  price_threshold: 5,
  price_target: null,
  alert_types: ['price_change'],
};

export const SubscribeModal: React.FC<SubscribeModalProps> = ({ isOpen, onClose }) => {
  const { subscriptionEmail, setSubscriptionEmail } = useStore();

  const [subs, setSubs] = useState<Subscription[]>([]);
  const [subsLoading, setSubsLoading] = useState(false);
  const [subsError, setSubsError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [submitting, setSubmitting] = useState(false);

  const effectiveEmail = useMemo(() => {
    const fromForm = form.email.trim();
    if (fromForm) return fromForm;
    return subscriptionEmail.trim();
  }, [form.email, subscriptionEmail]);

  const loadSubscriptions = useCallback(async () => {
    setSubsLoading(true);
    setSubsError(null);
    try {
      const res = await apiClient.listSubscriptions(effectiveEmail || undefined);
      if (res?.success) {
        setSubs(Array.isArray(res.subscriptions) ? res.subscriptions : []);
      } else {
        setSubsError(res?.detail || '加载订阅失败');
      }
    } catch {
      setSubsError('加载订阅失败');
    } finally {
      setSubsLoading(false);
    }
  }, [effectiveEmail]);

  useEffect(() => {
    if (!isOpen) return;
    void loadSubscriptions();
    if (subscriptionEmail && !form.email) {
      setForm((prev) => ({ ...prev, email: subscriptionEmail }));
    }
  }, [form.email, isOpen, loadSubscriptions, subscriptionEmail]);

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (key === 'email') {
      setSubscriptionEmail(String(value || ''));
    }
  };

  const toggleAlertType = (value: string) => {
    setForm((prev) => {
      const exists = prev.alert_types.includes(value);
      const alert_types = exists ? prev.alert_types.filter((item) => item !== value) : [...prev.alert_types, value];
      return { ...prev, alert_types };
    });
  };

  const parseTickerList = (value: string): string[] =>
    value
      .split(/[\s,]+/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);

  const handleSubscribe = async () => {
    const email = form.email.trim();
    const tickers = parseTickerList(form.tickers);

    if (!email || tickers.length === 0) {
      setSubsError('请填写邮箱与股票代码');
      return;
    }
    if (form.alert_mode === 'price_change_pct' && (!form.price_threshold || form.price_threshold <= 0)) {
      setSubsError('请输入有效的涨跌幅阈值');
      return;
    }
    if (form.alert_mode === 'price_target' && (!form.price_target || form.price_target <= 0)) {
      setSubsError('请输入有效的目标价格');
      return;
    }

    setSubmitting(true);
    setSubsError(null);
    try {
      for (const ticker of tickers) {
        await apiClient.subscribe({
          email,
          ticker,
          alert_types: form.alert_types,
          alert_mode: form.alert_mode,
          price_threshold: form.alert_mode === 'price_change_pct' ? form.price_threshold : null,
          price_target: form.alert_mode === 'price_target' ? form.price_target : null,
        });
      }
      setSubscriptionEmail(email);
      setForm((prev) => ({ ...prev, tickers: '' }));
      await loadSubscriptions();
    } catch {
      setSubsError('订阅失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const handleUnsubscribe = async (email: string, ticker?: string) => {
    setSubsLoading(true);
    setSubsError(null);
    try {
      const res = await apiClient.unsubscribe({ email, ticker });
      if (res?.success) {
        setSubs((prev) => prev.filter((item) => !(item.email === email && item.ticker === ticker)));
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
        enabled: currentDisabled,
      });
      if (res?.success) {
        setSubs((prev) =>
          prev.map((item) =>
            item.email === email && item.ticker === ticker
              ? { ...item, disabled: !currentDisabled, alert_failures: currentDisabled ? 0 : item.alert_failures }
              : item,
          ),
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

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      panelClassName="bg-fin-panel border border-fin-border rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto shadow-2xl"
    >
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-fin-border bg-fin-panel p-4 rounded-t-2xl">
        <div className="flex items-center gap-2">
          <div className="rounded-lg bg-fin-primary/10 p-2">
            <Bell size={18} className="text-fin-primary" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-fin-text">订阅管理</h2>
            <p className="text-xs text-fin-muted">管理价格提醒与新闻提醒</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={loadSubscriptions} disabled={subsLoading} className="p-1.5" title="刷新">
            <RefreshCw size={16} className={subsLoading ? 'animate-spin' : ''} />
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose} className="p-1.5">
            <X size={18} />
          </Button>
        </div>
      </div>

      <div className="space-y-5 p-6">
        <div className="grid gap-4 text-sm md:grid-cols-2">
          <Input
            label="邮箱"
            type="email"
            value={form.email}
            onChange={(event) => setField('email', event.target.value)}
            placeholder="you@example.com"
            className="py-2.5"
          />

          <div className="space-y-1">
            <label className="text-xs font-medium text-fin-text-secondary">股票代码（逗号或空格分隔）</label>
            <textarea
              rows={2}
              value={form.tickers}
              onChange={(event) => setField('tickers', event.target.value)}
              placeholder="AAPL, MSFT, TSLA"
              className="w-full resize-none rounded-lg border border-fin-border bg-fin-bg px-3 py-2.5 text-sm uppercase text-fin-text outline-none transition-colors focus:border-fin-primary focus:ring-1 focus:ring-fin-primary/30"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-fin-text-secondary">提醒模式</label>
            <div className="flex gap-2">
              <Button
                variant={form.alert_mode === 'price_change_pct' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setField('alert_mode', 'price_change_pct')}
              >
                涨跌幅
              </Button>
              <Button
                variant={form.alert_mode === 'price_target' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setField('alert_mode', 'price_target')}
              >
                到价
              </Button>
            </div>
            {form.alert_mode === 'price_change_pct' ? (
              <Input
                label="阈值（%）"
                type="number"
                min={0.1}
                step={0.1}
                value={form.price_threshold}
                onChange={(event) => {
                  const value = parseFloat(event.target.value);
                  setField('price_threshold', Number.isFinite(value) ? value : 0);
                }}
                className="py-2.5"
              />
            ) : (
              <Input
                label="目标价格"
                type="number"
                min={0.01}
                step={0.01}
                value={form.price_target ?? ''}
                onChange={(event) => {
                  const value = parseFloat(event.target.value);
                  setField('price_target', Number.isFinite(value) ? value : null);
                }}
                className="py-2.5"
              />
            )}
            {form.alert_mode === 'price_target' && (
              <p className="text-2xs text-fin-muted">方向由后端根据当前价格自动推断（仅 above / below）</p>
            )}
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-fin-text-secondary">订阅类型</label>
            <div className="flex gap-4 pt-1">
              <label className="inline-flex cursor-pointer items-center gap-1.5 text-fin-text">
                <input
                  type="checkbox"
                  checked={form.alert_types.includes('price_change')}
                  onChange={() => toggleAlertType('price_change')}
                  className="accent-fin-primary"
                />
                价格波动
              </label>
              <label className="inline-flex cursor-pointer items-center gap-1.5 text-fin-text">
                <input
                  type="checkbox"
                  checked={form.alert_types.includes('news')}
                  onChange={() => toggleAlertType('news')}
                  className="accent-fin-primary"
                />
                新闻
              </label>
            </div>
          </div>
        </div>

        {subsError && <p className="text-xs text-red-400">{subsError}</p>}

        <div className="flex justify-end">
          <Button variant="primary" size="lg" onClick={handleSubscribe} disabled={submitting}>
            {submitting ? '提交中...' : '保存订阅'}
          </Button>
        </div>

        <div className="border-t border-fin-border pt-5">
          <h4 className="mb-3 text-xs font-medium text-fin-muted">已订阅 ({subs.length})</h4>
          <div className="max-h-60 space-y-2 overflow-auto">
            {subs.map((sub) => {
              const isDisabled = sub.disabled === true;
              const hasError = Boolean((sub.alert_failures ?? 0) > 0 || sub.last_alert_error);
              return (
                <div
                  key={`${sub.email}-${sub.ticker}`}
                  className={[
                    'flex items-center justify-between rounded-lg border px-3 py-2.5 text-xs transition-colors',
                    isDisabled
                      ? 'border-red-500/30 bg-red-500/5 opacity-70'
                      : hasError
                        ? 'border-amber-500/30 bg-amber-500/5'
                        : 'border-fin-border bg-fin-bg/60 hover:bg-fin-hover',
                  ].join(' ')}
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className={isDisabled ? 'font-medium text-fin-muted line-through' : 'font-medium text-fin-text'}>
                        {sub.ticker}
                      </span>
                      {isDisabled && <Badge variant="danger">已禁用</Badge>}
                      {hasError && !isDisabled && (
                        <Badge variant="warning" className="flex items-center gap-1">
                          <AlertTriangle size={10} />
                          失败 {sub.alert_failures ?? 0} 次
                        </Badge>
                      )}
                    </div>

                    <div className="truncate text-fin-muted">{sub.email}</div>
                    <div className="text-fin-muted">
                      {sub.alert_types?.join(', ')} |{' '}
                      {sub.alert_mode === 'price_target'
                        ? `到价 ${sub.price_target ?? '-'} (${sub.direction ?? 'auto'})`
                        : `涨跌幅 ${sub.price_threshold ?? '-'}%`}
                    </div>

                    {sub.last_alert_error && (
                      <div className="truncate text-2xs text-red-400" title={sub.last_alert_error}>
                        错误: {sub.last_alert_error}
                      </div>
                    )}

                    {(sub.last_alert_at || sub.last_news_at) && (
                      <div className="text-2xs text-fin-muted">
                        {sub.last_alert_at && <>最后价格提醒: {new Date(sub.last_alert_at).toLocaleString()}</>}
                        {sub.last_news_at && (
                          <>
                            {sub.last_alert_at ? ' | ' : ''}
                            最后新闻提醒: {new Date(sub.last_news_at).toLocaleString()}
                          </>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="ml-3 flex shrink-0 items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleToggle(sub.email, sub.ticker, isDisabled)}
                      className={`p-1 ${isDisabled ? 'text-fin-muted hover:text-fin-success' : 'text-fin-success hover:text-fin-muted'}`}
                      title={isDisabled ? '点击启用' : '点击禁用'}
                    >
                      {isDisabled ? <ToggleLeft size={20} /> : <ToggleRight size={20} />}
                    </Button>

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleUnsubscribe(sub.email, sub.ticker)}
                      className="text-red-400 hover:text-red-300"
                    >
                      取消
                    </Button>
                  </div>
                </div>
              );
            })}

            {subs.length === 0 && !subsLoading && <p className="py-4 text-center text-xs text-fin-muted">暂无订阅</p>}
          </div>
        </div>
      </div>
    </Dialog>
  );
};
