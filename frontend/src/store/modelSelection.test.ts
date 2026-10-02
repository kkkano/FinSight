import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getModelSelectionHeaders,
  MODEL_SELECTION_HEADER,
  useModelSelectionStore,
  validateCustomModelSelection,
} from './modelSelection';
import type { ModelCapabilities, ModelSelection } from './modelSelection';
import { useStore } from './useStore';

const metadata: ModelCapabilities = {
  provider: 'stepfun', label: 'Step 5 Preview', icon_url: '/model-icons/stepfun.png',
  effort_options: ['low', 'medium', 'high'], default_effort: 'medium', docs_url: null,
};

const custom: Extract<ModelSelection, { source: 'custom' }> = {
  source: 'custom', base_url: 'https://测试.example.com/v1', api_key: 'test-only-secret', model: 'test-model',
  context_acknowledged: true,
};

function decodeHeader(): unknown {
  const binary = atob(getModelSelectionHeaders()[MODEL_SELECTION_HEADER]);
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, (character) => character.charCodeAt(0))));
}

afterEach(() => {
  useModelSelectionStore.getState().clearSelection();
  useStore.getState().setAuthIdentity(null);
  vi.unstubAllGlobals();
});

describe('request-scoped model selection', () => {
  it('keeps credentials in memory and encodes UTF-8 JSON in the header', () => {
    const localWrite = vi.fn();
    const sessionWrite = vi.fn();
    vi.stubGlobal('localStorage', { setItem: localWrite });
    vi.stubGlobal('sessionStorage', { setItem: sessionWrite });
    vi.stubGlobal('window', { localStorage: { setItem: localWrite }, sessionStorage: { setItem: sessionWrite } });

    expect(getModelSelectionHeaders()).toEqual({});
    useModelSelectionStore.getState().applySelection(custom, metadata);
    expect(decodeHeader()).toEqual(custom);
    expect(localWrite).not.toHaveBeenCalled();
    expect(sessionWrite).not.toHaveBeenCalled();
    expect(useModelSelectionStore.getInitialState().selection).toBeNull();
  });

  it('replaces custom credentials completely when applying a built-in model', () => {
    const store = useModelSelectionStore.getState();
    store.applySelection(custom, metadata);
    store.applySelection({ source: 'system', model_id: 'stepfun:step-5-preview', effort: 'medium' }, metadata);

    expect(decodeHeader()).toEqual({ source: 'system', model_id: 'stepfun:step-5-preview', effort: 'medium' });
    expect(JSON.stringify(useModelSelectionStore.getState())).not.toContain(custom.api_key);
    store.clearSelection();
    expect(getModelSelectionHeaders()).toEqual({});
  });

  it('refuses to apply a custom selection without the explicit context acknowledgement', () => {
    useModelSelectionStore.getState().applySelection({ ...custom, context_acknowledged: false } as unknown as ModelSelection, metadata);
    expect(getModelSelectionHeaders()).toEqual({});
  });

  it('clears credentials and explicit selection on logout and account changes', () => {
    const auth = useStore.getState();
    auth.setAuthIdentity({ userId: 'fixture-user-a', email: null });
    useModelSelectionStore.getState().applySelection(custom, metadata);
    auth.setAuthIdentity({ userId: 'fixture-user-a', email: null });
    expect(decodeHeader()).toEqual(custom);
    auth.setAuthIdentity({ userId: 'fixture-user-b', email: null });
    expect(getModelSelectionHeaders()).toEqual({});
    useModelSelectionStore.getState().applySelection(custom, metadata);
    auth.setAuthIdentity(null);
    expect(useModelSelectionStore.getState().selection).toBeNull();
    expect(JSON.stringify(useModelSelectionStore.getState())).not.toContain(custom.api_key);
  });

  it.each([
    ['base_url', 'api.example.com/v1'],
    ['base_url', 'http://api.example.com/v1'],
    ['base_url', 'https://api.example.com:8443/v1'],
    ['base_url', 'https://localhost/v1'],
    ['base_url', 'https://service.internal/v1'],
    ['base_url', 'https://127.0.0.1/v1'],
    ['base_url', 'https://192.168.1.1/v1'],
    ['base_url', 'https://[::1]/v1'],
    ['base_url', 'https://[fc00::1]/v1'],
    ['base_url', 'javascript:alert(1)'],
    ['base_url', 'https://name:password@api.example.com/v1'],
    ['base_url', 'https://api.example.com/v1?key=secret'],
    ['base_url', 'https://api.example.com/v1#secret'],
    ['model', ''],
    ['model', 'model name'],
    ['model', '测试模型'],
    ['model', 'm'.repeat(201)],
    ['api_key', '   '],
    ['api_key', 'key\nvalue'],
    ['api_key', 'key中文'],
  ])('rejects invalid %s input', (field, value) => {
    expect(validateCustomModelSelection({ ...custom, [field]: value })).toBeTruthy();
  });

  it('accepts a complete OpenAI-compatible configuration', () => {
    expect(validateCustomModelSelection(custom)).toBeNull();
    expect(validateCustomModelSelection({ ...custom, base_url: 'https://api.example.com:443/v1' })).toBeNull();
  });
});
