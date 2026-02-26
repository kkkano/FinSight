/**
 * ActionButtons -- 调仓建议底部操作栏。
 *
 * 按钮组：
 *  - 接受全部 / 拒绝全部 / 重置
 *  - 发送到对话（已接受的操作）
 *  - 导出 CSV / 复制文本
 *  - 模拟对比 (toggle)
 *  - 重新生成
 */
import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MessageSquare,
  RefreshCw,
  CheckCheck,
  XCircle,
  Download,
  Copy,
  BarChart3,
  RotateCcw,
} from 'lucide-react';

import { Button } from '../../ui/Button.tsx';
import { useStore } from '../../../store/useStore.ts';
import { downloadCSV, generateShareText, copyToClipboard } from '../../../utils/rebalanceExport.ts';
import type { RebalanceSuggestion } from '../../../types/dashboard.ts';
import type {
  ActionDecisionMap,
  WorkflowSummary,
} from '../../../hooks/useRebalanceWorkflow.ts';

interface ActionButtonsProps {
  suggestion: RebalanceSuggestion;
  onUpdateStatus: (id: string, status: 'sent_to_chat' | 'dismissed') => Promise<void>;
  onRegenerate: () => void;
  decisions?: ActionDecisionMap;
  summary?: WorkflowSummary;
  onAcceptAll?: () => void;
  onRejectAll?: () => void;
  onResetAll?: () => void;
  showCompare: boolean;
  onToggleCompare: () => void;
}

const PARAM_PANEL_ID = 'rebalance-param-panel';

export function ActionButtons({
  suggestion,
  onUpdateStatus,
  onRegenerate,
  decisions,
  summary,
  onAcceptAll,
  onRejectAll,
  onResetAll,
  showCompare,
  onToggleCompare,
}: ActionButtonsProps) {
  const navigate = useNavigate();
  const addMessage = useStore((s) => s.addMessage);
  const isSent = suggestion.status === 'sent_to_chat';
  const [copySuccess, setCopySuccess] = useState(false);

  // 发送到对话 -- 仅包含已接受的操作
  const handleSendToChat = useCallback(async () => {
    await onUpdateStatus(suggestion.suggestion_id, 'sent_to_chat');

    const acceptedActions = summary
      ? summary.acceptedActions
      : suggestion.actions;

    const actionSummary = acceptedActions
      .map((a) => `${a.ticker}: ${a.action}`)
      .join(', ');

    const content =
      `[AI 调仓建议] ${suggestion.summary}\n\n` +
      `已接受操作 (${acceptedActions.length}/${suggestion.actions.length}): ${actionSummary}`;

    addMessage({
      id: `rebalance-${suggestion.suggestion_id}-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: Date.now(),
    });

    navigate('/chat');
  }, [suggestion, onUpdateStatus, addMessage, navigate, summary]);

  // 导出 CSV
  const handleExportCSV = useCallback(() => {
    downloadCSV(suggestion, decisions);
  }, [suggestion, decisions]);

  // 复制文本
  const handleCopyText = useCallback(async () => {
    const text = generateShareText(suggestion, decisions);
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    }
  }, [suggestion, decisions]);

  // 重新生成（滚动到参数面板）
  const handleRegenerate = useCallback(() => {
    const el = document.getElementById(PARAM_PANEL_ID);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    onRegenerate();
  }, [onRegenerate]);

  const hasWorkflow = Boolean(summary);
  const hasAccepted = summary ? summary.accepted > 0 : true;

  return (
    <div className="space-y-3">
      {/* 第一行: 全量操作按钮 */}
      {hasWorkflow && (
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="primary" size="sm" onClick={onAcceptAll}>
            <CheckCheck size={14} />
            全部接受
          </Button>
          <Button variant="ghost" size="sm" onClick={onRejectAll}>
            <XCircle size={14} />
            全部拒绝
          </Button>
          <Button variant="ghost" size="sm" onClick={onResetAll}>
            <RotateCcw size={14} />
            重置
          </Button>

          {summary && (
            <span className="ml-auto text-2xs text-fin-muted">
              {summary.accepted} 接受 / {summary.rejected} 拒绝 / {summary.pending} 待定
            </span>
          )}
        </div>
      )}

      {/* 第二行: 核心操作 */}
      <div className="flex items-center gap-2 flex-wrap">
        <Button
          variant="primary"
          size="sm"
          onClick={handleSendToChat}
          disabled={isSent || !hasAccepted}
          title={!hasAccepted ? '请至少接受一项操作' : undefined}
        >
          <MessageSquare size={14} />
          {isSent ? '已发送' : '发送到对话'}
        </Button>

        <Button
          variant="secondary"
          size="sm"
          onClick={onToggleCompare}
        >
          <BarChart3 size={14} />
          {showCompare ? '收起对比' : '模拟对比'}
        </Button>

        <Button variant="ghost" size="sm" onClick={handleExportCSV}>
          <Download size={14} />
          导出 CSV
        </Button>

        <Button variant="ghost" size="sm" onClick={handleCopyText}>
          <Copy size={14} />
          {copySuccess ? '已复制' : '复制文本'}
        </Button>

        <Button
          variant="secondary"
          size="sm"
          onClick={handleRegenerate}
          className="ml-auto"
        >
          <RefreshCw size={14} />
          重新生成
        </Button>
      </div>
    </div>
  );
}
