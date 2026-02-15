/**
 * AgentControlPanel — user preferences for agent depth, budget, and concurrency.
 *
 * Persisted to localStorage (`finsight-agent-preferences`).
 * Backend performs whitelist validation — frontend values are only input.
 */
import React, { useCallback, useEffect, useState } from 'react';

import { Card } from '../ui/Card';

// --- Constants ---

const AGENT_NAMES = [
  { key: 'price_agent', label: '价格分析' },
  { key: 'news_agent', label: '新闻分析' },
  { key: 'fundamental_agent', label: '基本面' },
  { key: 'technical_agent', label: '技术面' },
  { key: 'macro_agent', label: '宏观分析' },
  { key: 'deep_search_agent', label: '深度搜索' },
] as const;

type AgentDepth = 'standard' | 'deep' | 'off';

export interface AgentPreferences {
  agents: Record<string, AgentDepth>;
  maxRounds: number;
  concurrentMode: boolean;
}

const STORAGE_KEY = 'finsight-agent-preferences';

const DEFAULT_PREFS: AgentPreferences = {
  agents: Object.fromEntries(
    AGENT_NAMES.map(({ key }) => [key, 'standard' as AgentDepth]),
  ),
  maxRounds: 3,
  concurrentMode: true,
};

// --- Persistence helpers ---

function loadPreferences(): AgentPreferences {
  if (typeof window === 'undefined') return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw);
    return {
      agents: { ...DEFAULT_PREFS.agents, ...(parsed.agents ?? {}) },
      maxRounds: Math.max(
        1,
        Math.min(10, Number(parsed.maxRounds) || DEFAULT_PREFS.maxRounds),
      ),
      concurrentMode: parsed.concurrentMode !== false,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

function savePreferences(prefs: AgentPreferences): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // localStorage quota or unavailable — ignore
  }
}

/** Read current preferences (for use outside React components). */
export function getAgentPreferences(): AgentPreferences {
  return loadPreferences();
}

// --- Depth option config ---

const DEPTH_OPTIONS: { value: AgentDepth; label: string }[] = [
  { value: 'standard', label: '标准' },
  { value: 'deep', label: '深度' },
  { value: 'off', label: '关闭' },
];

function depthButtonClass(
  depth: AgentDepth,
  isActive: boolean,
): string {
  if (!isActive) {
    return 'bg-fin-bg border border-fin-border text-fin-muted hover:text-fin-text';
  }
  if (depth === 'off') {
    return 'bg-red-900/30 text-red-300 border border-red-700/50';
  }
  if (depth === 'deep') {
    return 'bg-blue-900/30 text-blue-300 border border-blue-700/50';
  }
  return 'bg-fin-primary/10 text-fin-primary border border-fin-primary/30';
}

// --- Component ---

export const AgentControlPanel: React.FC = () => {
  const [prefs, setPrefs] = useState<AgentPreferences>(DEFAULT_PREFS);

  useEffect(() => {
    setPrefs(loadPreferences());
  }, []);

  const persist = useCallback((next: AgentPreferences) => {
    setPrefs(next);
    savePreferences(next);
  }, []);

  const setAgentDepth = useCallback(
    (agentKey: string, depth: AgentDepth) => {
      persist({
        ...prefs,
        agents: { ...prefs.agents, [agentKey]: depth },
      });
    },
    [prefs, persist],
  );

  const setMaxRounds = useCallback(
    (value: number) => {
      persist({ ...prefs, maxRounds: Math.max(1, Math.min(10, value)) });
    },
    [prefs, persist],
  );

  const setConcurrentMode = useCallback(
    (enabled: boolean) => {
      persist({ ...prefs, concurrentMode: enabled });
    },
    [prefs, persist],
  );

  return (
    <Card className="p-4 bg-fin-bg/40">
      <h3 className="text-sm font-medium text-fin-text mb-3">
        Agent 控制面板
      </h3>

      {/* Agent depth grid */}
      <div className="space-y-2 mb-4">
        {AGENT_NAMES.map(({ key, label }) => (
          <div key={key} className="flex items-center justify-between gap-3">
            <span className="text-xs text-fin-text min-w-20">{label}</span>
            <div className="flex gap-1">
              {DEPTH_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setAgentDepth(key, opt.value)}
                  className={`px-2 py-0.5 rounded text-2xs transition-colors ${depthButtonClass(
                    opt.value,
                    prefs.agents[key] === opt.value,
                  )}`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Budget slider */}
      <div className="mb-4">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-fin-muted">预算上限（轮次）</span>
          <span className="text-fin-text font-medium">{prefs.maxRounds}</span>
        </div>
        <input
          type="range"
          min={1}
          max={10}
          step={1}
          value={prefs.maxRounds}
          onChange={(e) => setMaxRounds(Number(e.target.value))}
          className="w-full accent-fin-primary h-1.5"
        />
        <div className="flex justify-between text-2xs text-fin-muted mt-0.5">
          <span>1</span>
          <span>10</span>
        </div>
      </div>

      {/* Concurrent mode */}
      <label className="inline-flex items-center gap-2 text-xs text-fin-muted cursor-pointer">
        <input
          type="checkbox"
          checked={prefs.concurrentMode}
          onChange={(e) => setConcurrentMode(e.target.checked)}
          className="accent-fin-primary"
        />
        Agent 并发执行
      </label>

      <p className="text-2xs text-fin-muted mt-3">
        设置仅影响投资报告生成时的 Agent 选择。后端会对设置做白名单校验。
      </p>
    </Card>
  );
};
