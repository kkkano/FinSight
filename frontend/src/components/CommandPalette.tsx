import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import type { FC, KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MessageSquarePlus,
  LayoutDashboard,
  Gauge,
  Moon,
  Sun,
  Search,
} from 'lucide-react';
import { useStore } from '../store/useStore';

/** 命令面板中的操作项定义 */
interface CommandAction {
  /** 唯一标识 */
  id: string;
  /** 显示标签 */
  label: string;
  /** lucide-react 图标组件 */
  icon: FC<{ size?: number; className?: string }>;
  /** 快捷键提示文本 */
  shortcut?: string;
  /** 执行该操作的回调 */
  execute: () => void;
}

interface CommandPaletteProps {
  /** 面板是否可见 */
  isOpen: boolean;
  /** 关闭面板的回调 */
  onClose: () => void;
}

/**
 * 命令面板组件
 *
 * 通过 Ctrl+K / Cmd+K 打开，提供快速操作入口。
 * 支持搜索过滤、方向键导航和 Enter 选择。
 */
export const CommandPalette: FC<CommandPaletteProps> = ({ isOpen, onClose }) => {
  const navigate = useNavigate();
  const { theme, setTheme } = useStore();

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 定义可用的快捷操作列表
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
        shortcut: '',
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
        label: '切换暗色模式',
        icon: theme === 'dark' ? Sun : Moon,
        execute: () => {
          setTheme(theme === 'dark' ? 'light' : 'dark');
          onClose();
        },
      },
    ],
    [navigate, onClose, theme, setTheme],
  );

  // 根据搜索文本过滤操作列表
  const filteredActions = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return actions;
    return actions.filter((action) => action.label.toLowerCase().includes(normalized));
  }, [actions, query]);

  // 当过滤结果变化时重置选中索引
  useEffect(() => {
    setActiveIndex(0);
  }, [filteredActions.length]);

  // 打开时聚焦输入框并重置状态
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setActiveIndex(0);
      // 等待 DOM 渲染完成后聚焦
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }
  }, [isOpen]);

  // 执行选中的操作
  const executeAction = useCallback(
    (action: CommandAction) => {
      action.execute();
    },
    [],
  );

  // 键盘导航处理（方向键 + Enter）
  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      switch (event.key) {
        case 'ArrowDown': {
          event.preventDefault();
          setActiveIndex((prev) =>
            prev < filteredActions.length - 1 ? prev + 1 : 0,
          );
          break;
        }
        case 'ArrowUp': {
          event.preventDefault();
          setActiveIndex((prev) =>
            prev > 0 ? prev - 1 : filteredActions.length - 1,
          );
          break;
        }
        case 'Enter': {
          event.preventDefault();
          const target = filteredActions[activeIndex];
          if (target) {
            executeAction(target);
          }
          break;
        }
        default:
          break;
      }
    },
    [filteredActions, activeIndex, executeAction],
  );

  // 滚动活跃项到可见区域
  useEffect(() => {
    if (!listRef.current) return;
    const activeElement = listRef.current.querySelector<HTMLElement>(
      `[data-command-index="${activeIndex}"]`,
    );
    activeElement?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  // 点击遮罩层关闭面板
  const handleOverlayClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) {
        onClose();
      }
    },
    [onClose],
  );

  if (!isOpen) return null;

  // 检测平台以显示正确的修饰键提示
  const modKey =
    typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.userAgent)
      ? '\u2318'
      : 'Ctrl';

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center pt-[20vh]"
      onClick={handleOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-label="命令面板"
    >
      {/* 面板容器 - 缩放动画入场 */}
      <div
        className="bg-fin-card border border-fin-border rounded-xl w-full max-w-lg shadow-2xl
                   animate-in fade-in zoom-in-95 duration-150 overflow-hidden"
        style={{
          animation: 'commandPaletteIn 150ms ease-out',
        }}
      >
        {/* 搜索输入区域 */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-fin-border">
          <Search size={18} className="text-fin-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="搜索命令..."
            aria-label="搜索命令"
            className="flex-1 bg-transparent text-fin-text text-sm placeholder:text-fin-muted
                       outline-none border-none"
          />
          <kbd className="hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded border
                         border-fin-border text-[10px] text-fin-muted font-mono">
            ESC
          </kbd>
        </div>

        {/* 操作列表 */}
        <div ref={listRef} className="max-h-64 overflow-y-auto py-2" role="listbox">
          {filteredActions.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-fin-muted">
              没有匹配的命令
            </div>
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
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors
                             rounded-lg mx-auto cursor-pointer
                             ${isActive
                               ? 'bg-fin-primary/10 text-fin-primary'
                               : 'text-fin-text hover:bg-fin-hover'
                             }`}
                >
                  <Icon size={16} className="shrink-0" />
                  <span className="flex-1 text-left">{action.label}</span>
                  {action.shortcut && (
                    <kbd className="text-[10px] text-fin-muted font-mono border border-fin-border
                                   px-1.5 py-0.5 rounded">
                      {action.shortcut}
                    </kbd>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* 底部快捷键提示 */}
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
      </div>

      {/* 内联关键帧动画定义 */}
      <style>{`
        @keyframes commandPaletteIn {
          from {
            opacity: 0;
            transform: scale(0.95) translateY(-8px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
      `}</style>
    </div>
  );
};
