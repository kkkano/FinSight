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
    return 'border-t-info bg-t-info/10 text-t-info';
  }
  return 'border-t-border bg-t-bg text-t-text2';
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
  return 'bg-t-divider';
}

export function PipelineStageBar({
  stages,
  currentStage,
  compact = false,
}: PipelineStageBarProps) {
  return (
    <div className="py-2">
      <div className="flex items-center gap-1">
        {STAGE_ORDER.map((stage, index) => {
          const state = stages?.[stage];
          const isCurrent = currentStage === stage;
          return (
            <div key={stage} className="flex items-center flex-1 min-w-0">
              <div className="flex flex-col items-center gap-1 min-w-[42px]">
                <span
                  className={`w-6 h-6 rounded-full border text-xs font-semibold flex items-center justify-center transition-colors ${nodeClass(state?.status, isCurrent)}`}
                  title={state?.message || STAGE_LABEL[stage]}
                >
                  {index + 1}
                </span>
                {!compact && (
                  <span className={`text-xs ${isCurrent ? 'text-t-text' : 'text-t-text2'}`}>
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
        <div className="mt-3 text-xs leading-relaxed text-t-text2">
          当前阶段：{STAGE_LABEL[currentStage]}
          {stages?.[currentStage]?.message ? ` · ${stages[currentStage].message}` : ''}
        </div>
      )}
    </div>
  );
}

export default PipelineStageBar;
