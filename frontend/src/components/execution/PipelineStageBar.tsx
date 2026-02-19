import type { PipelineStage, PipelineStageState } from '../../types/execution';

const STAGE_ORDER: PipelineStage[] = [
  'planning',
  'executing',
  'synthesizing',
  'rendering',
  'done',
];

const STAGE_LABEL: Record<PipelineStage, string> = {
  planning: '规划',
  executing: '执行',
  synthesizing: '合成',
  rendering: '渲染',
  done: '完成',
};

type PipelineStageBarProps = {
  stages?: Record<PipelineStage, PipelineStageState>;
  currentStage?: PipelineStage | null;
  compact?: boolean;
};

function nodeClass(status: PipelineStageState['status'] | undefined, isCurrent: boolean): string {
  if (status === 'done') {
    return 'border-emerald-500 bg-emerald-500 text-white';
  }
  if (status === 'error') {
    return 'border-red-500 bg-red-500 text-white';
  }
  if (status === 'running' || isCurrent) {
    return 'border-blue-500 bg-blue-500/20 text-blue-300';
  }
  return 'border-fin-border bg-fin-bg text-fin-muted';
}

function lineClass(
  status: PipelineStageState['status'] | undefined,
  nextStatus: PipelineStageState['status'] | undefined,
): string {
  if (status === 'done' && (nextStatus === 'done' || nextStatus === 'running')) {
    return 'bg-emerald-500/70';
  }
  if (status === 'error' || nextStatus === 'error') {
    return 'bg-red-500/50';
  }
  return 'bg-fin-border';
}

export function PipelineStageBar({
  stages,
  currentStage,
  compact = false,
}: PipelineStageBarProps) {
  return (
    <div className="rounded-lg border border-fin-border bg-fin-bg/30 px-3 py-3">
      <div className="flex items-center gap-2">
        {STAGE_ORDER.map((stage, index) => {
          const state = stages?.[stage];
          const isCurrent = currentStage === stage;
          return (
            <div key={stage} className="flex items-center flex-1 min-w-0">
              <div className="flex flex-col items-center gap-1 min-w-[42px]">
                <span
                  className={`w-6 h-6 rounded-full border text-2xs font-semibold flex items-center justify-center transition-colors ${nodeClass(state?.status, isCurrent)}`}
                  title={state?.message || STAGE_LABEL[stage]}
                >
                  {index + 1}
                </span>
                {!compact && (
                  <span className={`text-2xs ${isCurrent ? 'text-fin-text' : 'text-fin-muted'}`}>
                    {STAGE_LABEL[stage]}
                  </span>
                )}
              </div>
              {index < STAGE_ORDER.length - 1 && (
                <div className={`h-[2px] flex-1 rounded ${lineClass(state?.status, stages?.[STAGE_ORDER[index + 1]]?.status)}`} />
              )}
            </div>
          );
        })}
      </div>
      {!compact && currentStage && (
        <div className="mt-2 text-2xs text-fin-muted">
          当前阶段：{STAGE_LABEL[currentStage]}
          {stages?.[currentStage]?.message ? ` · ${stages[currentStage].message}` : ''}
        </div>
      )}
    </div>
  );
}

export default PipelineStageBar;

