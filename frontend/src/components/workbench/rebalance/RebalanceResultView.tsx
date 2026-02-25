/**
 * RebalanceResultView -- 调仓建议完整结果视图。
 *
 * 组合:
 *  - SuggestionSummaryCard  (AI 摘要 + 影响指标)
 *  - RebalanceWaterfallChart (权重变化瀑布图)
 *  - ActionList              (逐条操作 + 逐条接受/拒绝)
 *  - RebalanceCompareView    (模拟对比饼图 + 差异表, 可折叠)
 *  - DisclaimerBanner        (免责声明)
 *  - ActionButtons           (全量操作 + 导出 + 发送到对话)
 */
import { useState, useCallback } from 'react';

import { Card } from '../../ui/Card.tsx';
import { SuggestionSummaryCard } from './SuggestionSummaryCard.tsx';
import { RebalanceWaterfallChart } from './RebalanceWaterfallChart.tsx';
import { ActionList } from './ActionList.tsx';
import { RebalanceCompareView } from './RebalanceCompareView.tsx';
import { DisclaimerBanner } from './DisclaimerBanner.tsx';
import { ActionButtons } from './ActionButtons.tsx';
import { useRebalanceWorkflow } from '../../../hooks/useRebalanceWorkflow.ts';
import type { RebalanceSuggestion, SuggestionStatus } from '../../../types/dashboard.ts';

interface RebalanceResultViewProps {
  suggestion: RebalanceSuggestion;
  onUpdateStatus: (id: string, status: SuggestionStatus) => Promise<void>;
  onRegenerate: () => void;
}

export function RebalanceResultView({
  suggestion,
  onUpdateStatus,
  onRegenerate,
}: RebalanceResultViewProps) {
  const [showCompare, setShowCompare] = useState(false);

  const {
    decisions,
    summary,
    setDecision,
    acceptAll,
    rejectAll,
    resetAll,
  } = useRebalanceWorkflow(suggestion.actions);

  const handleToggleCompare = useCallback(() => {
    setShowCompare((prev) => !prev);
  }, []);

  return (
    <Card className="p-4 space-y-4">
      <SuggestionSummaryCard suggestion={suggestion} />

      {/* 权重变化瀑布图 */}
      {suggestion.actions.length > 0 && (
        <RebalanceWaterfallChart actions={suggestion.actions} />
      )}

      {/* 操作列表 (支持逐条接受/拒绝) */}
      <div className="border-t border-fin-border pt-3">
        <ActionList
          actions={suggestion.actions}
          decisions={decisions}
          onSetDecision={setDecision}
        />
      </div>

      {/* 模拟对比视图 (可折叠) */}
      {showCompare && suggestion.actions.length > 0 && (
        <div className="border-t border-fin-border pt-3">
          <div className="text-xs font-medium text-fin-text mb-2">
            模拟对比
          </div>
          <RebalanceCompareView
            actions={suggestion.actions}
            decisions={decisions}
          />
        </div>
      )}

      <DisclaimerBanner disclaimer={suggestion.disclaimer} />

      {/* 操作按钮栏 */}
      <div className="border-t border-fin-border pt-3">
        <ActionButtons
          suggestion={suggestion}
          onUpdateStatus={onUpdateStatus}
          onRegenerate={onRegenerate}
          decisions={decisions}
          summary={summary}
          onAcceptAll={acceptAll}
          onRejectAll={rejectAll}
          onResetAll={resetAll}
          showCompare={showCompare}
          onToggleCompare={handleToggleCompare}
        />
      </div>
    </Card>
  );
}
