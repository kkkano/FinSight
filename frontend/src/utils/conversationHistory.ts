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

export function conversationStatus(conversation: ConversationSummary): { value: string; label: string } {
  if (['failed', 'interrupted', 'persistence_failed'].includes(conversation.runStatus || '')) return { value: 'failed', label: '失败' };
  if (conversation.runStatus === 'running') return { value: 'running', label: '进行中' };
  if (conversation.answerStatus === 'partial' || ['partial', 'cancelled'].includes(conversation.runStatus || '')) return { value: 'partial', label: '部分完成' };
  if (conversation.runStatus === 'completed') return { value: 'completed', label: '完成' };
  return { value: 'saved', label: '已保存' };
}
