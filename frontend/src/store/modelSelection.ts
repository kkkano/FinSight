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

export type CustomModelDraft = Omit<Extract<ModelSelection, { source: 'custom' }>, 'api_key' | 'context_acknowledged'>;

interface ModelSelectionState {
  userId: string | null;
  selection: ModelSelection | null;
  pendingCustom: CustomModelDraft | null;
  metadata: ModelCapabilities | null;
  catalog: CatalogModel[];
  defaultModelId: string | null;
  setUser: (userId: string | null) => void;
  setCatalog: (models: CatalogModel[], defaultModelId?: string | null) => void;
  applySelection: (selection: ModelSelection, metadata: ModelCapabilities) => void;
  clearSelection: () => void;
}

export const modelPreferenceKey = (userId: string): string => `finsight-model-preference:${encodeURIComponent(userId)}`;

type ModelPreference = Extract<ModelSelection, { source: 'system' }> | CustomModelDraft;

function readPreference(userId: string): ModelPreference | null {
  try {
    const value = JSON.parse(localStorage.getItem(modelPreferenceKey(userId)) || 'null');
    if (!value || typeof value !== 'object') return null;
    const effort = typeof value.effort === 'string' ? { effort: value.effort } : {};
    if (value.source === 'system' && typeof value.model_id === 'string' && value.model_id.trim()) {
      return { source: 'system', model_id: value.model_id, ...effort };
    }
    if (value.source === 'custom' && typeof value.base_url === 'string' && typeof value.model === 'string') {
      return { source: 'custom', base_url: value.base_url, model: value.model, ...effort };
    }
  } catch {
    // 存储不可用时，当前页面仍可使用已应用的模型。
  }
  return null;
}

function writePreference(userId: string | null, selection: ModelSelection | null): void {
  if (!userId) return;
  try {
    if (!selection) {
      localStorage.removeItem(modelPreferenceKey(userId));
      return;
    }
    // 自带模型只保存非敏感字段，密钥和授权确认不落盘。
    const preference: ModelPreference = selection.source === 'system'
      ? { source: 'system', model_id: selection.model_id, ...(selection.effort ? { effort: selection.effort } : {}) }
      : { source: 'custom', base_url: selection.base_url, model: selection.model, ...(selection.effort ? { effort: selection.effort } : {}) };
    localStorage.setItem(modelPreferenceKey(userId), JSON.stringify(preference));
  } catch {
    // 不因浏览器禁用存储而阻断当前请求。
  }
}

export const useModelSelectionStore = create<ModelSelectionState>((set, get) => ({
  userId: null,
  selection: null,
  pendingCustom: null,
  metadata: null,
  catalog: [],
  defaultModelId: null,
  setUser: (userId) => {
    if (get().userId === userId) return;
    const preference = userId ? readPreference(userId) : null;
    const selection = preference?.source === 'system' ? preference : null;
    const pendingCustom = preference?.source === 'custom' ? preference : null;
    const modelId = selection?.model_id || get().defaultModelId;
    set({ userId, selection, pendingCustom, metadata: pendingCustom ? null : get().catalog.find((model) => model.id === modelId) || null });
  },
  setCatalog: (catalog, defaultModelId) => {
    const state = get();
    const resolvedDefault = defaultModelId ?? state.defaultModelId;
    const modelId = state.selection?.source === 'system' ? state.selection.model_id : resolvedDefault;
    set({ catalog, defaultModelId: resolvedDefault,
      ...(state.selection?.source !== 'custom' && !state.pendingCustom ? { metadata: catalog.find((model) => model.id === modelId) || null } : {}),
    });
  },
  applySelection: (selection, metadata) => {
    if (selection.source === 'custom' && selection.context_acknowledged !== true) return;
    writePreference(get().userId, selection);
    set({ selection, pendingCustom: null, metadata });
  },
  clearSelection: () => {
    writePreference(get().userId, null);
    set({ selection: null, pendingCustom: null, metadata: get().catalog.find((model) => model.id === get().defaultModelId) || null });
  },
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

export class ModelSelectionRequiredError extends Error {
  constructor() {
    super('自带模型的密钥未保存。请在模型设置中重新填写 API Key、测试并应用，或明确选择内置模型。');
    this.name = 'ModelSelectionRequiredError';
  }
}

export function getModelSelectionHeaders(): Record<string, string> {
  const { selection, pendingCustom } = useModelSelectionStore.getState();
  if (pendingCustom) throw new ModelSelectionRequiredError();
  if (!selection) return {};
  const bytes = new TextEncoder().encode(JSON.stringify(selection));
  const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
  return { [MODEL_SELECTION_HEADER]: btoa(binary) };
}
