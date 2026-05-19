import { describe, expect, it } from 'vitest';

import { isCommandPaletteShortcut, isRightPanelShortcut } from './useKeyboardShortcuts';

describe('keyboard shortcut predicates', () => {
  it('recognizes Ctrl/Cmd+K regardless of keyboard event key casing', () => {
    expect(isCommandPaletteShortcut({ key: 'k', ctrlKey: true, metaKey: false })).toBe(true);
    expect(isCommandPaletteShortcut({ key: 'K', ctrlKey: true, metaKey: false })).toBe(true);
    expect(isCommandPaletteShortcut({ key: 'K', ctrlKey: false, metaKey: true })).toBe(true);
  });

  it('recognizes Ctrl+/ for the right panel toggle', () => {
    expect(isRightPanelShortcut({ key: '/', ctrlKey: true })).toBe(true);
    expect(isRightPanelShortcut({ key: '?', ctrlKey: true })).toBe(true);
    expect(isRightPanelShortcut({ key: '/', ctrlKey: false })).toBe(false);
  });
});
