import { DashboardSourceBadge } from './DashboardSourceBadge';

interface DashboardSourceItem {
  metaKey: string;
  fallbackSource?: string;
}

interface DashboardSourceBadgesProps {
  items: DashboardSourceItem[];
  className?: string;
}

/** 多来源派生卡片的紧凑来源列；每项仍读取后端 meta 的降级与时间信息。 */
export function DashboardSourceBadges({ items, className = '' }: DashboardSourceBadgesProps) {
  return (
    <div className={`flex flex-wrap items-center justify-end gap-x-2 gap-y-1 ${className}`.trim()}>
      {items.map((item) => (
        <DashboardSourceBadge
          key={item.metaKey}
          metaKey={item.metaKey}
          fallbackSource={item.fallbackSource}
        />
      ))}
    </div>
  );
}
