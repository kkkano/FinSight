import type { ValuationData, SnapshotData } from '../../types/dashboard';
import { formatMoney, formatMarketCapForMarket, formatDividendYield } from '../../utils/format';
import { DashboardSourceBadge } from './DashboardSourceBadge';
import { DashboardSourceBadges } from './DashboardSourceBadges';
import { useDashboardSnapshot } from '../../hooks/useDashboardData';
import { dashboardResearchContext } from '../../utils/dashboardResearchContext';
import type { DashboardResearchContext } from '../../types/chatHandoff';
interface MetricsBarProps {valuation?:ValuationData|null;snapshot?:SnapshotData|null;ticker?:string|null;loading?:boolean;onSelectMetric?:(context:DashboardResearchContext)=>void}
const valid=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
export function MetricsBar({valuation,snapshot,ticker,loading,onSelectMetric}:MetricsBarProps){
  const metadata=useDashboardSnapshot()?.meta;
  const v=valuation||{};const s=snapshot||{};
  const metrics=[{label:'总市值',raw:v.market_cap,value:formatMarketCapForMarket(v.market_cap,ticker,v.market_cap_currency),meta:'valuation'},
    {label:'市盈率',raw:v.trailing_pe,value:valid(v.trailing_pe)?v.trailing_pe.toFixed(1):'',meta:'valuation'},
    {label:'市净率',raw:v.price_to_book,value:valid(v.price_to_book)?v.price_to_book.toFixed(1):'',meta:'valuation'},
    {label:'每股收益',raw:s.eps,value:formatMoney(s.eps,s.financial_currency),meta:'financials'},
    {label:'股息率',raw:v.dividend_yield,value:formatDividendYield(v.dividend_yield),meta:'valuation'},
    {label:'市场敏感度',raw:v.beta,value:valid(v.beta)?v.beta.toFixed(2):'',meta:'valuation'},
    {label:'52周最低',raw:v.week52_low,value:formatMoney(v.week52_low,v.currency),meta:'valuation'},
    {label:'52周最高',raw:v.week52_high,value:formatMoney(v.week52_high,v.currency),meta:'valuation'}];
  const metricIds=['market_cap','trailing_pe','price_to_book','eps','dividend_yield','beta','week52_low','week52_high'];
  return <section className="design-card" aria-label="关键指标"><div className="dashboard-card-title"><h2>关键指标</h2><DashboardSourceBadges items={[{metaKey:'valuation'},{metaKey:'financials'}]}/></div><dl className="dashboard-metrics">{metrics.map((item,index)=><div key={item.label} className="dashboard-metric"><dt>{item.label}</dt>{loading?<dd className="t-skeleton h-6 w-16"/>:<dd className="num">{valid(item.raw)?item.value:'暂无'}</dd>}<small><DashboardSourceBadge metaKey={item.meta}/>{!loading&&!valid(item.raw)&&<span className="block">来源未返回该指标</span>}</small>{onSelectMetric&&<button type="button" className="mt-1 text-xs text-t-accent" onClick={()=>onSelectMetric(dashboardResearchContext(metadata?.[item.meta],{id:metricIds[index],label:item.label,value:valid(item.raw)?item.raw:null,unit:index===0?v.market_cap_currency:index===3?s.financial_currency:index>=6?v.currency:null}))}>问 AI</button>}</div>)}</dl></section>;
}
export default MetricsBar;
