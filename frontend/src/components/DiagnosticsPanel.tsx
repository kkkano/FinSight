import { useEffect, useState } from 'react';
import { Activity, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
import { apiClient } from '../api/client';

interface OrchestratorStats {
  orchestrator: any;
  cache: any;
  sources: Record<string, any>;
}

interface DiagnosticsPanelProps {
  wrapperClassName?: string;
}

export const DiagnosticsPanel: React.FC<DiagnosticsPanelProps> = ({ wrapperClassName }) => {
  const [orch, setOrch] = useState<OrchestratorStats | null>(null);
  const [langgraph, setLanggraph] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      const [lg, oc] = await Promise.all([
        apiClient.diagnosticsLanggraph(),
        apiClient.diagnosticsOrchestrator(),
      ]);
      setLanggraph(lg?.data || lg);
      setOrch(oc?.data || oc);
    } catch (e) {
      console.error('Diagnostics fetch failed', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, []);

  const panelClass =
    'absolute left-0 top-full mt-2 w-80 rounded-lg border border-fin-border bg-fin-panel/90 p-3 text-xs text-fin-muted shadow-lg z-50';
  const wrapperClass = wrapperClassName || 'relative inline-flex';

  return (
    <div className={wrapperClass}>
      <div
        className="flex items-center gap-2 font-semibold text-fin-text cursor-pointer px-2 py-1 rounded border border-fin-border bg-fin-panel/70 hover:border-fin-primary transition-colors"
        onClick={() => setCollapsed(!collapsed)}
      >
        <Activity size={14} />
        健康面板
        {collapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
      </div>

      {!collapsed && (
        <div className={panelClass}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold text-fin-text">
              <Activity size={14} />
              健康面板
            </div>
            <button
              onClick={load}
              className="flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>

          <div className="mt-2 space-y-2">
            {orch && (
              <div>
                <div className="font-semibold text-fin-text">Orchestrator</div>
                <div>总请求: {orch.orchestrator?.total_requests ?? '—'}</div>
                <div>缓存命中: {orch.orchestrator?.cache_hits ?? '—'}</div>
                <div>回退次数: {orch.orchestrator?.fallback_used ?? '—'}</div>
                <div className="mt-1">
                  源健康:
                  {Object.entries(orch.sources || {}).map(([dtype, items]: any) => (
                    <div key={dtype} className="ml-2">
                      <div className="font-semibold text-fin-text">{dtype}</div>
                      {(items || []).map((s: any) => {
                        const fr = typeof s.fail_rate === 'number' ? s.fail_rate : null;
                        const cooldown = Math.max(0, Math.round(s.cooldown_remaining || 0));
                        return (
                          <div key={s.name} className="flex flex-wrap gap-2 text-[11px]">
                            <span>{s.name}</span>
                            <span>calls {s.total_calls}</span>
                            <span>succ {s.total_successes}</span>
                            <span>fail {s.consecutive_failures}</span>
                            {fr !== null && <span>fail_rate {(fr * 100).toFixed(0)}%</span>}
                            {cooldown > 0 && <span className="text-trend-down">cooldown {cooldown}s</span>}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {langgraph && (
              <div>
                <div className="font-semibold text-fin-text">LangGraph</div>
                <div>状态: {langgraph.available ? 'ready' : 'degraded'}</div>
                <div>模型: {langgraph.agent_info?.model ?? langgraph.self_check?.model ?? '—'}</div>
                <div>节点: {langgraph.self_check?.graph?.nodes?.join(', ') || '—'}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
