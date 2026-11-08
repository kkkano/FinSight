import type { ConversationSummary } from '../store/useStore';

export function groupConversations(conversations: ConversationSummary[], now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  const groups = ['今天', '昨天', '7天内', '更早'].map((label) => ({ label, items: [] as ConversationSummary[] }));
  for (const conversation of [...conversations].filter((item) => item.messageCount > 0).sort((a, b) => b.updatedAt - a.updatedAt)) {
    const age = today - conversation.updatedAt;
    groups[age <= 0 ? 0 : age <= day ? 1 : age < 7 * day ? 2 : 3].items.push(conversation);
  }
  return groups.filter((group) => group.items.length);
}

type ConversationGroup = ReturnType<typeof groupConversations>[number];

export function cleanConversationTitle(title: string): string {
  return title.replace(/\s*(?:（\d{4}[-/.]\d{1,2}[-/.]\d{1,2}）|\(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\))\s*$/, '').trim() || '新对话';
}

export function conversationTimeHint(conversation: ConversationSummary, group: ConversationGroup): string | null {
  const title = cleanConversationTitle(conversation.title);
  const matching = group.items.filter((item) => cleanConversationTitle(item.title) === title);
  if (matching.length < 2) return null;

  const date = new Date(conversation.updatedAt);
  const sharesDate = matching.some((item) => item.sessionId !== conversation.sessionId
    && new Date(item.updatedAt).toDateString() === date.toDateString());
  const twoDigits = (value: number) => String(value).padStart(2, '0');
  return sharesDate
    ? `${twoDigits(date.getHours())}:${twoDigits(date.getMinutes())}`
    : `${twoDigits(date.getMonth() + 1)}/${twoDigits(date.getDate())}`;
}

export function recentConversationView(
  groups: ConversationGroup[],
  selectedSessionId: string,
  collapsedGroups: Readonly<Record<string, boolean>>,
  limit = 8,
) {
  let remaining = limit;
  const recentGroups = groups.flatMap((group) => {
    const items = group.items.slice(0, remaining);
    remaining -= items.length;
    return items.length ? [{ ...group, items, count: group.items.length }] : [];
  });
  const selected = groups.flatMap((group) => group.items).find((item) => item.sessionId === selectedSessionId);
  const selectedIsVisible = recentGroups.some((group) => !collapsedGroups[group.label]
    && group.items.some((item) => item.sessionId === selectedSessionId));

  return {
    groups: recentGroups,
    totalCount: groups.reduce((total, group) => total + group.items.length, 0),
    pinnedConversation: selected && !selectedIsVisible ? selected : null,
  };
}

export function conversationStatus(conversation: ConversationSummary): { value: string; label: string } {
  if (['failed', 'interrupted', 'persistence_failed'].includes(conversation.runStatus || '')) return { value: 'failed', label: '失败' };
  if (conversation.runStatus === 'running') return { value: 'running', label: '进行中' };
  if (conversation.answerStatus === 'partial' || ['partial', 'cancelled'].includes(conversation.runStatus || '')) return { value: 'partial', label: '部分完成' };
  if (conversation.runStatus === 'completed') return { value: 'completed', label: '完成' };
  return { value: 'saved', label: '已保存' };
}
