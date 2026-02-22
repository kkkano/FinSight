import { useMemo } from 'react';

import type { NewsItem, TechnicalData, ValuationData } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';
import { CardInfoTip } from '../../../ui/CardInfoTip';

interface DimensionRadarProps {
  valuation?: ValuationData | null;
  technicals?: TechnicalData | null;
  news?: NewsItem[];
  reportData?: LatestReportData | null;
}

type DimensionStatus = 'ok' | 'not_run' | 'error';

interface Dimension {
  name: string;
  value: number;
  status: DimensionStatus;
}

type AgentStatusKind = 'success' | 'fallback' | 'error' | 'not_run' | 'unknown';

interface AgentSignal {
  status: AgentStatusKind;
  confidence: number | null;
}

const clampPercent = (value: number): number => Math.max(0, Math.min(100, Math.round(value)));

const normalizeAgentStatus = (value: unknown): AgentStatusKind => {
  const raw = String(value || '').trim().toLowerCase();
  if (raw === 'success') return 'success';
  if (raw === 'fallback') return 'fallback';
  if (raw === 'error') return 'error';
  if (raw === 'not_run' || raw === 'skipped') return 'not_run';
  return 'unknown';
};

const readAgentSignal = (
  reportData: LatestReportData | null | undefined,
  candidates: string[],
): AgentSignal => {
  const report = reportData?.report as Record<string, unknown> | undefined;
  const agentStatus = report?.agent_status as Record<string, any> | undefined;
  if (!agentStatus || typeof agentStatus !== 'object') {
    return { status: 'not_run', confidence: null };
  }

  for (const key of candidates) {
    const node = agentStatus[key];
    if (!node || typeof node !== 'object') continue;
    const confidenceRaw = node.confidence ?? node.score;
    const confidence = Number(confidenceRaw);
    return {
      status: normalizeAgentStatus(node.status),
      confidence: Number.isFinite(confidence)
        ? (confidence <= 1 ? clampPercent(confidence * 100) : clampPercent(confidence))
        : null,
    };
  }

  return { status: 'not_run', confidence: null };
};

const toDimensionFromAgent = (name: string, signal: AgentSignal): Dimension => {
  if (signal.confidence != null) {
    return { name, value: signal.confidence, status: 'ok' };
  }
  if (signal.status === 'error') {
    return { name, value: 0, status: 'error' };
  }
  return { name, value: 0, status: 'not_run' };
};

function computeDimensions(
  valuation: ValuationData | null | undefined,
  technicals: TechnicalData | null | undefined,
  news: NewsItem[] | undefined,
  reportData: LatestReportData | null | undefined,
): Dimension[] {
  const fundamentalSignal = readAgentSignal(reportData, ['fundamental_agent']);
  const technicalSignal = readAgentSignal(reportData, ['technical_agent']);
  const newsSignal = readAgentSignal(reportData, ['news_agent']);
  const deepSignal = readAgentSignal(reportData, ['deep_search_agent', 'deep_research_agent']);
  const macroSignal = readAgentSignal(reportData, ['macro_agent']);

  let fundamentals = toDimensionFromAgent('基本面', fundamentalSignal);
  if (valuation) {
    const fields = [
      valuation.trailing_pe,
      valuation.forward_pe,
      valuation.price_to_book,
      valuation.ev_to_ebitda,
      valuation.dividend_yield,
      valuation.market_cap,
    ];
    const filled = fields.filter((field) => field != null).length;
    fundamentals = {
      name: '基本面',
      value: clampPercent((filled / fields.length) * 100),
      status: 'ok',
    };
  }

  let technical = toDimensionFromAgent('技术面', technicalSignal);
  if (technicals) {
    const fields = [
      technicals.rsi,
      technicals.macd,
      technicals.ma50,
      technicals.ma200,
      technicals.ema12,
      technicals.adx,
      technicals.cci,
    ];
    const filled = fields.filter((field) => field != null).length;
    technical = {
      name: '技术面',
      value: clampPercent((filled / fields.length) * 100),
      status: 'ok',
    };
  }

  let newsDimension = toDimensionFromAgent('新闻情绪', newsSignal);
  const newsList = news ?? [];
  if (newsList.length > 0) {
    const newsCountScore = Math.min(100, newsList.length * 10);
    const relevanceList = newsList
      .map((item) => item.asset_relevance)
      .filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
    const relevanceAvg = relevanceList.length
      ? relevanceList.reduce((sum, value) => sum + value, 0) / relevanceList.length
      : null;
    const score = relevanceAvg == null
      ? newsCountScore
      : clampPercent(newsCountScore * (0.6 + 0.4 * relevanceAvg));
    newsDimension = { name: '新闻情绪', value: score, status: 'ok' };
  }

  return [
    fundamentals,
    technical,
    newsDimension,
    toDimensionFromAgent('深度研究', deepSignal),
    toDimensionFromAgent('宏观环境', macroSignal),
  ];
}

const statusText = (item: Dimension): string => {
  if (item.status === 'not_run') return '未执行';
  if (item.status === 'error') return '失败';
  return `${item.value}%`;
};

const statusTextClass = (item: Dimension): string => {
  if (item.status === 'not_run') return 'text-fin-muted';
  if (item.status === 'error') return 'text-fin-danger';
  return 'text-fin-text-secondary';
};

const progressClass = (item: Dimension): string => {
  if (item.status === 'not_run') return 'bg-fin-border';
  if (item.status === 'error') return 'bg-fin-danger';
  if (item.value >= 70) return 'bg-fin-success';
  if (item.value >= 40) return 'bg-fin-warning';
  if (item.value > 0) return 'bg-fin-danger';
  return 'bg-fin-border';
};

export function DimensionRadar({ valuation, technicals, news, reportData }: DimensionRadarProps) {
  const dimensions = useMemo(
    () => computeDimensions(valuation, technicals, news, reportData),
    [valuation, technicals, news, reportData],
  );

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center gap-1 text-xs font-medium text-fin-muted mb-3">
        分析维度覆盖
        <CardInfoTip content="未执行与失败会单独标注，不再与 0% 混淆。" />
      </div>

      <div className="space-y-2.5">
        {dimensions.map((item) => (
          <div key={item.name} className="flex items-center gap-2">
            <span className="text-2xs text-fin-muted w-16 shrink-0 text-right">{item.name}</span>
            <div className="flex-1 h-2 bg-fin-border rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${progressClass(item)}`}
                style={{ width: `${item.value}%` }}
              />
            </div>
            <span className={`text-2xs tabular-nums w-12 text-right ${statusTextClass(item)}`}>
              {statusText(item)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default DimensionRadar;
