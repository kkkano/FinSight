import { useMemo, useState } from 'react';
import { MessageSquare, Search, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useStore, type ConversationSummary } from '../../store/useStore';
import { conversationStatus, groupConversations } from '../../utils/conversationHistory';
import { ConversationDeleteDialog } from './ConversationDeleteDialog';

export function ConversationHistoryPanel() {
  const navigate = useNavigate();
  const conversations = useStore((state) => state.conversationSummaries);
  const [query, setQuery] = useState('');
  const [ticker, setTicker] = useState('');
  const [status, setStatus] = useState('');
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  const tickers = [...new Set(conversations.flatMap((item) => item.tickers ?? []))].sort();
  const groups = useMemo(() => groupConversations(conversations.filter((item) =>
    (!query || `${item.title} ${item.lastMessagePreview} ${(item.tickers ?? []).join(' ')}`.toLowerCase().includes(query.toLowerCase()))
    && (!ticker || item.tickers?.includes(ticker)) && (!status || conversationStatus(item).value === status))), [conversations, query, ticker, status]);
  const control = 'h-9 rounded-lg border border-t-border bg-t-surface px-3 text-sm text-t-text2';
  return <section className="mx-auto w-full max-w-5xl">
    <div className="mb-6 flex flex-wrap items-center gap-3">
      <label className="flex min-w-[200px] flex-1 items-center gap-2 rounded-lg border border-t-border bg-t-surface px-3">
        <Search size={15} className="text-t-text3" /><input className="h-9 min-w-0 flex-1 border-0 bg-transparent text-sm text-t-text outline-none"
          aria-label="搜索对话" placeholder="搜索标题、标的或对话内容" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <select className={control} aria-label="按标的筛选对话" value={ticker} onChange={(event) => setTicker(event.target.value)}>
        <option value="">全部标的</option>{tickers.map((item) => <option key={item}>{item}</option>)}
      </select>
      <select className={control} aria-label="按状态筛选对话" value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="">全部状态</option><option value="completed">完成</option><option value="partial">部分完成</option>
        <option value="failed">失败</option><option value="running">进行中</option><option value="saved">已保存</option>
      </select>
    </div>
    {!groups.length && <div className="flex min-h-56 flex-col items-center justify-center gap-3 text-sm text-t-text3"><MessageSquare size={24} />
      {query || ticker || status ? '没有匹配的对话。' : '暂无历史对话，提出一个问题开始研究。'}</div>}
    {groups.map((group) => <section key={group.label} className="mb-6">
      <h2 className="mb-2 px-2.5 text-xs text-t-text3">{group.label}</h2>
      {group.items.map((item) => <article key={item.sessionId} className="group flex items-center gap-3 rounded-lg px-2.5 py-3 hover:bg-t-hover" data-testid="history-conversation">
        <button type="button" className="min-w-0 flex-1 text-left" onClick={() => { useStore.getState().selectConversation(item.sessionId); navigate('/chat'); }}>
          <div className="flex flex-wrap items-center gap-2"><span className="truncate text-[14px] font-medium text-t-text">{item.title}</span>
            {(item.tickers ?? []).map((symbol) => <span key={symbol} className="num text-xs text-t-text3">{symbol}</span>)}</div>
          <div className="mt-1 flex gap-3 text-xs text-t-text3"><time dateTime={new Date(item.updatedAt).toISOString()}>
            {new Date(item.updatedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}</time>
            <span className={conversationStatus(item).value === 'failed' ? 'text-fin-danger' : ''}>{conversationStatus(item).label}</span></div>
        </button>
        <button type="button" aria-label={`删除对话 ${item.title}`} className="rounded-md p-2 text-t-text3 opacity-0 hover:text-fin-danger group-hover:opacity-100 focus:opacity-100 max-lg:opacity-100"
          onClick={() => setDeleting(item)}><Trash2 size={14} /></button>
      </article>)}
    </section>)}
    <ConversationDeleteDialog title={deleting?.title ?? null} onCancel={() => setDeleting(null)} onConfirm={() => {
      if (deleting) useStore.getState().deleteConversation(deleting.sessionId); setDeleting(null);
    }} />
  </section>;
}
