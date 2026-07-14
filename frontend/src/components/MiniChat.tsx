import { useState, type FormEvent } from 'react';
import { SendHorizontal } from 'lucide-react';
import { useLocation } from 'react-router-dom';

import { useChatHandoff } from '../hooks/useChatHandoff';
import { useDashboardStore } from '../store/dashboardStore';

/** 兼容旧引用的轻量跳转器；真实发送始终由主 Chat 的 useChatStream 完成。 */
export function MiniChat() {
  const [draft, setDraft] = useState('');
  const location = useLocation();
  const handoff = useChatHandoff();
  const activeSymbol = useDashboardStore((state) => state.activeAsset?.symbol);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const sourceView = location.pathname.startsWith('/workbench') ? 'workbench' : 'dashboard';
    if (handoff({ draft, activeSymbol, sourceView })) setDraft('');
  };

  return (
    <form onSubmit={submit} className="flex items-end gap-2 p-3">
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        aria-label="转到主对话"
        className="min-h-16 flex-1 resize-none rounded border border-fin-border bg-fin-bg p-2 text-sm text-fin-text"
      />
      <button
        type="submit"
        className="inline-flex h-9 w-9 items-center justify-center rounded border border-fin-border text-fin-text-secondary hover:text-fin-primary"
        title="转到主对话"
      >
        <SendHorizontal size={16} />
      </button>
    </form>
  );
}

export default MiniChat;
