/**
 * Snapshot Card - KPI 指标快照
 *
 * 显示 4 个关键指标：Revenue, EPS, Gross Margin, FCF
 * 或对于 Index/ETF/Crypto：Index Level, NAV 等
 */
import type { SnapshotData } from '../../types/dashboard';

interface SnapshotCardProps {
  data: SnapshotData;
  loading?: boolean;
}

// 格式化数字
const formatNumber = (value: number | null | undefined, type: string): string => {
  if (value === null || value === undefined) return '--';

  switch (type) {
    case 'currency':
      if (value >= 1e12) return `$${(value / 1e12).toFixed(1)}T`;
      if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
      if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
      return `$${value.toLocaleString()}`;
    case 'percent':
      return `${(value * 100).toFixed(1)}%`;
    case 'price':
      return value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    default:
      return value.toLocaleString();
  }
};

// 指标配置
const getMetrics = (data: SnapshotData) => {
  const metrics = [];

  if (data.revenue !== undefined && data.revenue !== null) {
    metrics.push({
      label: '营收',
      value: formatNumber(data.revenue, 'currency'),
      color: 'text-blue-500',
      bgColor: 'bg-blue-50',
    });
  }

  if (data.eps !== undefined && data.eps !== null) {
    metrics.push({
      label: 'EPS',
      value: `$${data.eps.toFixed(2)}`,
      color: 'text-green-500',
      bgColor: 'bg-green-50',
    });
  }

  if (data.gross_margin !== undefined && data.gross_margin !== null) {
    metrics.push({
      label: '毛利率',
      value: formatNumber(data.gross_margin, 'percent'),
      color: 'text-purple-500',
      bgColor: 'bg-purple-50',
    });
  }

  if (data.fcf !== undefined && data.fcf !== null) {
    metrics.push({
      label: '自由现金流',
      value: formatNumber(data.fcf, 'currency'),
      color: 'text-orange-500',
      bgColor: 'bg-orange-50',
    });
  }

  if (data.index_level !== undefined && data.index_level !== null) {
    metrics.push({
      label: '指数点位',
      value: formatNumber(data.index_level, 'price'),
      color: 'text-indigo-500',
      bgColor: 'bg-indigo-50',
    });
  }

  if (data.nav !== undefined && data.nav !== null) {
    metrics.push({
      label: 'NAV',
      value: `$${formatNumber(data.nav, 'price')}`,
      color: 'text-teal-500',
      bgColor: 'bg-teal-50',
    });
  }

  return metrics;
};

export function SnapshotCard({ data, loading }: SnapshotCardProps) {
  const metrics = getMetrics(data);

  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="animate-pulse">
              <div className="h-4 bg-fin-border rounded w-16 mb-2" />
              <div className="h-8 bg-fin-border rounded w-24" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (metrics.length === 0) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 text-center text-fin-muted text-sm">
        暂无指标数据
      </div>
    );
  }

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {metrics.map((metric, index) => (
          <div
            key={index}
            className={`${metric.bgColor} rounded-lg p-3 transition-transform hover:scale-105`}
          >
            <div className="text-xs text-fin-muted mb-1">{metric.label}</div>
            <div className={`text-xl font-bold ${metric.color}`}>
              {metric.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default SnapshotCard;
