import { describe, expect, it } from 'vitest';
import { cleanConversationTitle, conversationStatus, conversationTimeHint, groupConversations, recentConversationView } from './conversationHistory';

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

describe('conversation display titles', () => {
  it('removes a trailing date in Chinese or ASCII parentheses only for display', () => {
    expect(cleanConversationTitle('特斯拉最新关键新闻（2026-11-05）')).toBe('特斯拉最新关键新闻');
    expect(cleanConversationTitle('特斯拉最新关键新闻 (2026/11/05) ')).toBe('特斯拉最新关键新闻');
    expect(cleanConversationTitle('特斯拉最新关键新闻（2026.11.05）')).toBe('特斯拉最新关键新闻');
  });

  it('retains non-date parentheses and dates within the title', () => {
    expect(cleanConversationTitle('苹果估值（市盈率 25）')).toBe('苹果估值（市盈率 25）');
    expect(cleanConversationTitle('苹果（2026-11-05）财报')).toBe('苹果（2026-11-05）财报');
    expect(cleanConversationTitle('')).toBe('新对话');
  });

  it('uses time to distinguish cleaned duplicate titles on the same day', () => {
    const items = [
      conversation(+new Date(2026, 10, 7, 10, 5), { title: '特斯拉新闻（2026-11-07）' }),
      conversation(+new Date(2026, 10, 7, 8, 30), { title: '特斯拉新闻（2026-11-06）' }),
      conversation(+new Date(2026, 10, 7, 7), { title: '苹果财报' }),
    ];
    const group = { label: '今天', items };
    expect(conversationTimeHint(items[0], group)).toBe('10:05');
    expect(conversationTimeHint(items[1], group)).toBe('08:30');
    expect(conversationTimeHint(items[2], group)).toBeNull();
    expect(items[0].title).toBe('特斯拉新闻（2026-11-07）');
  });

  it('uses month/day when matching titles are on different days of one group', () => {
    const items = [conversation(+new Date(2026, 9, 3)), conversation(+new Date(2026, 9, 1))];
    const group = { label: '更早', items };
    expect(conversationTimeHint(items[0], group)).toBe('10/03');
    expect(conversationTimeHint(items[1], group)).toBe('10/01');
  });
});

describe('recent conversation rail', () => {
  const now = new Date(2026, 10, 7, 12);
  const items = Array.from({ length: 12 }, (_, index) => conversation(
    +new Date(2026, 10, 7 - Math.floor(index / 4), 12 - index % 4), { sessionId: `session-${index}` },
  ));

  it('takes the first eight in grouped order and retains full counts without mutating history', () => {
    const originalOrder = [...items].reverse();
    const groups = groupConversations(originalOrder, now);
    const view = recentConversationView(groups, 'new-chat', {});
    expect(view.groups.flatMap((group) => group.items.map((item) => item.sessionId)))
      .toEqual(items.slice(0, 8).map((item) => item.sessionId));
    expect(view.totalCount).toBe(12);
    expect(groups.flatMap((group) => group.items)).toHaveLength(12);
    expect(originalOrder[0].sessionId).toBe('session-11');

    const oneGroup = recentConversationView([{ label: '今天', items }], 'new-chat', {});
    expect(oneGroup.groups[0].items).toHaveLength(8);
    expect(oneGroup.groups[0].count).toBe(12);
  });

  it('appends the selected conversation beyond the limit without displacing the first eight', () => {
    const view = recentConversationView(groupConversations(items, now), 'session-11', {});
    expect(view.groups.flatMap((group) => group.items)).toHaveLength(8);
    expect(view.pinnedConversation?.sessionId).toBe('session-11');
  });

  it('does not duplicate a selected conversation already in an expanded group', () => {
    const view = recentConversationView(groupConversations(items, now), 'session-2', {});
    expect(view.pinnedConversation).toBeNull();
  });

  it('keeps a selection in a collapsed group visible without reopening the group', () => {
    const collapsed = { 今天: true };
    const view = recentConversationView(groupConversations(items, now), 'session-2', collapsed);
    expect(view.pinnedConversation?.sessionId).toBe('session-2');
    expect(collapsed).toEqual({ 今天: true });
  });

  it('does not invent a row for a missing selection or an empty history', () => {
    expect(recentConversationView([], 'missing', {})).toEqual({ groups: [], totalCount: 0, pinnedConversation: null });
    expect(recentConversationView(groupConversations(items, now), 'missing', {}).pinnedConversation).toBeNull();
  });
});
