import { useEffect, useState } from 'react';
import { Cpu } from 'lucide-react';
import { SettingsModal } from '../SettingsModal';
import { useModelSelectionStore } from '../../store/modelSelection';
import { apiClient } from '../../api/client';

export function ModelPickerButton() {
  const [open, setOpen] = useState(false);
  const metadata = useModelSelectionStore((state) => state.metadata);
  const selection = useModelSelectionStore((state) => state.selection);
  const pendingCustom = useModelSelectionStore((state) => state.pendingCustom);
  const setCatalog = useModelSelectionStore((state) => state.setCatalog);
  useEffect(() => {
    let active = true;
    if (!useModelSelectionStore.getState().catalog.length) {
      void apiClient.getModels().then(({ models, default_model_id }) => {
        if (active) setCatalog(models, default_model_id);
      }).catch(() => undefined);
    }
    return () => { active = false; };
  }, [setCatalog]);
  return <>
    <button type="button" data-testid="chat-model-switcher" onClick={() => setOpen(true)}
      className="flex min-w-0 items-center gap-1 rounded px-2 py-1 text-xs text-fin-muted hover:bg-fin-hover"
      aria-label="切换 AI 模型">
      {metadata?.icon_url ? <img src={metadata.icon_url} alt="" className="h-4 w-4" /> : <Cpu size={14} />}
      <span className="max-w-36 truncate">{pendingCustom ? `${pendingCustom.model} · 待补密钥`
        : metadata?.label || (selection?.source === 'system' ? selection.model_id : selection?.model) || '选择模型'}</span>
    </button>
    {open && <SettingsModal isOpen onClose={() => setOpen(false)} />}
  </>;
}
