/**
 * Top Constituents Card - 成分股排行
 *
 * 用于展示指数的主要成分股权重
 */
import type { ChartPoint } from '../../types/dashboard';

interface TopConstituentsCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

export function TopConstituentsCard({
  data,
  loading,
  title = 'Top 成分股',
}: TopConstituentsCardProps) {
  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-64">
        <div className="h-4 bg-fin-border rounded w-24 mb-4" />
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="flex items-center gap-3 animate-pulse">
              <div className="h-4 bg-fin-border rounded w-12" />
              <div className="flex-1 h-4 bg-fin-border rounded" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-64 flex items-center justify-center text-fin-muted text-sm">
        暂无成分股数据
      </div>
    );
  }

  // 排序并取前 10
  const sortedData = [...data]
    .sort((a, b) => (b.weight || 0) - (a.weight || 0))
    .slice(0, 10);

  // 找出最大权重用于计算条形宽度
  const maxWeight = Math.max(...sortedData.map((d) => d.weight || 0));

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-4">
      <h3 className="text-sm font-semibold text-fin-text mb-3">{title}</h3>
      <div className="space-y-2">
        {sortedData.map((item, index) => {
          const weight = item.weight || 0;
          const widthPercent = maxWeight > 0 ? (weight / maxWeight) * 100 : 0;

          return (
            <div key={item.symbol || index} className="flex items-center gap-3">
              {/* 排名 */}
              <span className="w-5 text-xs text-fin-muted text-right">
                {index + 1}
              </span>

              {/* Symbol */}
              <span className="w-14 text-xs font-medium text-fin-text truncate">
                {item.symbol}
              </span>

              {/* 进度条 */}
              <div className="flex-1 h-5 bg-fin-bg-secondary rounded overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-400 to-blue-500 rounded transition-all duration-500"
                  style={{ width: `${widthPercent}%` }}
                />
              </div>

              {/* 权重 */}
              <span className="w-12 text-xs text-fin-muted text-right">
                {(weight * 100).toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default TopConstituentsCard;
