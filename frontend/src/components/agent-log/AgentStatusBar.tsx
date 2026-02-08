import type { AgentLogSource, AgentStatus } from '../../types';
import { formatSize, type EventStats } from './constants';

export interface AgentStatusBarProps {
  stats: EventStats;
  showTokens: boolean;
  agentStatuses: Record<AgentLogSource, AgentStatus>;
}

export const AgentStatusBar: React.FC<AgentStatusBarProps> = ({
  stats,
  showTokens,
  agentStatuses,
}) => {
  return (
    <div className="flex items-center justify-between px-2 py-1 bg-fin-bg border-t border-fin-border text-2xs text-fin-muted">
      <div className="flex items-center gap-3">
        <span data-testid="agent-log-event-count">{stats.filtered}/{stats.total} events</span>
        <span>{formatSize(stats.totalBytes)}</span>
        {!showTokens && stats.typeCounts['token'] > 0 && (
          <span className="text-fin-muted/70">({stats.typeCounts['token']} tokens hidden)</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {Object.entries(agentStatuses)
          .filter(([, s]) => s.status === 'running')
          .map(([key]) => (
            <span key={key} className="px-1 py-0.5 rounded bg-fin-success/10 text-fin-success text-[9px]">
              {key}
            </span>
          ))
        }
      </div>
    </div>
  );
};
