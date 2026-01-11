import { useState } from 'react';
import { Brain, ChevronDown, ChevronUp } from 'lucide-react';
import type { ThinkingStep } from '../types';

interface ThinkingProcessProps {
  thinking: ThinkingStep[];
}

const stageLabels: Record<string, string> = {
  reference_resolution: 'Understanding context',
  intent_classification: 'Intent classification',
  data_collection: 'Data collection',
  processing: 'Processing',
  complete: 'Complete',
  tool_call: 'Tool call',
  llm_call: 'LLM reasoning',
  error: 'Error',
};

const getStageIcon = (stage: string) => {
  if (stage.includes('complete')) return 'OK';
  if (stage.includes('error')) return '!';
  if (stage.includes('processing') || stage.includes('collection')) return '...';
  return '>';
};

export const ThinkingProcess: React.FC<ThinkingProcessProps> = ({ thinking }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!thinking?.length) {
    return null;
  }

  return (
    <div className="mt-3 border-t border-fin-border pt-3">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between w-full text-xs text-fin-muted hover:text-fin-text transition-colors"
      >
        <div className="flex items-center gap-2">
          <Brain size={14} />
          <span>Reasoning trace ({thinking.length} steps)</span>
        </div>
        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-2 max-h-64 overflow-y-auto">
          {thinking.map((step, index) => (
            <div
              key={index}
              className="text-xs bg-fin-panel/50 rounded-lg p-2 border border-fin-border/50"
            >
              <div className="flex items-start gap-2">
                <span className="text-base leading-none">{getStageIcon(step.stage)}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-fin-text">
                    {stageLabels[step.stage] || step.stage}
                  </div>
                  {step.message && (
                    <div className="text-fin-muted mt-1">{step.message}</div>
                  )}
                  {step.result && (
                    <div className="mt-1 text-fin-muted">
                      <details className="cursor-pointer">
                        <summary className="text-xs">View details</summary>
                        <pre className="mt-1 text-xs bg-fin-bg p-2 rounded overflow-x-auto">
                          {JSON.stringify(step.result, null, 2)}
                        </pre>
                      </details>
                    </div>
                  )}
                  <div className="text-fin-muted/50 text-[10px] mt-1">
                    {new Date(step.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
