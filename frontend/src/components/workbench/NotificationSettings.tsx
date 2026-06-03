/**
 * NotificationSettings.tsx —— 邮件通知设置（监控配置面板底部分区）
 *
 * - SMTP 未配置：灰色提示「服务器未配置 SMTP，邮件通知不可用」，输入框禁用
 * - SMTP 就绪：邮箱输入框 + 开关，保存调 PUT
 * - 启用但服务器拒绝（理论上 smtp_configured=false 才会）→ toast 后端错误文案
 */
import { useEffect, useState } from 'react';
import { Mail } from 'lucide-react';

import { useMonitorSettings } from '../../hooks/useMonitorSettings';
import { useToast } from '../ui';

interface NotificationSettingsProps {
  sessionId: string | null | undefined;
}

const inputClass =
  'min-w-0 flex-1 px-2 py-1 text-xs rounded-lg border border-fin-border bg-fin-bg text-fin-text placeholder:text-fin-muted focus:outline-none focus:border-fin-primary focus:ring-1 focus:ring-fin-primary/30 disabled:opacity-50 disabled:cursor-not-allowed';

export function NotificationSettings({ sessionId }: NotificationSettingsProps) {
  const { settings, loading, save } = useMonitorSettings(sessionId);
  const { toast } = useToast();

  const [email, setEmail] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [saving, setSaving] = useState(false);

  // 后端数据回填到本地编辑态
  useEffect(() => {
    if (settings) {
      setEmail(settings.notify_email ?? '');
      setEnabled(settings.notify_enabled);
    }
  }, [settings]);

  const smtpConfigured = settings?.smtp_configured ?? false;

  const handleSave = async (nextEnabled: boolean) => {
    const trimmed = email.trim();
    // 启用时校验邮箱基本格式
    if (nextEnabled && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      toast({ type: 'warning', title: '请输入有效的邮箱地址' });
      return;
    }
    setSaving(true);
    const ok = await save(trimmed || null, nextEnabled);
    setSaving(false);
    if (ok) {
      setEnabled(nextEnabled);
      toast({ type: 'success', title: '通知设置已保存' });
    } else {
      // 失败时还原开关，并提示后端错误（如 SMTP 未配置）
      setEnabled(settings?.notify_enabled ?? false);
      toast({
        type: 'error',
        title: '保存通知设置失败',
        message: '服务器未配置 SMTP，无法启用邮件通知',
      });
    }
  };

  return (
    <div className="px-4 py-3 border-t border-fin-border" data-testid="notification-settings">
      <div className="flex items-center gap-2 mb-2">
        <Mail size={13} className="text-fin-primary" />
        <span className="text-xs font-semibold text-fin-text">邮件通知</span>
      </div>

      {loading && !settings ? (
        <div className="text-2xs text-fin-muted">正在加载通知设置...</div>
      ) : !smtpConfigured ? (
        <div className="text-2xs text-fin-muted leading-relaxed" data-testid="notification-smtp-unavailable">
          服务器未配置 SMTP，邮件通知不可用。
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="通知邮箱"
              aria-label="通知邮箱"
              disabled={saving}
              className={inputClass}
            />
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label="邮件通知开关"
              disabled={saving}
              onClick={() => void handleSave(!enabled)}
              data-testid="notification-toggle"
              className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
                enabled ? 'bg-fin-primary' : 'bg-fin-border'
              }`}
            >
              <span
                className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                  enabled ? 'translate-x-3.5' : 'translate-x-0.5'
                }`}
              />
            </button>
          </div>
          {/* 保存邮箱（不改开关，仅更新邮箱地址） */}
          <button
            type="button"
            onClick={() => void handleSave(enabled)}
            disabled={saving}
            className="px-2.5 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-50 transition-colors"
          >
            保存邮箱
          </button>
        </div>
      )}

      <div className="mt-2 text-2xs text-fin-muted leading-relaxed">
        开启后，盯盘扫描发现新异常时会汇总发送到该邮箱（每小时最多 1 封）。
      </div>
    </div>
  );
}

export default NotificationSettings;
