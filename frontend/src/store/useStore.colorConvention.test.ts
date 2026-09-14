import { afterEach, describe, expect, it, vi } from 'vitest';

import { useStore } from './useStore';

describe('useStore color convention', () => {
  afterEach(() => {
    useStore.getState().setColorConvention('intl');
    vi.unstubAllGlobals();
  });

  it('persists the choice and toggles the cn-colors root class', () => {
    const toggle = vi.fn();
    const setItem = vi.fn();
    vi.stubGlobal('document', { documentElement: { classList: { toggle } } });
    vi.stubGlobal('window', { localStorage: { setItem } });

    useStore.getState().setColorConvention('cn');

    expect(useStore.getState().colorConvention).toBe('cn');
    expect(toggle).toHaveBeenCalledWith('cn-colors', true);
    expect(setItem).toHaveBeenCalledWith('finsight-color-convention', 'cn');
  });
});
