import { useState } from 'react';
import { Cpu } from 'lucide-react';
import { SettingsModal } from '../SettingsModal';
import { useModelSelectionStore } from '../../store/modelSelection';

export function ModelPickerButton() {
  const [open, setOpen] = useState(false);
  const metadata = useModelSelectionStore((state) => state.metadata);
  return <>
    <button type="button" data-testid="chat-model-switcher" onClick={() => setOpen(true)}
      className="flex min-w-0 items-center gap-1 rounded px-2 py-1 text-xs text-fin-muted hover:bg-fin-hover"
      aria-label="切换聊天和报告模型">
      {metadata?.icon_url ? <img src={metadata.icon_url} alt="" className="h-4 w-4" /> : <Cpu size={14} />}
      <span className="max-w-36 truncate">{metadata?.label || '默认模型'}</span>
    </button>
    {open && <SettingsModal isOpen onClose={() => setOpen(false)} />}
  </>;
}
