/**
 * rebalanceExport -- 调仓建议导出工具。
 *
 * 支持 CSV 文件下载和剪贴板文本复制两种导出方式。
 * 纯函数设计，不包含 React 依赖。
 */
import type {
  RebalanceSuggestion,
  RebalanceAction,
  RiskTier,
} from '../types/dashboard.ts';
import type { ActionDecisionMap } from '../hooks/useRebalanceWorkflow.ts';

// === 风险偏好标签映射 ===
const RISK_TIER_LABELS: Record<RiskTier, string> = {
  conservative: '保守型',
  moderate: '稳健型',
  aggressive: '进取型',
};

// === 操作类型标签映射 ===
const ACTION_LABELS: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  hold: '持有',
  reduce: '减持',
  increase: '增持',
};

// === CSV 导出 ===

/**
 * 将调仓建议生成为 CSV 字符串。
 * 仅导出已接受的操作（如果提供了 decisions），否则导出全部。
 */
export function generateCSV(
  suggestion: RebalanceSuggestion,
  decisions?: ActionDecisionMap,
): string {
  const filteredActions = filterActions(suggestion.actions, decisions);

  const header = [
    '代码',
    '操作',
    '当前权重(%)',
    '目标权重(%)',
    '变动(%)',
    '优先级',
    '决策状态',
    '调仓理由',
  ].join(',');

  const rows = filteredActions.map((action) => {
    const decision = decisions?.[action.ticker] ?? 'pending';
    const decisionLabel =
      decision === 'accepted'
        ? '已接受'
        : decision === 'rejected'
          ? '已拒绝'
          : '待定';

    return [
      action.ticker,
      ACTION_LABELS[action.action] ?? action.action,
      action.current_weight.toFixed(1),
      action.target_weight.toFixed(1),
      action.delta_weight.toFixed(1),
      String(action.priority),
      decisionLabel,
      `"${escapeCsvField(action.reason)}"`,
    ].join(',');
  });

  // 添加元信息
  const meta = [
    `# AI 智能调仓建议`,
    `# 风险偏好: ${RISK_TIER_LABELS[suggestion.risk_tier]}`,
    `# 预计换手率: ${suggestion.expected_impact.estimated_turnover_pct.toFixed(1)}%`,
    `# 生成时间: ${suggestion.created_at || new Date().toISOString()}`,
    `# ${suggestion.disclaimer}`,
    '',
  ];

  return [...meta, header, ...rows].join('\n');
}

/**
 * 触发 CSV 文件下载。
 */
export function downloadCSV(
  suggestion: RebalanceSuggestion,
  decisions?: ActionDecisionMap,
): void {
  const csv = generateCSV(suggestion, decisions);
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `rebalance_${suggestion.suggestion_id.slice(0, 8)}_${formatDate()}.csv`;
  link.click();

  URL.revokeObjectURL(url);
}

// === 文本分享 ===

/**
 * 生成结构化的文本摘要，适合剪贴板复制或消息分享。
 */
export function generateShareText(
  suggestion: RebalanceSuggestion,
  decisions?: ActionDecisionMap,
): string {
  const filteredActions = filterActions(suggestion.actions, decisions);
  const lines: string[] = [];

  lines.push('=== AI 智能调仓建议 ===');
  lines.push('');
  lines.push(`风险偏好: ${RISK_TIER_LABELS[suggestion.risk_tier]}`);
  lines.push(`预计换手率: ${suggestion.expected_impact.estimated_turnover_pct.toFixed(1)}%`);
  lines.push(`分散化变化: ${suggestion.expected_impact.diversification_delta}`);
  lines.push(`风险变化: ${suggestion.expected_impact.risk_delta}`);
  lines.push('');
  lines.push(`摘要: ${suggestion.summary}`);
  lines.push('');
  lines.push('--- 操作明细 ---');

  for (const action of filteredActions) {
    const decision = decisions?.[action.ticker] ?? 'pending';
    const statusIcon =
      decision === 'accepted' ? '[v]' : decision === 'rejected' ? '[x]' : '[ ]';
    const delta =
      action.delta_weight >= 0
        ? `+${action.delta_weight.toFixed(1)}%`
        : `${action.delta_weight.toFixed(1)}%`;

    lines.push(
      `${statusIcon} ${action.ticker} | ${ACTION_LABELS[action.action] ?? action.action} | ` +
        `${action.current_weight.toFixed(1)}% -> ${action.target_weight.toFixed(1)}% (${delta})`,
    );
  }

  lines.push('');
  lines.push(`${suggestion.disclaimer}`);

  return lines.join('\n');
}

/**
 * 将文本复制到剪贴板。成功返回 true，失败返回 false。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// === 内部工具函数 ===

function filterActions(
  actions: readonly RebalanceAction[],
  decisions?: ActionDecisionMap,
): readonly RebalanceAction[] {
  if (!decisions) return actions;
  // 导出全部操作（包含状态标记），不过滤
  return actions;
}

function escapeCsvField(value: string): string {
  return value.replace(/"/g, '""').replace(/\n/g, ' ');
}

function formatDate(): string {
  const now = new Date();
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
  ].join('');
}
