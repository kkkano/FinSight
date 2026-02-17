import { useMemo, useState } from 'react';
import { AlertTriangle, Info, XCircle } from 'lucide-react';

import { Dialog } from '../ui';
import type { DataSourceMeta } from '../../types/dashboard';

interface DataSourceTraceProps {
  meta?: Record<string, DataSourceMeta>;
}

interface SourceRow {
  key: string;
  label: string;
  staleLevel: 'ok' | 'warn' | 'critical' | 'unknown';
  ageMinutes: number | null;
  meta: DataSourceMeta;
}

const LABEL_MAP: Record<string, string> = {
  snapshot: '核心快照',
  market_chart: '价格走势',
  revenue_trend: '营收趋势',
  segment_mix: '收入结构',
  sector_weights: '行业权重',
  top_constituents: '主要成分',
  holdings: '持仓明细',
  news_market: '市场新闻',
  news_impact: '影响新闻',
  valuation: '估值数据',
  financials: '财务报表',
  technicals: '技术指标',
  peers: '同业对比',
};

const STALE_RULES_MINUTES: Record<string, { warn: number; critical: number }> = {
  snapshot: { warn: 15, critical: 120 },
  market_chart: { warn: 1440, critical: 4320 },
  revenue_trend: { warn: 4320, critical: 20160 },
  segment_mix: { warn: 4320, critical: 20160 },
  sector_weights: { warn: 4320, critical: 20160 },
  top_constituents: { warn: 4320, critical: 20160 },
  holdings: { warn: 4320, critical: 20160 },
  valuation: { warn: 4320, critical: 20160 },
  financials: { warn: 4320, critical: 20160 },
  technicals: { warn: 1440, critical: 4320 },
  peers: { warn: 4320, critical: 20160 },
  news_market: { warn: 240, critical: 1440 },
  news_impact: { warn: 240, critical: 1440 },
};

function formatDateTime(iso: string): string {
  if (!iso) return '--';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString();
}

function getAgeMinutes(iso: string): number | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const diff = Date.now() - date.getTime();
  if (diff < 0) return 0;
  return Math.floor(diff / 60000);
}

function toStaleLevel(
  key: string,
  ageMinutes: number | null,
): 'ok' | 'warn' | 'critical' | 'unknown' {
  if (ageMinutes === null) return 'unknown';
  const rule = STALE_RULES_MINUTES[key] ?? { warn: 1440, critical: 10080 };
  if (ageMinutes >= rule.critical) return 'critical';
  if (ageMinutes >= rule.warn) return 'warn';
  return 'ok';
}

function staleText(level: SourceRow['staleLevel']): string {
  if (level === 'critical') return '陈旧';
  if (level === 'warn') return '偏旧';
  if (level === 'ok') return '正常';
  return '未知';
}

function staleClass(level: SourceRow['staleLevel']): string {
  if (level === 'critical') return 'bg-fin-danger/10 text-fin-danger border-fin-danger/40';
  if (level === 'warn') return 'bg-fin-warning/10 text-fin-warning border-fin-warning/40';
  if (level === 'ok') return 'bg-fin-success/10 text-fin-success border-fin-success/40';
  return 'bg-fin-hover text-fin-muted border-fin-border';
}

function buildRows(meta?: Record<string, DataSourceMeta>): SourceRow[] {
  if (!meta) return [];
  return Object.entries(meta)
    .map(([key, value]) => {
      const ageMinutes = getAgeMinutes(value.as_of);
      return {
        key,
        label: LABEL_MAP[key] ?? key,
        staleLevel: toStaleLevel(key, ageMinutes),
        ageMinutes,
        meta: value,
      };
    })
    .sort((a, b) => {
      const order = { critical: 0, warn: 1, unknown: 2, ok: 3 };
      return order[a.staleLevel] - order[b.staleLevel] || a.label.localeCompare(b.label);
    });
}

export function DataSourceTrace({ meta }: DataSourceTraceProps) {
  const [open, setOpen] = useState(false);
  const rows = useMemo(() => buildRows(meta), [meta]);
  const summary = useMemo(() => {
    let critical = 0;
    let warn = 0;
    let fallback = 0;
    for (const row of rows) {
      if (row.staleLevel === 'critical') critical += 1;
      else if (row.staleLevel === 'warn') warn += 1;
      if (row.meta.fallback_used) fallback += 1;
    }
    return { total: rows.length, critical, warn, fallback };
  }, [rows]);

  if (!rows.length) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary text-xs"
        title="查看数据来源与降级信息"
      >
        <Info size={14} />
        <span>数据来源</span>
        {(summary.critical > 0 || summary.fallback > 0) && (
          <span className="inline-flex items-center gap-1 rounded-full bg-fin-danger/10 text-fin-danger px-1.5 py-0.5 text-[10px]">
            <AlertTriangle size={10} />
            {summary.critical + summary.fallback}
          </span>
        )}
      </button>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        labelledBy="dashboard-source-title"
        panelClassName="w-full max-w-4xl max-h-[82vh] overflow-hidden bg-fin-card border border-fin-border rounded-xl shadow-2xl"
      >
        <div className="p-4 border-b border-fin-border flex items-center justify-between">
          <div>
            <h3 id="dashboard-source-title" className="text-base font-semibold text-fin-text">
              数据来源与可追踪信息
            </h3>
            <p className="text-xs text-fin-muted mt-1">
              共 {summary.total} 项，陈旧 {summary.critical}，偏旧 {summary.warn}，降级 {summary.fallback}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="p-1.5 rounded-md border border-fin-border text-fin-muted hover:text-fin-text hover:bg-fin-hover"
            aria-label="关闭数据来源弹窗"
          >
            <XCircle size={16} />
          </button>
        </div>

        <div className="p-4 overflow-y-auto max-h-[70vh] space-y-3">
          {rows.map((row) => (
            <section key={row.key} className="rounded-lg border border-fin-border bg-fin-bg/60 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-fin-text">{row.label}</div>
                  <div className="text-xs text-fin-muted mt-0.5">
                    {row.meta.provider} / {row.meta.source_type}
                  </div>
                </div>
                <span className={`text-2xs px-2 py-0.5 rounded-full border ${staleClass(row.staleLevel)}`}>
                  {staleText(row.staleLevel)}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 text-xs text-fin-text-secondary mt-3">
                <div>更新时间：{formatDateTime(row.meta.as_of)}</div>
                <div>数据时延：{row.meta.latency_ms} ms</div>
                <div>置信度：{Math.round((row.meta.confidence ?? 0) * 100)}%</div>
                <div>统计口径：{row.meta.calc_window || '--'}</div>
                <div>货币：{row.meta.currency || '--'}</div>
                <div>
                  距今：{row.ageMinutes === null ? '--' : `${row.ageMinutes} 分钟`}
                </div>
              </div>

              {row.meta.fallback_used && (
                <div className="mt-2 text-xs text-fin-warning bg-fin-warning/10 border border-fin-warning/30 rounded-md px-2 py-1.5">
                  降级原因：{row.meta.fallback_reason || '上游数据不可用'}
                </div>
              )}
            </section>
          ))}
        </div>
      </Dialog>
    </>
  );
}

export default DataSourceTrace;
