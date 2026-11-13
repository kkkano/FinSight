import { useDashboardSnapshot } from '../../hooks/useDashboardData';
import { sourceDisplayName } from '../../utils/sourceDisplayName';
import { zh } from '../../locales/zh';
interface DashboardSourceBadgeProps { metaKey: string; fallbackSource?: string; className?: string }
export function DashboardSourceBadge({metaKey,fallbackSource,className}:DashboardSourceBadgeProps){
  const meta=useDashboardSnapshot()?.meta?.[metaKey];
  const source=sourceDisplayName(meta?.provider||fallbackSource);
  const date=meta?.as_of?meta.as_of.replace('T',' ').replace('Z',' UTC'):zh.dashboard.asOfUnknown;
  const estimated=meta?.estimated === true || meta?.source_type === 'estimated';
  const delayed=meta?.delayed === true || (typeof meta?.delay_minutes === 'number' && meta.delay_minutes > 0);
  return <span className={`design-caption ${className||''}`}>{source} · <span className="num">{date}</span>
    {meta?.status&&['error','missing','empty'].includes(meta.status)?` · ${zh.dashboard.missing}`:''}
    {delayed?` · ${zh.dashboard.delayed}${meta?.delay_minutes ? ` ${meta.delay_minutes} 分钟` : ''}`:''}
    {estimated?` · ${zh.dashboard.estimated}`:''}</span>;
}
