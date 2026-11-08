import { useEffect, useState } from 'react';
import { Check, CircleAlert, Loader2, X } from 'lucide-react';
import { apiClient } from '../../api/client';
import type { ResearchAction } from '../../types/runtime';

export function ActionConfirmationCard({ action, runId }: { action: ResearchAction; runId?: string }) {
  const [status, setStatus] = useState(action.status);
  const [pending, setPending] = useState(false);
  useEffect(() => setStatus(action.status), [action.status]);
  const [error, setError] = useState('');
  const expired = action.expires_at && Date.parse(action.expires_at) <= Date.now();
  const verb = action.action === 'watchlist.add' ? '加入自选' : '从自选移除';
  const confirm = async (confirmed: boolean) => {
    if (!runId || pending || status !== 'proposed') return;
    setPending(true); setError('');
    try {
      const result = await apiClient.confirmRunAction(runId, action.action_id, action.payload_hash, confirmed);
      setStatus(result.status);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作未完成，请稍后重试');
    } finally { setPending(false); }
  };
  return <section className="my-4 rounded-xl border border-t-border bg-t-card p-4" aria-label="操作确认">
    <div className="flex items-start gap-3">
      {status === 'completed' ? <Check size={17} className="mt-0.5 text-fin-success" /> : <CircleAlert size={17} className="mt-0.5 text-t-accent" />}
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-medium text-t-text">{action.ticker} · {verb}</h3>
        <p className="mt-1 text-xs leading-6 text-t-text3">仅修改你的自选列表，不执行股票交易。</p>
        {status === 'completed' ? <p role="status" className="mt-2 text-sm text-fin-success">操作已完成</p>
          : status === 'cancelled' ? <p role="status" className="mt-2 text-sm text-t-text3">已取消此操作</p>
            : status === 'expired' || expired ? <p role="status" className="mt-2 text-sm text-t-text3">确认已过期，请重新提出要求。</p>
              : <div className="mt-3 flex gap-2">
                <button type="button" onClick={() => void confirm(true)} disabled={pending || !runId} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-t-accent px-4 text-sm text-white dark:text-[#0e1014] disabled:opacity-50">
                  {pending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}确认{verb}
                </button>
                <button type="button" onClick={() => void confirm(false)} disabled={pending || !runId} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-t-border px-4 text-sm text-t-text2"><X size={14} />取消</button>
              </div>}
        {error && <p role="alert" className="mt-2 text-sm text-fin-danger">{error}</p>}
      </div>
    </div>
  </section>;
}

