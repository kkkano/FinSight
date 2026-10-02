import { create } from 'zustand';

export type ModelSelection =
  | { source: 'system'; model_id: string; effort?: string }
  | { source: 'custom'; base_url: string; api_key: string; model: string; effort?: string; context_acknowledged: true };

export type ModelTestSelection =
  | Extract<ModelSelection, { source: 'system' }>
  | (Omit<Extract<ModelSelection, { source: 'custom' }>, 'context_acknowledged'> & { context_acknowledged?: boolean });

export interface ModelCapabilities {
  provider: string;
  label: string;
  icon_url: string | null;
  effort_options: string[];
  default_effort: string | null;
  docs_url: string | null;
}

export interface CatalogModel extends ModelCapabilities {
  id: string;
  model: string;
  available: boolean;
}

interface ModelSelectionState {
  selection: ModelSelection | null;
  metadata: ModelCapabilities | null;
  catalog: CatalogModel[];
  setCatalog: (models: CatalogModel[]) => void;
  applySelection: (selection: ModelSelection, metadata: ModelCapabilities) => void;
  clearSelection: () => void;
}

// Deliberately memory-only: a reload must discard custom credentials and selection.
// Keep this store separate from persisted conversation/preferences stores and devtools.
export const useModelSelectionStore = create<ModelSelectionState>((set) => ({
  selection: null,
  metadata: null,
  catalog: [],
  setCatalog: (catalog) => set({ catalog }),
  applySelection: (selection, metadata) => {
    if (selection.source === 'custom' && selection.context_acknowledged !== true) return;
    set({ selection, metadata });
  },
  clearSelection: () => set({ selection: null, metadata: null }),
}));

export function validateCustomModelSelection(
  selection: Extract<ModelTestSelection, { source: 'custom' }>,
): string | null {
  const invalidUrl = '请输入完整的公共 HTTPS API 地址。';
  try {
    if (selection.base_url.length > 2048) return invalidUrl;
    const url = new URL(selection.base_url.trim());
    if (url.protocol !== 'https:' || !url.hostname) return invalidUrl;
    if (url.port && url.port !== '443') return 'API 地址仅支持默认 HTTPS 端口 443。';
    if (url.username || url.password || url.search || url.hash) {
      return 'API 地址不能包含登录信息、查询参数或片段。';
    }
    const host = url.hostname.toLowerCase().replace(/\.$/, '').replace(/^\[|\]$/g, '');
    const octets = /^\d+\.\d+\.\d+\.\d+$/.test(host) ? host.split('.').map(Number) : null;
    const localIpv4 = octets && (
      [0, 10, 127].includes(octets[0]) || octets[0] >= 224
      || (octets[0] === 100 && octets[1] >= 64 && octets[1] <= 127)
      || (octets[0] === 169 && octets[1] === 254)
      || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31)
      || (octets[0] === 192 && octets[1] === 168)
    );
    const localIpv6 = host.includes(':') && /^(?:f[cd]|fe[89ab]|ff|::|2001:db8:)/.test(host);
    if (localIpv4 || localIpv6 || host === 'localhost' || /\.(?:local|internal|localhost)$/.test(host)
      || (!host.includes('.') && !host.includes(':'))) {
      return 'API 地址必须指向公共网络，不能使用本机或内网地址。';
    }
    // The backend also checks DNS results before connecting to user-supplied hosts.
  } catch {
    return invalidUrl;
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$/.test(selection.model.trim())) {
    return '请输入有效的模型 ID，使用供应商提供的英文名称（最多 200 个字符）。';
  }
  if (!selection.api_key.trim()) return '请输入自定义模型的 API Key。';
  if (selection.api_key.length > 4096 || /[^\x20-\x7e]/.test(selection.api_key)) {
    return 'API Key 格式不正确，请检查是否包含换行或非英文字符。';
  }
  return null;
}

export const MODEL_SELECTION_HEADER = 'X-FinSight-Model';

export function getModelSelectionHeaders(): Record<string, string> {
  const { selection } = useModelSelectionStore.getState();
  if (!selection) return {};
  const bytes = new TextEncoder().encode(JSON.stringify(selection));
  const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
  return { [MODEL_SELECTION_HEADER]: btoa(binary) };
}
