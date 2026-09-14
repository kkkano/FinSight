import { LogOut, Moon, Settings, Sun, X } from 'lucide-react';
import type { FC } from 'react';
import { useState } from 'react';

import { getSupabaseClient } from '../api/supabaseClient';
import { buildAnonymousSessionId, useStore } from '../store/useStore';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { Dialog } from './ui/Dialog';
import { useToast } from './ui/Toast';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [signingOut, setSigningOut] = useState(false);
  const { toast } = useToast();
  const {
    theme,
    setTheme,
    colorConvention,
    setColorConvention,
    layoutMode,
    setLayoutMode,
    authIdentity,
    setAuthIdentity,
    setEntryMode,
    setSessionId,
  } = useStore();

  const signOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      const client = getSupabaseClient();
      if (client) {
        const { error } = await client.auth.signOut();
        if (error) throw error;
      }
      setAuthIdentity(null);
      setEntryMode('pending');
      setSessionId(buildAnonymousSessionId());
      onClose();
      window.location.assign('/welcome');
    } catch (error) {
      toast({
        type: 'error',
        title: '退出失败',
        message: error instanceof Error ? error.message : '请稍后重试',
      });
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      labelledBy="settings-modal-title"
      panelClassName="w-full max-w-lg overflow-hidden rounded-lg border border-fin-border bg-fin-panel shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-fin-border p-4">
        <div className="flex items-center gap-2">
          <Settings size={18} className="text-fin-primary" />
          <h2 id="settings-modal-title" className="text-base font-semibold text-fin-text">设置</h2>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="关闭设置" className="p-1">
          <X size={18} />
        </Button>
      </div>

      <div className="space-y-4 p-5">
        <Card className="space-y-3 bg-fin-bg/40 p-4">
          <h3 className="text-sm font-medium text-fin-text">外观</h3>
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant={theme === 'light' ? 'primary' : 'secondary'}
              onClick={() => setTheme('light')}
              className="justify-center"
            >
              <Sun size={15} /> 浅色
            </Button>
            <Button
              variant={theme === 'dark' ? 'primary' : 'secondary'}
              onClick={() => setTheme('dark')}
              className="justify-center"
            >
              <Moon size={15} /> 深色
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <label className="flex cursor-pointer items-center gap-2 rounded border border-fin-border px-3 py-2 text-fin-text">
              <input
                type="radio"
                name="color-convention"
                checked={colorConvention === 'intl'}
                onChange={() => setColorConvention('intl')}
              />
              绿涨红跌
            </label>
            <label className="flex cursor-pointer items-center gap-2 rounded border border-fin-border px-3 py-2 text-fin-text">
              <input
                type="radio"
                name="color-convention"
                checked={colorConvention === 'cn'}
                onChange={() => setColorConvention('cn')}
              />
              红涨绿跌
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <label className="flex cursor-pointer items-center gap-2 rounded border border-fin-border px-3 py-2 text-fin-text">
              <input
                type="radio"
                name="layout-mode"
                checked={layoutMode === 'centered'}
                onChange={() => setLayoutMode('centered')}
              />
              居中布局
            </label>
            <label className="flex cursor-pointer items-center gap-2 rounded border border-fin-border px-3 py-2 text-fin-text">
              <input
                type="radio"
                name="layout-mode"
                checked={layoutMode === 'full'}
                onChange={() => setLayoutMode('full')}
              />
              铺满宽度
            </label>
          </div>
        </Card>

        <Card className="flex items-center justify-between gap-4 bg-fin-bg/40 p-4">
          <div className="min-w-0">
            <h3 className="text-sm font-medium text-fin-text">账户</h3>
            <p className="mt-1 truncate text-xs text-fin-muted">
              {authIdentity?.email || '当前未登录'}
            </p>
          </div>
          {authIdentity && (
            <Button variant="secondary" onClick={() => void signOut()} disabled={signingOut}>
              <LogOut size={14} /> {signingOut ? '退出中' : '退出登录'}
            </Button>
          )}
        </Card>
      </div>
    </Dialog>
  );
};
