/**
 * useRebalanceWorkflow -- 管理调仓建议的逐条接受/拒绝工作流。
 *
 * 跟踪每条操作的 accepted / rejected / pending 状态，
 * 并提供全量操作（全部接受/全部拒绝/重置）和导出能力。
 */
import { useState, useCallback, useMemo } from 'react';

import type { RebalanceAction } from '../types/dashboard.ts';

// === 操作决策状态 ===
export type ActionDecision = 'accepted' | 'rejected' | 'pending';

export interface ActionDecisionMap {
  readonly [ticker: string]: ActionDecision;
}

export interface WorkflowSummary {
  /** 总操作数 */
  readonly total: number;
  /** 已接受数 */
  readonly accepted: number;
  /** 已拒绝数 */
  readonly rejected: number;
  /** 待决定数 */
  readonly pending: number;
  /** 是否所有条目都已有决策 */
  readonly allDecided: boolean;
  /** 被接受的操作列表 */
  readonly acceptedActions: readonly RebalanceAction[];
  /** 被拒绝的操作列表 */
  readonly rejectedActions: readonly RebalanceAction[];
}

export interface UseRebalanceWorkflowReturn {
  readonly decisions: ActionDecisionMap;
  readonly summary: WorkflowSummary;
  readonly setDecision: (ticker: string, decision: ActionDecision) => void;
  readonly acceptAll: () => void;
  readonly rejectAll: () => void;
  readonly resetAll: () => void;
  readonly toggleDecision: (ticker: string) => void;
}

/**
 * 初始化全部为 pending 的决策 map
 */
function initDecisions(actions: readonly RebalanceAction[]): ActionDecisionMap {
  const map: Record<string, ActionDecision> = {};
  for (const action of actions) {
    map[action.ticker] = 'pending';
  }
  return map;
}

export function useRebalanceWorkflow(
  actions: readonly RebalanceAction[],
): UseRebalanceWorkflowReturn {
  const [decisions, setDecisions] = useState<ActionDecisionMap>(() =>
    initDecisions(actions),
  );

  const setDecision = useCallback(
    (ticker: string, decision: ActionDecision) => {
      setDecisions((prev) => ({ ...prev, [ticker]: decision }));
    },
    [],
  );

  const toggleDecision = useCallback((ticker: string) => {
    setDecisions((prev) => {
      const current = prev[ticker] ?? 'pending';
      // pending -> accepted -> rejected -> pending 循环
      const next: ActionDecision =
        current === 'pending'
          ? 'accepted'
          : current === 'accepted'
            ? 'rejected'
            : 'pending';
      return { ...prev, [ticker]: next };
    });
  }, []);

  const acceptAll = useCallback(() => {
    setDecisions((prev) => {
      const next: Record<string, ActionDecision> = {};
      for (const key of Object.keys(prev)) {
        next[key] = 'accepted';
      }
      return next;
    });
  }, []);

  const rejectAll = useCallback(() => {
    setDecisions((prev) => {
      const next: Record<string, ActionDecision> = {};
      for (const key of Object.keys(prev)) {
        next[key] = 'rejected';
      }
      return next;
    });
  }, []);

  const resetAll = useCallback(() => {
    setDecisions(initDecisions(actions));
  }, [actions]);

  const summary = useMemo<WorkflowSummary>(() => {
    const entries = Object.values(decisions);
    const accepted = entries.filter((d) => d === 'accepted').length;
    const rejected = entries.filter((d) => d === 'rejected').length;
    const pending = entries.filter((d) => d === 'pending').length;
    const total = entries.length;

    const acceptedActions = actions.filter(
      (a) => decisions[a.ticker] === 'accepted',
    );
    const rejectedActions = actions.filter(
      (a) => decisions[a.ticker] === 'rejected',
    );

    return {
      total,
      accepted,
      rejected,
      pending,
      allDecided: pending === 0,
      acceptedActions,
      rejectedActions,
    };
  }, [decisions, actions]);

  return {
    decisions,
    summary,
    setDecision,
    acceptAll,
    rejectAll,
    resetAll,
    toggleDecision,
  };
}
