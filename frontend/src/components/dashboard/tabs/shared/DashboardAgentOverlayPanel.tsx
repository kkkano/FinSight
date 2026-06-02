import { useMemo } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Loader2, PauseCircle } from 'lucide-react';

import { SmartChartRenderer } from '../../../SmartChart';
import type { ExecutionRun } from '../../../../types/execution';
import {
  dashboardChartSpecsToBlocks,
  type DashboardAgentOverlay,
} from '../../../../utils/dashboardDeepDiveOverlay';

interface DashboardAgentOverlayPanelProps {
  overlay: DashboardAgentOverlay | null;
  run?: ExecutionRun | null;
  className?: string;
}

export function DashboardAgentOverlayPanel({
  overlay,
  run = null,
  className = '',
}: DashboardAgentOverlayPanelProps) {
  const chartBlocks = useMemo(
    () => dashboardChartSpecsToBlocks(overlay?.chartSpecs),
    [overlay?.chartSpecs],
  );

  if (!overlay && !run) return null;

  const status = run?.status ?? overlay?.status ?? 'done';
  const progress = run?.progress ?? (status === 'done' ? 100 : 0);
  const currentStep = run?.currentStep ?? overlay?.summary ?? 'Agent 深挖处理中...';
  const streamedContent = run?.streamedContent?.trim() ?? '';
  const summary = overlay?.summary?.trim() ?? streamedContent;
  const claims = overlay?.claims ?? [];
  const isRunning = status === 'running' || status === 'interrupted';
  const isError = status === 'error' || status === 'cancelled';

  return (
    <div className={`space-y-3 ${className}`}>
      <div
        className={`rounded-xl border p-4 ${
          isError
            ? 'border-fin-danger/40 bg-fin-danger/10'
            : 'border-fin-primary/30 bg-fin-primary/5'
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            {status === 'running' && <Loader2 size={15} className="text-fin-primary animate-spin shrink-0" />}
            {status === 'interrupted' && <PauseCircle size={15} className="text-fin-warning shrink-0" />}
            {status === 'done' && <CheckCircle2 size={15} className="text-fin-success shrink-0" />}
            {isError && <AlertTriangle size={15} className="text-fin-danger shrink-0" />}
            {!isRunning && !isError && status !== 'done' && <Activity size={15} className="text-fin-primary shrink-0" />}
            <div className="min-w-0">
              <div className="text-sm font-semibold text-fin-text">
                {isRunning ? 'Agent 深挖进行中' : isError ? 'Agent 深挖未完成' : 'Agent 深挖结论'}
              </div>
              {overlay?.updatedAt && (
                <div className="text-2xs text-fin-muted mt-0.5">
                  更新于 {new Date(overlay.updatedAt).toLocaleString()}
                </div>
              )}
            </div>
          </div>
          {isRunning && (
            <span className="text-xs text-fin-primary tabular-nums shrink-0">
              {progress}%
            </span>
          )}
        </div>

        {isRunning && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="text-fin-muted truncate">{currentStep}</span>
            </div>
            <div className="h-1.5 rounded-full bg-fin-border overflow-hidden">
              <div
                className="h-full rounded-full bg-fin-primary transition-all duration-300"
                style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
              />
            </div>
            {streamedContent && (
              <div className="max-h-36 overflow-y-auto rounded-lg border border-fin-border/60 bg-fin-bg/40 p-3 text-xs leading-relaxed text-fin-text/80 whitespace-pre-wrap">
                {streamedContent}
              </div>
            )}
          </div>
        )}

        {!isRunning && summary && (
          <p className="mt-3 text-sm leading-relaxed text-fin-text/85 whitespace-pre-wrap">
            {summary}
          </p>
        )}

        {!isRunning && claims.length > 0 && (
          <div className="mt-3 border-t border-fin-border/40 pt-3">
            <div className="text-xs font-medium text-fin-muted mb-2">关键 claims</div>
            <ul className="space-y-1.5">
              {claims.slice(0, 5).map((claim) => (
                <li key={claim.claim_id} className="flex items-start gap-2 text-xs text-fin-text/75">
                  <span className="mt-1 h-1.5 w-1.5 rounded-full bg-fin-primary shrink-0" />
                  <span className="leading-relaxed">{claim.claim}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {!isRunning && !isError && chartBlocks.map((block, index) => (
        <SmartChartRenderer
          key={`${overlay?.runId ?? 'overlay'}:${index}:${block.type}:${block.title}`}
          block={block}
        />
      ))}
    </div>
  );
}

export default DashboardAgentOverlayPanel;
