/**
 * Toast 通知组件系统
 *
 * 提供全局 Toast 通知能力，包括：
 * - ToastProvider：上下文提供者，管理通知队列状态
 * - ToastContainer：渲染活跃通知（固定在右下角）
 * - useToast：自定义 Hook，暴露 toast / dismiss 方法
 *
 * 支持 success / error / warning / info 四种类型，
 * 自动消失（默认 5 秒）、最多显示 3 条、溢出排队。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

/* ------------------------------------------------------------------ */
/*  类型定义                                                            */
/* ------------------------------------------------------------------ */

/** Toast 通知类型 */
type ToastType = 'success' | 'error' | 'warning' | 'info';

/** 创建 Toast 的参数 */
interface ToastOptions {
  /** 通知类型 */
  type: ToastType;
  /** 通知标题 */
  title: string;
  /** 可选的详细描述 */
  message?: string;
  /** 自动关闭时长（毫秒），默认 5000。设为 0 则不自动关闭 */
  duration?: number;
}

/** 内部 Toast 数据结构（带唯一 ID 与消失状态） */
interface ToastItem extends ToastOptions {
  /** 唯一标识 */
  id: string;
  /** 是否正在执行退出动画 */
  dismissing: boolean;
}

/** useToast Hook 返回值 */
interface UseToastReturn {
  /** 显示一条 Toast 通知 */
  toast: (options: ToastOptions) => string;
  /** 手动关闭指定 Toast */
  dismiss: (id: string) => void;
}

/* ------------------------------------------------------------------ */
/*  常量                                                                */
/* ------------------------------------------------------------------ */

/** 同时可见的最大 Toast 数量 */
const MAX_VISIBLE = 3;

/** 默认自动关闭时长（毫秒） */
const DEFAULT_DURATION = 5000;

/** 退出动画时长（毫秒），与 Tailwind animate-fade-out 保持一致 */
const EXIT_ANIMATION_MS = 250;

/* ------------------------------------------------------------------ */
/*  样式映射                                                            */
/* ------------------------------------------------------------------ */

/** 不同类型对应的颜色样式 */
const typeStyles: Record<ToastType, { accent: string; icon: string }> = {
  success: {
    accent: 'border-l-emerald-500',
    icon: 'text-fin-success',
  },
  error: {
    accent: 'border-l-red-500',
    icon: 'text-fin-danger',
  },
  warning: {
    accent: 'border-l-amber-500',
    icon: 'text-fin-warning',
  },
  info: {
    accent: 'border-l-blue-500',
    icon: 'text-fin-primary',
  },
};

/** 不同类型的 SVG 图标路径 */
const typeIcons: Record<ToastType, string> = {
  success:
    'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  error:
    'M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z',
  warning:
    'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z',
  info:
    'M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z',
};

/* ------------------------------------------------------------------ */
/*  Context                                                            */
/* ------------------------------------------------------------------ */

const ToastContext = createContext<UseToastReturn | null>(null);

/* ------------------------------------------------------------------ */
/*  自增 ID 生成器                                                       */
/* ------------------------------------------------------------------ */

let nextId = 0;

function generateId(): string {
  nextId += 1;
  return `toast-${nextId}`;
}

/* ------------------------------------------------------------------ */
/*  ToastProvider                                                      */
/* ------------------------------------------------------------------ */

interface ToastProviderProps {
  children: ReactNode;
}

/**
 * Toast 上下文提供者
 *
 * 在应用最外层包裹此组件，即可在任意子组件中使用 useToast()。
 * 内部维护一个通知队列，最多同时显示 MAX_VISIBLE 条，
 * 超出部分排队等待。
 */
