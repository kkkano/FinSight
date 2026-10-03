import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useStore } from '../../store/useStore';

export function ApplicationUpdateBanner() {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const loading = useStore((state) => Object.values(state.chatLoadingBySession).some(Boolean));
  const draft = useStore((state) => state.draft);

  useEffect(() => {
    const currentBuild = import.meta.env.VITE_APP_BUILD_ID;
    if (!currentBuild || currentBuild === 'local') return;
    const controller = new AbortController();
    let checking = false;
    const check = async () => {
      if (checking || document.visibilityState === 'hidden') return;
      checking = true;
      try {
        const response = await fetch('/app-version.json', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) return;
        const version = await response.json();
        if (typeof version.build_id === 'string' && /^[A-Za-z0-9._-]{1,128}$/.test(version.build_id)
          && version.build_id !== currentBuild && version.build_id !== 'local') setUpdateAvailable(true);
      } catch {
        // 网络暂不可用不影响研究，下一次回到页面时重新检查。
      } finally {
        checking = false;
      }
    };
    void check();
    const interval = window.setInterval(() => void check(), 300_000);
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    return () => {
      controller.abort();
      window.clearInterval(interval);
      window.removeEventListener('focus', check);
      document.removeEventListener('visibilitychange', check);
    };
  }, []);

  if (!updateAvailable) return null;
  const blocked = loading || Boolean(draft.trim());
  return (
    <div role="status" className="mx-3 mt-3 flex shrink-0 items-center justify-between gap-3 rounded-lg bg-fin-primary/10 px-3 py-2 text-sm text-fin-text">
      <span>{loading ? '新版本已就绪，本次回答结束后即可更新。'
        : draft.trim() ? '新版本已就绪，请先发送或保存当前输入。' : '新版本已就绪，刷新后使用最新修复。'}</span>
      <button type="button" disabled={blocked} onClick={() => window.location.reload()}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-fin-primary hover:bg-fin-primary/10 disabled:opacity-50">
        <RefreshCw size={14} />刷新更新
      </button>
    </div>
  );
}
