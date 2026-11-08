import { useEffect, useRef } from 'react';
import { Dialog } from '../ui/Dialog';

export function ConversationDeleteDialog({ title, onCancel, onConfirm }: {
  title: string | null; onCancel: () => void; onConfirm: () => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (title === null) return;
    const previous = document.activeElement as HTMLElement | null;
    cancel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onCancel(); }
      if (event.key === 'Tab') {
        event.preventDefault();
        (document.activeElement === cancel.current ? confirm.current : cancel.current)?.focus();
      }
    };
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key); previous?.focus(); };
  }, [title, onCancel]);
  return <Dialog open={title !== null} onClose={onCancel} ariaLabel="删除对话确认"
    panelClassName="w-full max-w-sm rounded-xl border border-t-border bg-t-surface p-6 shadow-xl">
    <h2 className="text-base font-semibold text-t-text">删除这段对话？</h2>
    <p className="mt-3 break-words text-sm leading-6 text-t-text2">「{title}」及保存的对话内容将被删除。</p>
    <div className="mt-5 flex justify-end gap-2">
      <button ref={cancel} type="button" onClick={onCancel} className="min-h-10 rounded-lg border border-t-border px-4 text-sm text-t-text2">取消</button>
      <button ref={confirm} type="button" onClick={onConfirm} className="min-h-10 rounded-lg bg-fin-danger px-4 text-sm text-white">删除对话</button>
    </div>
  </Dialog>;
}
