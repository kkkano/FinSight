import { useDashboardStore } from '../../store/dashboardStore';
import { SourceBadge } from '../ui/SourceBadge';

interface DashboardSourceBadgeProps {
  metaKey: string;
  fallbackSource?: string;
  className?: string;
}

/** 统一从 Dashboard 数据契约读取来源；没有 meta 的旧字段只展示已知 provider，不伪造日期。 */
export function DashboardSourceBadge({ metaKey, fallbackSource, className }: DashboardSourceBadgeProps) {
  const meta = useDashboardStore((state) => state.dashboardData?.meta?.[metaKey]);

  return (
    <SourceBadge
      source={meta?.provider ?? fallbackSource}
      asOf={meta?.as_of}
      degraded={meta?.fallback_used}
      className={className}
    />
  );
}
