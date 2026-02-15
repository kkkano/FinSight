/**
 * ActionButtons — Action row for rebalance suggestion results.
 *
 * - "Send to Chat": patches status to sent_to_chat, injects message, navigates to chat
 * - "Dismiss": patches status to dismissed
 * - "Regenerate": scrolls to the parameter panel for re-generation
 */
import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, X, RefreshCw } from 'lucide-react';

import { Button } from '../../ui/Button.tsx';
import { useStore } from '../../../store/useStore.ts';
import type { RebalanceSuggestion } from '../../../types/dashboard.ts';

interface ActionButtonsProps {
  suggestion: RebalanceSuggestion;
  onUpdateStatus: (id: string, status: 'sent_to_chat' | 'dismissed') => Promise<void>;
  onRegenerate: () => void;
}

const PARAM_PANEL_ID = 'rebalance-param-panel';

export function ActionButtons({ suggestion, onUpdateStatus, onRegenerate }: ActionButtonsProps) {
  const navigate = useNavigate();
  const addMessage = useStore((s) => s.addMessage);
  const isDismissed = suggestion.status === 'dismissed';
  const isSent = suggestion.status === 'sent_to_chat';

  const handleSendToChat = useCallback(async () => {
    await onUpdateStatus(suggestion.suggestion_id, 'sent_to_chat');

    // Inject a summary message into chat
    const actionSummary = suggestion.actions
      .map((a) => `${a.ticker}: ${a.action}`)
      .join(', ');
    const content = `[AI 调仓建议] ${suggestion.summary}\n\n操作摘要: ${actionSummary}`;

    addMessage({
      id: `rebalance-${suggestion.suggestion_id}-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: Date.now(),
    });

    navigate('/chat');
  }, [suggestion, onUpdateStatus, addMessage, navigate]);

  const handleDismiss = useCallback(async () => {
    await onUpdateStatus(suggestion.suggestion_id, 'dismissed');
  }, [suggestion.suggestion_id, onUpdateStatus]);

  const handleRegenerate = useCallback(() => {
    const el = document.getElementById(PARAM_PANEL_ID);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    onRegenerate();
  }, [onRegenerate]);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Button
        variant="primary"
        size="sm"
        onClick={handleSendToChat}
        disabled={isSent}
      >
        <MessageSquare size={14} />
        {isSent ? '已发送' : '发送到对话'}
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={handleDismiss}
        disabled={isDismissed}
      >
        <X size={14} />
        {isDismissed ? '已忽略' : '忽略'}
      </Button>

      <Button
        variant="secondary"
        size="sm"
        onClick={handleRegenerate}
      >
        <RefreshCw size={14} />
        重新生成
      </Button>
    </div>
  );
}
