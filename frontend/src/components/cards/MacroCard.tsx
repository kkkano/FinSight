/**
 * Macro Card - 宏观数据
 *
 * 提供宏观经济分析入口，点击可触发 macro_agent 深度分析。
 */
import { Globe, Loader2 } from 'lucide-react';

import { useExecuteAgent } from '../../hooks/useExecuteAgent';

interface MacroCardProps {
  loading?: boolean;
}

export function MacroCard({ loading }: MacroCardProps) {
  const { execute, isRunning } = useExecuteAgent();

  const handleAnalyze = () => {
    if (isRunning) return;
    execute({
      query: '分析宏观经济环境',
      agents: ['macro_agent'],
      source: 'dashboard_macro',
    });
  };

  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-32 animate-pulse">
        <div className="h-4 bg-fin-border rounded w-24 mb-4" />
        <div className="h-16 bg-fin-border rounded" />
      </div>
    );
  }

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-4">
      <h3 className="text-sm font-semibold text-fin-text mb-3">宏观数据</h3>
      <div className="flex items-center justify-center h-24 text-fin-muted text-sm border-2 border-dashed border-fin-border rounded-lg">
        <button
          type="button"
          onClick={handleAnalyze}
          disabled={isRunning}
          className="flex flex-col items-center gap-2 text-fin-muted hover:text-fin-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isRunning ? (
            <Loader2 size={20} className="animate-spin" />
          ) : (
            <Globe size={20} />
          )}
          <span className="text-xs">{isRunning ? '分析中...' : '宏观详解'}</span>
          <span className="text-2xs text-fin-muted">GDP、CPI、利率等宏观指标分析</span>
        </button>
      </div>
    </div>
  );
}

export default MacroCard;
