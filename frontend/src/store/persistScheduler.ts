/**
 * 会话持久化去抖调度器（FE-01）。
 *
 * 流式回复期间每个 token 都会触发一次消息更新，若每次都全量序列化写
 * localStorage 会阻塞主线程（100 条消息 × 每秒多次）。本模块把"写盘"收敛为：
 *   - schedulePersist：同一 key 的写盘请求在 delayMs 内合并，只执行最后一次
 *   - flushPersist：立即执行 pending 的写盘（切会话 / 流结束 / beforeunload）
 *   - cancelPersist：丢弃 pending 写盘（删除会话时防止"删后又写回"）
 *
 * 纯调度逻辑，不触碰 localStorage —— 由调用方通过 flush 回调决定写什么。
 */

const PERSIST_DEBOUNCE_MS = 500;

const timers = new Map<string, ReturnType<typeof setTimeout>>();
const pendingFlush = new Map<string, () => void>();

export function schedulePersist(key: string, flush: () => void, delayMs: number = PERSIST_DEBOUNCE_MS): void {
  const existing = timers.get(key);
  if (existing) clearTimeout(existing);
  pendingFlush.set(key, flush);
  timers.set(
    key,
    setTimeout(() => {
      timers.delete(key);
      pendingFlush.delete(key);
      flush();
    }, delayMs),
  );
}

/** 立即执行 pending 写盘。不传 key 则 flush 全部（beforeunload 场景）。 */
export function flushPersist(key?: string): void {
  const keys = key !== undefined ? [key] : [...timers.keys()];
  for (const k of keys) {
    const timer = timers.get(k);
    if (timer) clearTimeout(timer);
    const flush = pendingFlush.get(k);
    timers.delete(k);
    pendingFlush.delete(k);
    if (flush) flush();
  }
}

/** 丢弃 pending 写盘（不执行回调）。删除会话时用，防止定时器把已删数据写回。 */
export function cancelPersist(key: string): void {
  const timer = timers.get(key);
  if (timer) clearTimeout(timer);
  timers.delete(key);
  pendingFlush.delete(key);
}

export function hasPendingPersist(key: string): boolean {
  return timers.has(key);
}