function ToastProvider({ children }: ToastProviderProps) {
  /** 完整通知队列（包含可见与排队中的） */
  const [queue, setQueue] = useState<readonly ToastItem[]>([]);

  /** 存储每条 Toast 的自动关闭定时器 */
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );

  /* ---------- 清理所有定时器（组件卸载时） ---------- */
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
    };
  }, []);

  /* ---------- dismiss：触发退出动画并移除 ---------- */
  const dismiss = useCallback((id: string) => {
    /* 先清除自动关闭定时器（避免重复触发） */
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }

    /* 标记为 dismissing（播放退出动画） */
    setQueue((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, dismissing: true } : item,
      ),
    );

    /* 等动画结束后真正移除 */
    setTimeout(() => {
      setQueue((prev) => prev.filter((item) => item.id !== id));
    }, EXIT_ANIMATION_MS);
  }, []);

  /* ---------- toast：添加一条新通知 ---------- */
  const toast = useCallback(
    (options: ToastOptions): string => {
      const id = generateId();
      const duration = options.duration ?? DEFAULT_DURATION;

      const newItem: ToastItem = {
        ...options,
        id,
        dismissing: false,
      };

      setQueue((prev) => [...prev, newItem]);

      /* 设置自动关闭定时器（duration 为 0 时不自动关闭） */
      if (duration > 0) {
        const timer = setTimeout(() => {
          dismiss(id);
        }, duration);
        timersRef.current.set(id, timer);
      }

      return id;
    },
    [dismiss],
  );

  /* ---------- 对外暴露的值 ---------- */
  const contextValue = useMemo<UseToastReturn>(
    () => ({ toast, dismiss }),
    [toast, dismiss],
  );

  /* 仅取前 MAX_VISIBLE 条作为可见列表 */
  const visibleToasts = queue.slice(0, MAX_VISIBLE);

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <ToastContainer toasts={visibleToasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

/* ------------------------------------------------------------------ */
/*  useToast Hook                                                      */
/* ------------------------------------------------------------------ */

/**
 * 获取 Toast 通知方法
 *
 * @example
 * ```tsx
 * const { toast, dismiss } = useToast();
 * toast({ type: 'success', title: '操作成功' });
 * ```
 */
function useToast(): UseToastReturn {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast 必须在 ToastProvider 内部使用');
  }
  return ctx;
}

/* ------------------------------------------------------------------ */
/*  ToastContainer                                                     */
/* ------------------------------------------------------------------ */

interface ToastContainerProps {
  toasts: readonly ToastItem[];
  onDismiss: (id: string) => void;
}

/**
 * Toast 容器
 *
 * 固定在视窗右下角，渲染当前可见的通知列表。
 */
function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div
      aria-live="polite"
      aria-label="通知列表"
      className="fixed bottom-4 right-4 z-50 flex flex-col-reverse gap-2 w-80 pointer-events-none"
    >
      {toasts.map((item) => (
        <ToastCard key={item.id} item={item} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ToastCard（单条通知卡片）                                             */
/* ------------------------------------------------------------------ */

interface ToastCardProps {
  item: ToastItem;
  onDismiss: (id: string) => void;
}

/**
 * 单条 Toast 卡片
 *
 * 左侧带彩色边线标识类型，右上角关闭按钮，
 * 进入时 slide-in-right 动画，退出时 fade-out 动画。
 */
function ToastCard({ item, onDismiss }: ToastCardProps) {
  const style = typeStyles[item.type];
  const iconPath = typeIcons[item.type];

  const animationClass = item.dismissing
    ? 'animate-fade-out'
    : 'animate-slide-in-right';

  return (
    <div
      role="alert"
      className={`
        pointer-events-auto
        flex items-start gap-3 p-3
        bg-fin-card border border-fin-border rounded-lg
        border-l-[3px] ${style.accent}
        shadow-lg shadow-black/10
        ${animationClass}
      `.trim()}
    >
      {/* 类型图标 */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className={`w-5 h-5 shrink-0 mt-0.5 ${style.icon}`}
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d={iconPath} />
      </svg>

      {/* 文本内容 */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-fin-text leading-snug">
          {item.title}
        </p>
        {item.message && (
          <p className="mt-0.5 text-2xs text-fin-text-secondary leading-relaxed">
            {item.message}
          </p>
        )}
      </div>

      {/* 关闭按钮 */}
      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        aria-label="关闭通知"
        className="
          shrink-0 p-0.5 rounded
          text-fin-muted hover:text-fin-text
          transition-colors duration-150
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-fin-primary/50
        "
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
          className="w-4 h-4"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M6 18L18 6M6 6l12 12"
          />
        </svg>
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  导出                                                                */
/* ------------------------------------------------------------------ */

// eslint-disable-next-line react-refresh/only-export-components -- useToast 与 ToastProvider 共享 Context，合并导出是合理设计
export { ToastProvider, ToastContainer, useToast };
export type { ToastType, ToastOptions, ToastItem, UseToastReturn };
