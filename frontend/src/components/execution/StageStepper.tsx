import clsx from 'clsx';

export type StageStatus = 'done' | 'active' | 'pending' | 'error';

export interface StageStepperProps {
  stages: {
    key: string;
    label: string;
    status: StageStatus;
    detail?: string;
  }[];
  elapsedMs?: number;
  currentAction?: string;
}

const STATUS_SYMBOL: Record<StageStatus, string> = {
  done: '●',
  active: '◉',
  pending: '○',
  error: '●',
};

const STATUS_LABEL: Record<StageStatus, string> = {
  done: '已完成',
  active: '进行中',
  pending: '等待中',
  error: '失败',
};

function formatElapsed(elapsedMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m${seconds}s` : `${seconds}s`;
}

export function StageStepper({ stages, elapsedMs, currentAction }: StageStepperProps) {
  return (
    <div className="rounded-lg border border-t-border bg-t-card px-3 py-2.5 shadow-[var(--t-shadow-card)]">
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center" aria-label="执行阶段">
          {stages.map((stage, index) => (
            <div key={stage.key} className="flex min-w-0 flex-1 items-center last:flex-none">
              <div
                className="flex shrink-0 items-center gap-1 font-mono text-2xs"
                aria-label={`${stage.label}：${STATUS_LABEL[stage.status]}`}
              >
                <span
                  aria-hidden="true"
                  className={clsx(
                    'text-[13px] leading-none',
                    stage.status === 'done' && 'text-t-accent',
                    stage.status === 'active' && 'animate-pulse text-t-accent',
                    stage.status === 'pending' && 'text-t-text3',
                    stage.status === 'error' && 'text-t-down',
                  )}
                >
                  {STATUS_SYMBOL[stage.status]}
                </span>
                <span className={clsx(stage.status === 'pending' ? 'text-t-text3' : 'text-t-text2')}>
                  {stage.label}{stage.detail ? `(${stage.detail})` : ''}
                </span>
              </div>
              {index < stages.length - 1 && (
                <span
                  aria-hidden="true"
                  className={clsx(
                    'mx-2 h-px min-w-2 flex-1 bg-t-border',
                    stage.status === 'done' && 'bg-t-accent/60',
                  )}
                />
              )}
            </div>
          ))}
        </div>
        {elapsedMs !== undefined && (
          <span className="num shrink-0 text-2xs text-t-text3">{formatElapsed(elapsedMs)}</span>
        )}
      </div>
      {currentAction && (
        <div className="mt-2 truncate font-mono text-2xs text-t-text3">
          正在运行: <span className="text-t-text2">{currentAction}</span>
        </div>
      )}
    </div>
  );
}

export default StageStepper;
