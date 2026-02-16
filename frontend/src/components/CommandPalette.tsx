import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import type { FC, KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquarePlus, LayoutDashboard, Gauge, Moon, Sun, Search } from 'lucide-react';
import { useStore } from '../store/useStore';
import { Dialog } from './ui/Dialog';

interface CommandAction {
  id: string;
  label: string;
  icon: FC<{ size?: number; className?: string }>;
  shortcut?: string;
  execute: () => void;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CommandPalette: FC<CommandPaletteProps> = ({ isOpen, onClose }) => {
  const navigate = useNavigate();
  const { theme, setTheme } = useStore();

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const actions: CommandAction[] = useMemo(
    () => [
      {
        id: 'new-chat',
        label: '新建对话',
        icon: MessageSquarePlus,
        execute: () => {
          navigate('/chat');
          onClose();
        },
      },
      {
        id: 'open-workbench',
        label: '打开工作台',
        icon: LayoutDashboard,
        execute: () => {
          navigate('/workbench');
          onClose();
        },
      },
      {
        id: 'open-dashboard',
        label: '打开仪表盘',
        icon: Gauge,
        execute: () => {
          navigate('/dashboard');
          onClose();
        },
      },
      {
        id: 'toggle-dark-mode',
        label: '切换明暗主题',
        icon: theme === 'dark' ? Sun : Moon,
        execute: () => {
          setTheme(theme === 'dark' ? 'light' : 'dark');
          onClose();
        },
      },
    ],
    [navigate, onClose, theme, setTheme],
  );

  const filteredActions = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return actions;
    return actions.filter((action) => action.label.toLowerCase().includes(normalized));
  }, [actions, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [filteredActions.length]);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setActiveIndex(0);
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }
  }, [isOpen]);

  const executeAction = useCallback((action: CommandAction) => {
    action.execute();
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          setActiveIndex((prev) => (prev < filteredActions.length - 1 ? prev + 1 : 0));
          return;
        case 'ArrowUp':
          event.preventDefault();
          setActiveIndex((prev) => (prev > 0 ? prev - 1 : filteredActions.length - 1));
          return;
        case 'Enter': {
          event.preventDefault();
          const target = filteredActions[activeIndex];
          if (target) executeAction(target);
          return;
        }
        default:
          return;
      }
    },
    [filteredActions, activeIndex, executeAction],
  );

  useEffect(() => {
    if (!listRef.current) return;
    const activeElement = listRef.current.querySelector<HTMLElement>(`[data-command-index="${activeIndex}"]`);
    activeElement?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const modKey =
    typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.userAgent)
      ? '⌘'
      : 'Ctrl';

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      labelledBy="command-palette-title"
      overlayClassName="items-start pt-[20vh]"
      panelClassName="bg-fin-card border border-fin-border rounded-xl w-full max-w-lg shadow-2xl overflow-hidden"
    >
      <h2 id="command-palette-title" className="sr-only">
        命令面板
      </h2>

      <div className="flex items-center gap-3 px-4 py-3 border-b border-fin-border">
        <Search size={18} className="text-fin-muted shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="搜索命令..."
          aria-label="搜索命令"
          className="flex-1 bg-transparent text-fin-text text-sm placeholder:text-fin-muted outline-none border-none"
        />
        <kbd className="hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-fin-border text-[10px] text-fin-muted font-mono">
          ESC
        </kbd>
      </div>

      <div ref={listRef} className="max-h-64 overflow-y-auto py-2" role="listbox">
        {filteredActions.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-fin-muted">没有匹配的命令</div>
        ) : (
          filteredActions.map((action, index) => {
            const isActive = index === activeIndex;
            const Icon = action.icon;
            return (
              <button
                key={action.id}
                data-command-index={index}
                role="option"
                aria-selected={isActive}
                onClick={() => executeAction(action)}
                onMouseEnter={() => setActiveIndex(index)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors rounded-lg mx-auto cursor-pointer ${
                  isActive ? 'bg-fin-primary/10 text-fin-primary' : 'text-fin-text hover:bg-fin-hover'
                }`}
              >
                <Icon size={16} className="shrink-0" />
                <span className="flex-1 text-left">{action.label}</span>
                {action.shortcut && (
                  <kbd className="text-[10px] text-fin-muted font-mono border border-fin-border px-1.5 py-0.5 rounded">
                    {action.shortcut}
                  </kbd>
                )}
              </button>
            );
          })
        )}
      </div>

      <div className="flex items-center gap-4 px-4 py-2 border-t border-fin-border text-[10px] text-fin-muted">
        <span className="flex items-center gap-1">
          <kbd className="px-1 py-0.5 rounded border border-fin-border font-mono">&uarr;&darr;</kbd>
          导航
        </span>
        <span className="flex items-center gap-1">
          <kbd className="px-1 py-0.5 rounded border border-fin-border font-mono">Enter</kbd>
          选择
        </span>
        <span className="flex items-center gap-1">
          <kbd className="px-1 py-0.5 rounded border border-fin-border font-mono">{modKey}+K</kbd>
          切换
        </span>
      </div>
    </Dialog>
  );
};
