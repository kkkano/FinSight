import { useCallback, useRef, useState, type KeyboardEvent } from 'react';
import { Loader2, Search, Settings2, Zap } from 'lucide-react';

import type { AnalysisConfig } from '../../types/execution';
import { useExecutionStore } from '../../store/executionStore';
import { AnalysisConfigPanel } from './AnalysisConfigPanel';

interface QuickAnalysisBarProps {
  defaultTicker?: string;
  onAnalysisStarted?: (query: string) => void;
}

function isTickerInput(value: string): boolean {
  return /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/i.test(value.trim());
}

function normalizeTicker(value: string): string | undefined {
  const raw = value.trim().toUpperCase();
  if (!raw) return undefined;
  return isTickerInput(raw) ? raw : undefined;
}

function buildAnalysisQuery(input: string): string {
  const trimmed = input.trim();
  if (isTickerInput(trimmed)) {
    return `Analyze ${trimmed.toUpperCase()} investment outlook`;
  }
  return trimmed;
}

export function QuickAnalysisBar({ defaultTicker, onAnalysisStarted }: QuickAnalysisBarProps) {
  const [query, setQuery] = useState('');
  const [configOpen, setConfigOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const startExecution = useExecutionStore((state) => state.startExecution);
  const isRunning = useExecutionStore((state) =>
    state.activeRuns.some((run) => run.source === 'workbench_quick_analysis' && run.status === 'running'),
  );

  const getRawInput = useCallback((): string => {
    const typed = query.trim();
    if (typed) return typed;
    return (defaultTicker || '').trim();
  }, [query, defaultTicker]);

  const dispatchRun = useCallback(
    (config?: AnalysisConfig) => {
      const rawInput = getRawInput();
      if (!rawInput || isRunning) return;

      const finalQuery = buildAnalysisQuery(rawInput);
      const ticker = normalizeTicker(rawInput);
      const selectedAgents = config
        ? Object.entries(config.agentDepths)
          .filter(([, depth]) => depth !== 'off')
          .map(([name]) => name)
        : undefined;

      startExecution({
        query: finalQuery,
        tickers: ticker ? [ticker] : undefined,
        outputMode: 'brief',
        analysisDepth: config?.analysisDepth,
        agents: selectedAgents,
        source: 'workbench_quick_analysis',
        budget: config?.budget,
        agentPreferencesOverride: config
          ? {
            agents: config.agentDepths,
            maxRounds: config.budget,
            concurrentMode: config.concurrentMode,
          }
          : undefined,
      });

      onAnalysisStarted?.(finalQuery);
      setQuery('');
      setConfigOpen(false);
    },
    [getRawInput, isRunning, startExecution, onAnalysisStarted],
  );

  const handleSubmit = useCallback(() => {
    dispatchRun();
  }, [dispatchRun]);

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  };

  const queryPreview = getRawInput();
  const canSubmit = Boolean(queryPreview) && !isRunning;

  return (
    <>
      <div className="flex items-center gap-2 px-3 py-2 bg-fin-card rounded-xl border border-fin-border hover:border-fin-primary/30 transition-colors">
        <Search className="w-4 h-4 text-fin-muted flex-shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            defaultTicker
              ? `快速分析 ${defaultTicker} 或输入任意查询...`
              : '输入股票代码或分析查询...'
          }
          className="flex-1 bg-transparent text-sm text-fin-text placeholder:text-fin-muted/60 outline-none"
          disabled={isRunning}
        />
        <button
          type="button"
          onClick={() => setConfigOpen(true)}
          disabled={!canSubmit}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded-lg border border-fin-border text-fin-muted hover:text-fin-text disabled:opacity-40 disabled:cursor-not-allowed"
          title="执行前配置"
        >
          <Settings2 className="w-3.5 h-3.5" />
          配置
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Zap className="w-3.5 h-3.5" />
          )}
          分析
        </button>
      </div>
      <AnalysisConfigPanel
        open={configOpen}
        queryPreview={queryPreview}
        onClose={() => setConfigOpen(false)}
        onStart={(config) => dispatchRun(config)}
      />
    </>
  );
}

export default QuickAnalysisBar;
