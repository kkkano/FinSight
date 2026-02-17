/**
 * AgentControlPanel — user preferences for agent depth, budget, and concurrency.
 *
 * Persisted to localStorage (`finsight-agent-preferences`) and synced to backend.
 * Backend performs whitelist validation; frontend values are only input.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { apiClient } from '../../api/client';
import { deriveUserIdFromSessionId, useStore } from '../../store/useStore';
import { Card } from '../ui/Card';

const AGENT_NAMES = [
  { key: 'price_agent', label: '价格分析' },
  { key: 'news_agent', label: '新闻分析' },
  { key: 'fundamental_agent', label: '基本面' },
  { key: 'technical_agent', label: '技术面' },
  { key: 'risk_agent', label: '风险分析' },
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

const normalizePreferences = (raw: unknown): AgentPreferences => {
  const parsed = typeof raw === 'object' && raw !== null ? (raw as Partial<AgentPreferences>) : {};
  const inputAgents =
    typeof parsed.agents === 'object' && parsed.agents !== null
      ? (parsed.agents as Record<string, unknown>)
      : {};

  const agents: Record<string, AgentDepth> = Object.fromEntries(
    AGENT_NAMES.map(({ key }) => {
      const depthRaw = String(inputAgents[key] ?? 'standard').toLowerCase();
      const depth = depthRaw === 'deep' || depthRaw === 'off' ? depthRaw : 'standard';
      return [key, depth as AgentDepth];
    }),
  );

  const roundsRaw = Number(parsed.maxRounds);
  const maxRounds = Number.isFinite(roundsRaw)
    ? Math.max(1, Math.min(10, Math.trunc(roundsRaw)))
    : DEFAULT_PREFS.maxRounds;

  const concurrentMode =
    typeof parsed.concurrentMode === 'boolean'
      ? parsed.concurrentMode
      : DEFAULT_PREFS.concurrentMode;

  return { agents, maxRounds, concurrentMode };
};

function loadPreferences(): AgentPreferences {
  if (typeof window === 'undefined') return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    return normalizePreferences(JSON.parse(raw));
  } catch {
    return DEFAULT_PREFS;
  }
}

let preferenceCache: AgentPreferences = loadPreferences();

function savePreferences(prefs: AgentPreferences): void {
  preferenceCache = prefs;
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // ignore localStorage failures
  }
}

// eslint-disable-next-line react-refresh/only-export-components
export function getAgentPreferences(): AgentPreferences {
  return preferenceCache;
}

const DEPTH_OPTIONS: { value: AgentDepth; label: string }[] = [
  { value: 'standard', label: '标准' },
  { value: 'deep', label: '深度' },
  { value: 'off', label: '关闭' },
];

function depthButtonClass(depth: AgentDepth, isActive: boolean): string {
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

export const AgentControlPanel: React.FC = () => {
  const sessionId = useStore((state) => state.sessionId);
  const userId = useMemo(() => deriveUserIdFromSessionId(sessionId), [sessionId]);
  const [prefs, setPrefs] = useState<AgentPreferences>(() => preferenceCache);

  useEffect(() => {
    const localPrefs = loadPreferences();
    preferenceCache = localPrefs;
    setPrefs(localPrefs);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const syncFromApi = async () => {
      try {
        const response = await apiClient.getAgentPreferences(userId);
        if (!response?.success || !response.preferences || cancelled) return;
        const normalized = normalizePreferences(response.preferences);
        savePreferences(normalized);
        setPrefs(normalized);
      } catch {
        // keep local preferences when API unavailable
      }
    };
    void syncFromApi();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const persist = useCallback(
    (updater: (previous: AgentPreferences) => AgentPreferences) => {
      setPrefs((previous) => {
        const next = normalizePreferences(updater(previous));
        savePreferences(next);
        void apiClient
          .updateAgentPreferences({ user_id: userId, preferences: next })
          .catch(() => undefined);
        return next;
      });
    },
    [userId],
  );

  const setAgentDepth = useCallback(
    (agentKey: string, depth: AgentDepth) => {
      persist((previous) => ({
        ...previous,
        agents: { ...previous.agents, [agentKey]: depth },
      }));
    },
    [persist],
  );

  const setMaxRounds = useCallback(
    (value: number) => {
      persist((previous) => ({
        ...previous,
        maxRounds: Math.max(1, Math.min(10, value)),
      }));
    },
    [persist],
  );

  const setConcurrentMode = useCallback(
    (enabled: boolean) => {
      persist((previous) => ({ ...previous, concurrentMode: enabled }));
    },
    [persist],
  );

  return (
    <Card className="p-4 bg-fin-bg/40">
      <h3 className="text-sm font-medium text-fin-text mb-3">
        Agent 控制面板
      </h3>

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
