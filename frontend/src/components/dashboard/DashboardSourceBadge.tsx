import { useDashboardSnapshot } from '../../hooks/useDashboardData';
import { sourceDisplayName } from '../../utils/sourceDisplayName';
interface DashboardSourceBadgeProps { metaKey: string; fallbackSource?: string; className?: string }
export function DashboardSourceBadge({metaKey,fallbackSource,className}:DashboardSourceBadgeProps){
  const meta=useDashboardSnapshot()?.meta?.[metaKey];
  const source=sourceDisplayName(meta?.provider||fallbackSource);
  const date=meta?.as_of?meta.as_of.slice(0,10):'日期未注明';
  return <span className={`design-caption ${className||''}`} title={meta?.fallback_reason||undefined}>{source} · <span className="num">{date}</span>{meta?.status&&['error','missing','empty'].includes(meta.status)?' · 数据暂无':''}</span>;
}
