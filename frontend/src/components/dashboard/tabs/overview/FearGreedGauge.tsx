import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import type { LatestReportData } from '../../../../hooks/useLatestReport';

interface FearGreedGaugeProps {
  reportData?: LatestReportData | null;
}

interface FearGreedValue {
  value: number | null;
  label: string;
  source: string;
}

const asRecord = (value: unknown): Record<string, unknown> | null => (
  value && typeof value === 'object' ? (value as Record<string, unknown>) : null
);

const scoreLabel = (value: number): string => {
  if (value <= 20) return '极度恐惧';
  if (value <= 40) return '恐惧';
  if (value <= 60) return '中性';
  if (value <= 80) return '贪婪';
  return '极度贪婪';
};

const extractFearGreedFromText = (text: string): number | null => {
  if (!text) return null;
  const normalized = text.replace(/\s+/g, ' ');
  const match = normalized.match(/(?:fear\s*&?\s*greed(?:\s*index)?|恐惧贪婪指数)[^0-9]{0,20}([0-9]{1,3})/i);
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
};

function resolveFearGreed(reportData: LatestReportData | null | undefined): FearGreedValue {
  const report = asRecord(reportData?.report);
  if (!report) {
    return { value: null, label: '--', source: '暂无报告数据' };
  }

  const meta = asRecord(report.meta);
  const agentSummaries = Array.isArray(meta?.agent_summaries) ? meta?.agent_summaries : [];
  for (const item of agentSummaries) {
    const node = asRecord(item);
    if (!node || String(node.agent_name || '') !== 'macro_agent') continue;
    const summary = String(node.summary || '');
    const parsed = extractFearGreedFromText(summary);
    if (parsed != null) {
      return {
        value: parsed,
        label: scoreLabel(parsed),
        source: '来源：macro_agent 摘要',
      };
    }
  }

  const agentStatus = asRecord(report.agent_status);
  const macro = asRecord(agentStatus?.macro_agent);
  const confidenceRaw = Number(macro?.confidence);
  if (Number.isFinite(confidenceRaw)) {
    const value = Math.max(0, Math.min(100, confidenceRaw <= 1 ? confidenceRaw * 100 : confidenceRaw));
    return {
      value,
      label: `${scoreLabel(value)}（近似）`,
      source: '来源：macro_agent 置信度近似',
    };
  }

  return { value: null, label: '--', source: 'macro_agent 未提供情绪值' };
}

export function FearGreedGauge({ reportData }: FearGreedGaugeProps) {
  const fearGreed = useMemo(() => resolveFearGreed(reportData), [reportData]);

  const option = useMemo(() => {
    if (fearGreed.value == null) return null;
    return {
      series: [
        {
          type: 'gauge',
          min: 0,
          max: 100,
          progress: {
            show: true,
            width: 10,
          },
          axisLine: {
            lineStyle: {
              width: 10,
              color: [
                [0.2, '#ef4444'],
                [0.4, '#f97316'],
                [0.6, '#f59e0b'],
                [0.8, '#22c55e'],
                [1, '#16a34a'],
              ],
            },
          },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: {
            distance: 10,
            color: '#9ca3af',
            fontSize: 10,
          },
          pointer: {
            icon: 'path://M12 2 L14 12 L10 12 Z',
            width: 8,
            length: '58%',
            itemStyle: { color: '#e5e7eb' },
          },
          detail: {
            valueAnimation: true,
            formatter: '{value}',
            offsetCenter: [0, '64%'],
            color: '#f9fafb',
            fontSize: 18,
            fontWeight: 700,
          },
          data: [{ value: Math.round(fearGreed.value) }],
        },
      ],
    };
  }, [fearGreed.value]);

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-fin-muted">市场情绪（Fear &amp; Greed）</span>
        <span className="text-2xs text-fin-muted">{fearGreed.label}</span>
      </div>

      {option ? (
        <ReactECharts option={option} style={{ width: '100%', height: 170 }} notMerge lazyUpdate />
      ) : (
        <div className="h-[170px] rounded-lg border border-dashed border-fin-border flex items-center justify-center text-fin-muted text-sm">
          暂无可用情绪值
        </div>
      )}

      <div className="mt-2 text-2xs text-fin-muted">{fearGreed.source}</div>
    </div>
  );
}

export default FearGreedGauge;
