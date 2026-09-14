import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import type { Message } from '../types';
import { findRetryQuery } from './useChatStream';

const messages: Message[] = [
  { id: 'u1', role: 'user', content: 'AAPL first', timestamp: 1 },
  { id: 'a1', role: 'assistant', content: 'first answer', timestamp: 2 },
  { id: 'u2', role: 'user', content: 'NVDA second', timestamp: 3 },
  { id: 'a2', role: 'assistant', content: 'second answer', timestamp: 4 },
];

describe('findRetryQuery', () => {
  it('为 assistant 重试复用它前面的最近一条 user query', () => {
    expect(findRetryQuery(messages, 'a1')).toBe('AAPL first');
    expect(findRetryQuery(messages, 'a2')).toBe('NVDA second');
  });

  it('目标消息不存在时不猜测 query', () => {
    expect(findRetryQuery(messages, 'missing')).toBeNull();
  });
});

describe('SSE 异步终态竞态契约', () => {
  it('主聊天在流返回后等待 onError 的异步恢复逻辑', () => {
    const source = readFileSync(new URL('./useChatStream.ts', import.meta.url), 'utf8');

    expect(source).toContain('terminalHandlingPromise =');
    expect(source).toContain('const pendingTerminalHandling = terminalHandlingPromise;');
    expect(source).toContain('if (pendingTerminalHandling) await pendingTerminalHandling;');
  });
});
