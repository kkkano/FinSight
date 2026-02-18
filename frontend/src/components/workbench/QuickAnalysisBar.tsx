/**
 * QuickAnalysisBar - Quick analysis entry point for the Workbench.
 *
 * Provides a search-bar style input that allows users to type a ticker
 * or free-text query and trigger an analysis via the execute API.
 */
import { useState, useCallback, useRef, type KeyboardEvent } from 'react';
import { Search, Zap, Loader2 } from 'lucide-react';

import { useExecuteAgent } from '../../hooks/useExecuteAgent';

// --- Props ---

interface QuickAnalysisBarProps {
  /** Default ticker to pre-fill */
  defaultTicker?: string;
  /** Callback after analysis is dispatched */
  onAnalysisStarted?: (query: string) => void;
}

// --- Component ---

export function QuickAnalysisBar({ defaultTicker, onAnalysisStarted }: QuickAnalysisBarProps) {
  const [query, setQuery] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { execute } = useExecuteAgent();

  const handleSubmit = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    try {
      const analysisQuery = trimmed.match(/^[A-Z]{1,5}$/i)
        ? `分析 ${trimmed.toUpperCase()} 的投资价值`
        : trimmed;

      const tickerMatch = trimmed.match(/^[A-Z]{1,5}$/i);
      execute({
        query: analysisQuery,
        tickers: tickerMatch ? [trimmed.toUpperCase()] : undefined,
        outputMode: 'brief',
        source: 'workbench_quick_analysis',
      });
      onAnalysisStarted?.(analysisQuery);
      setQuery('');
    } catch {
      // Silently handle — the execution store will show status
    } finally {
      setSubmitting(false);
    }
  }, [query, submitting, onAnalysisStarted, execute]);

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-fin-card rounded-xl border border-fin-border hover:border-fin-primary/30 transition-colors">
      <Search className="w-4 h-4 text-fin-muted flex-shrink-0" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          defaultTicker
            ? `快速分析 ${defaultTicker} 或输入任意查询...`
            : '输入股票代码或分析查询...'
        }
        className="flex-1 bg-transparent text-sm text-fin-text placeholder:text-fin-muted/60 outline-none"
        disabled={submitting}
      />
      <button
        type="button"
        onClick={() => void handleSubmit()}
        disabled={!query.trim() || submitting}
        className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {submitting ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Zap className="w-3.5 h-3.5" />
        )}
        分析
      </button>
    </div>
  );
}

export default QuickAnalysisBar;
