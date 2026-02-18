import { useEffect, useMemo, useState } from 'react';

import { apiClient, type ToolCapabilitiesResponse } from '../../api/client';
import { getAgentPreferences } from '../settings/AgentControlPanel';
import type { AgentPreferenceDepth, AnalysisConfig, AnalysisDepth } from '../../types/execution';
import { Card } from '../ui/Card';
import { Dialog } from '../ui/Dialog';

const AGENT_LABELS: Record<string, string> = {
  price_agent: '价格分析',
  news_agent: '新闻分析',
  fundamental_agent: '基本面',
  technical_agent: '技术面',
  risk_agent: '风险分析',
  macro_agent: '宏观分析',
  deep_search_agent: '深度搜索',
};

const DEPTHS: AnalysisDepth[] = ['quick', 'report', 'deep_research'];

const DEPTH_LABELS: Record<AnalysisDepth, string> = {
  quick: '快速',
  report: '标准',
  deep_research: '深度',
};

const AGENT_DEPTH_OPTIONS: AgentPreferenceDepth[] = ['standard', 'deep', 'off'];

const AGENT_DEPTH_LABELS: Record<AgentPreferenceDepth, string> = {
  standard: '标准',
  deep: '深度',
  off: '关闭',
};

const clampBudget = (value: number): number => Math.max(1, Math.min(10, Math.round(value)));

interface AnalysisConfigPanelProps {
  open: boolean;
  queryPreview: string;
  onClose: () => void;
  onStart: (config: AnalysisConfig) => void;
}

export function AnalysisConfigPanel({
  open,
  queryPreview,
  onClose,
  onStart,
}: AnalysisConfigPanelProps) {
  const [analysisDepth, setAnalysisDepth] = useState<AnalysisDepth>('report');
  const [budget, setBudget] = useState(3);
  const [concurrentMode, setConcurrentMode] = useState(true);
  const [agentDepths, setAgentDepths] = useState<Record<string, AgentPreferenceDepth>>({});
  const [capabilities, setCapabilities] = useState<ToolCapabilitiesResponse | null>(null);
  const [loadingCapabilities, setLoadingCapabilities] = useState(false);

  useEffect(() => {
    if (!open) return;
    const prefs = getAgentPreferences();
    const normalizedAgents = Object.fromEntries(
      Object.entries(AGENT_LABELS).map(([name]) => {
        const depth = prefs.agents?.[name];
        const normalized: AgentPreferenceDepth =
          depth === 'deep' || depth === 'off' ? depth : 'standard';
        return [name, normalized];
      }),
    );
    setAgentDepths(normalizedAgents);
    setBudget(clampBudget(prefs.maxRounds ?? 3));
    setConcurrentMode(Boolean(prefs.concurrentMode));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingCapabilities(true);
    void apiClient
      .getToolCapabilities({
        market: 'US',
        operation: 'qa',
        analysis_depth: analysisDepth,
        output_mode: 'brief',
      })
      .then((payload) => {
        if (!cancelled) setCapabilities(payload);
      })
      .catch(() => {
        if (!cancelled) setCapabilities(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingCapabilities(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, analysisDepth]);

  const selectedAgents = useMemo(
    () => Object.entries(agentDepths)
      .filter(([, depth]) => depth !== 'off')
      .map(([name]) => name),
    [agentDepths],
  );

  const selectedTools = capabilities?.selected_tools ?? [];

  const setDepth = (name: string, depth: AgentPreferenceDepth) => {
    setAgentDepths((previous) => ({ ...previous, [name]: depth }));
  };

  const handleStart = () => {
    if (selectedAgents.length === 0) return;
    onStart({
      analysisDepth,
      budget: clampBudget(budget),
      agentDepths,
      concurrentMode,
    });
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      labelledBy="analysis-config-title"
      panelClassName="w-full max-w-2xl"
    >
      <Card className="p-5 border border-fin-border bg-fin-card text-fin-text">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 id="analysis-config-title" className="text-base font-semibold text-fin-text">分析配置</h3>
            <p className="text-xs text-fin-muted mt-1 break-all">
              {queryPreview || '未输入查询'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-2 py-1 rounded border border-fin-border text-fin-muted hover:text-fin-text"
          >
            关闭
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <p className="text-xs text-fin-muted mb-2">分析深度</p>
            <div className="flex gap-2">
              {DEPTHS.map((depth) => (
                <button
                  key={depth}
                  type="button"
                  onClick={() => setAnalysisDepth(depth)}
                  className={`px-3 py-1.5 rounded text-xs border transition-colors ${
                    analysisDepth === depth
                      ? 'border-fin-primary/60 bg-fin-primary/10 text-fin-primary'
                      : 'border-fin-border text-fin-muted hover:text-fin-text'
                  }`}
                >
                  {DEPTH_LABELS[depth]}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-fin-muted">预算轮次</span>
              <span className="text-fin-text">{clampBudget(budget)}</span>
            </div>
            <input
              type="range"
              min={1}
              max={10}
              step={1}
              value={budget}
              onChange={(event) => setBudget(Number(event.target.value))}
              className="w-full accent-fin-primary"
            />
          </div>

          <label className="inline-flex items-center gap-2 text-xs text-fin-muted">
            <input
              type="checkbox"
              className="accent-fin-primary"
              checked={concurrentMode}
              onChange={(event) => setConcurrentMode(event.target.checked)}
            />
            启用并发执行
          </label>

          <div>
            <p className="text-xs text-fin-muted mb-2">本次执行 Agent 深度覆盖</p>
            <div className="space-y-2 max-h-56 overflow-auto pr-1">
              {Object.entries(AGENT_LABELS).map(([name, label]) => {
                const depth = agentDepths[name] ?? 'standard';
                return (
                  <div
                    key={name}
                    className="flex items-center justify-between gap-3 rounded border border-fin-border px-3 py-2"
                  >
                    <span className="text-xs text-fin-text">{label}</span>
                    <div className="flex gap-1">
                      {AGENT_DEPTH_OPTIONS.map((option) => (
                        <button
                          key={option}
                          type="button"
                          onClick={() => setDepth(name, option)}
                          className={`px-2 py-0.5 rounded text-2xs border ${
                            depth === option
                              ? option === 'off'
                                ? 'border-red-700/60 text-red-300 bg-red-900/20'
                                : option === 'deep'
                                  ? 'border-blue-700/60 text-blue-300 bg-blue-900/20'
                                  : 'border-fin-primary/60 text-fin-primary bg-fin-primary/10'
                              : 'border-fin-border text-fin-muted hover:text-fin-text'
                          }`}
                        >
                          {AGENT_DEPTH_LABELS[option]}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded border border-fin-border px-3 py-2">
            <p className="text-xs text-fin-muted mb-1">当前可用工具</p>
            {loadingCapabilities ? (
              <p className="text-xs text-fin-muted">加载中...</p>
            ) : (
              <div className="flex flex-wrap gap-1">
                {selectedTools.length > 0 ? (
                  selectedTools.map((tool) => (
                    <span
                      key={tool}
                      className="text-2xs px-1.5 py-0.5 rounded bg-fin-primary/10 text-fin-primary border border-fin-primary/30"
                    >
                      {tool}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-fin-muted">暂无可用工具</span>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded text-xs border border-fin-border text-fin-muted hover:text-fin-text"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleStart}
            disabled={selectedAgents.length === 0}
            className="px-3 py-1.5 rounded text-xs bg-fin-primary/15 text-fin-primary border border-fin-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            以此配置开始
          </button>
        </div>
      </Card>
    </Dialog>
  );
}

export default AnalysisConfigPanel;
