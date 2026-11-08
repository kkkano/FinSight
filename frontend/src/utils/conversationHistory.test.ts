import { describe, expect, it } from 'vitest';
import { conversationStatus, groupConversations } from './conversationHistory';

const conversation = (updatedAt: number, extra = {}) => ({ sessionId: String(updatedAt), title: 'AAPL 研究', lastMessagePreview: '',
  messageCount: 2, createdAt: updatedAt, updatedAt, ...extra });

describe('conversation history', () => {
  it('groups real conversations by local calendar day and excludes empty placeholders', () => {
    const now = new Date(2026, 10, 7, 12);
    const groups = groupConversations([conversation(+now), conversation(+new Date(2026, 10, 6, 13)),
      conversation(+new Date(2026, 10, 3)), conversation(+new Date(2026, 9, 1)), conversation(+now, { messageCount: 0 })], now);
    expect(groups.map((group) => group.label)).toEqual(['今天', '昨天', '7天内', '更早']);
    expect(groups.every((group) => group.items.length === 1)).toBe(true);
  });
  it('does not invent a completed status for old records without a terminal status', () => {
    expect(conversationStatus(conversation(1)).label).toBe('已保存');
    expect(conversationStatus(conversation(1, { runStatus: 'completed', answerStatus: 'partial' })).label).toBe('部分完成');
    expect(conversationStatus(conversation(1, { runStatus: 'failed' })).label).toBe('失败');
  });
});
