import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { cancelPersist, flushPersist, hasPendingPersist, schedulePersist } from './persistScheduler';

describe('persistScheduler (FE-01 去抖)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    flushPersist(); // 清理跨用例残留
    vi.useRealTimers();
  });

  it('同一 key 连续 50 次调度只执行最后一次回调', () => {
    const calls: number[] = [];
    for (let i = 0; i < 50; i++) {
      schedulePersist('s1', () => calls.push(i));
    }
    expect(calls).toHaveLength(0); // 去抖窗口内不执行
    vi.advanceTimersByTime(600);
    expect(calls).toEqual([49]); // 只有最后一次
  });

  it('flushPersist 立即执行 pending 且清除定时器', () => {
    const calls: string[] = [];
    schedulePersist('s1', () => calls.push('flushed'));
    flushPersist('s1');
    expect(calls).toEqual(['flushed']);
    expect(hasPendingPersist('s1')).toBe(false);
    vi.advanceTimersByTime(600);
    expect(calls).toEqual(['flushed']); // 定时器已清，不重复执行
  });

  it('cancelPersist 丢弃 pending 不执行（删除会话防写回）', () => {
    const calls: string[] = [];
    schedulePersist('s1', () => calls.push('should-not-run'));
    cancelPersist('s1');
    vi.advanceTimersByTime(600);
    expect(calls).toHaveLength(0);
  });

  it('不同 key 互不影响；无参 flush 全部执行', () => {
    const calls: string[] = [];
    schedulePersist('a', () => calls.push('a'));
    schedulePersist('b', () => calls.push('b'));
    cancelPersist('a');
    flushPersist();
    expect(calls).toEqual(['b']);
  });
});
