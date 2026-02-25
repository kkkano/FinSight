import { useMemo } from 'react';
import { CheckCircle2, AlertTriangle, Loader2, SkipForward } from 'lucide-react';

import type { AgentRunInfo } from '../../types/execution';
import { getAgentDisplayName } from '../../utils/userMessageMapper';

type AgentSummaryCardsProps = {
  agentStatuses: Record<string, AgentRunInfo>;
  selectedAgents?: string[];
  className?: string;
};

/** Agent 状态对应的图标和样式 */
function agentStatusConfig(status: AgentRunInfo['status']) {
  switch (status) {
    case 'running':
      return {
        icon: <Loader2 size={14} className="animate-spin text-blue-400" />,
        border: 'border-blue-500/30',
        bg: 'bg-blue-500/5',
        textColor: 'text-blue-200',
      };
    case 'done':
      return {
        icon: <CheckCircle2 size={14} className="text-emerald-400" />,
        border: 'border-emerald-500/30',
        bg: 'bg-emerald-500/5',
        textColor: 'text-emerald-200',
      };
    case 'error':
      return {
        icon: <AlertTriangle size={14} className="text-red-400" />,
        border: 'border-red-500/30',
        bg: 'bg-red-500/5',
        textColor: 'text-red-200',
      };
    case 'skipped':
      return {
        icon: <SkipForward size={14} className="text-fin-muted" />,
        border: 'border-fin-border/40',
        bg: 'bg-fin-bg/20',
        textColor: 'text-fin-muted',
      };
    default:
      return {
        icon: <div className="w-3.5 h-3.5 rounded-full bg-fin-border/60" />,
        border: 'border-fin-border/30',
        bg: 'bg-fin-bg/10',
        textColor: 'text-fin-muted',
      };
  }
}

/**
 * AgentSummaryCards — Agent 执行状态摘要卡片组件。
 *
 * 在用户模式下展示各 Agent 的执行状态，使用中文名称。
 * 紧凑的卡片布局，适合嵌入 ExecutionPanel 的用户视图。
 */
export function AgentSummaryCards({
  agentStatuses,
  selectedAgents,
  className = '',
}: AgentSummaryCardsProps) {
  const agents = useMemo(() => {
    // 优先按 selectedAgents 顺序，否则按 agentStatuses 的 key 排序
    const order = selectedAgents ?? Object.keys(agentStatuses);
    return order
      .filter((name) => agentStatuses[name])
      .map((name) => ({
        name,
        displayName: getAgentDisplayName(name),
        info: agentStatuses[name],
      }));
  }, [agentStatuses, selectedAgents]);

  if (agents.length === 0) return null;

  const runningCount = agents.filter((a) => a.info.status === 'running').length;
  const doneCount = agents.filter((a) => a.info.status === 'done').length;
  const totalCount = agents.length;

  return (
    <div className={`space-y-2 ${className}`}>
      {/* 进度摘要 */}
      <div className="flex items-center justify-between text-2xs text-fin-muted px-1">
        <span>
          分析师团队 ({doneCount}/{totalCount} 完成)
        </span>
        {runningCount > 0 && (
          <span className="text-blue-300">
            {runningCount} 位正在分析中...
          </span>
        )}
      </div>

      {/* Agent 卡片网格 */}
      <div className="grid grid-cols-2 gap-1.5">
        {agents.map(({ name, displayName, info }) => {
          const config = agentStatusConfig(info.status);
          return (
            <div
              key={name}
              className={`
                flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                border ${config.border} ${config.bg}
                transition-colors duration-200
              `}
            >
              {config.icon}
              <div className="min-w-0 flex-1">
                <div className={`text-2xs font-medium truncate ${config.textColor}`}>
                  {displayName}
                </div>
                {info.durationMs != null && info.status === 'done' && (
                  <div className="text-3xs text-fin-muted">
                    {(info.durationMs / 1000).toFixed(1)}s
                  </div>
                )}
                {info.status === 'error' && info.error && (
                  <div className="text-3xs text-red-300 truncate" title={info.error}>
                    {info.error}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default AgentSummaryCards;
