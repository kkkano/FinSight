import { useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';

interface KeyboardShortcutEvent {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
}

export const isCommandPaletteShortcut = (event: KeyboardShortcutEvent): boolean => {
  const isMod = Boolean(event.metaKey || event.ctrlKey);
  return isMod && String(event.key || '').toLowerCase() === 'k';
};

export const isRightPanelShortcut = (event: KeyboardShortcutEvent): boolean =>
  Boolean(event.ctrlKey) && ['/', '?'].includes(String(event.key || ''));

/**
 * 全局键盘快捷键 hook
 *
 * 支持的快捷键:
 * - Ctrl+K / Cmd+K: 打开命令面板
 * - Ctrl+/: 切换右侧面板可见性
 * - Escape: 关闭当前打开的命令面板
 */
export function useKeyboardShortcuts(handlers: {
  /** 打开/关闭命令面板的回调 */
  onToggleCommandPalette: () => void;
  /** 命令面板当前是否打开（用于 Escape 关闭判断） */
  isCommandPaletteOpen: boolean;
  /** 关闭命令面板的回调 */
  onCloseCommandPalette: () => void;
}): void {
  const toggleRightPanel = useStore((s) => s.toggleRightPanel);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Ctrl+K / Cmd+K: 切换命令面板
      if (isCommandPaletteShortcut(event)) {
        event.preventDefault();
        event.stopPropagation();
        handlers.onToggleCommandPalette();
        return;
      }

      // Ctrl+/ : 切换右侧面板显示
      if (isRightPanelShortcut(event)) {
        event.preventDefault();
        event.stopPropagation();
        toggleRightPanel();
        return;
      }

      // Escape: 关闭当前打开的命令面板
      if (event.key === 'Escape' && handlers.isCommandPaletteOpen) {
        event.preventDefault();
        event.stopPropagation();
        handlers.onCloseCommandPalette();
        return;
      }
    },
    [handlers, toggleRightPanel],
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleKeyDown]);
}
