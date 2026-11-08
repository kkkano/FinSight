import { Star, MessageSquare } from 'lucide-react';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useWatchlist } from '../../hooks/useWatchlist';
import { useCompanyProfile, exchangeDisplayName } from '../../hooks/useCompanyProfile';
import { useDashboardSnapshot } from '../../hooks/useDashboardData';
import { useStore } from '../../store/useStore';
import { apiClient } from '../../api/client';
import type { SnapshotData, ChartPoint, ValuationData } from '../../types/dashboard';
import { sourceDisplayName } from '../../utils/sourceDisplayName';
import { useToast } from '../ui';

interface StockHeaderProps { ticker: string; displayName: string; assetType: string; snapshot: SnapshotData; charts: Record<string, ChartPoint[]>; valuation?: ValuationData | null; loading?: boolean; onResearch?: () => void; controls?: ReactNode }
export function StockHeader({ticker,displayName,snapshot,charts,loading,onResearch,controls}:StockHeaderProps) {
  const {watchlist,addWatchItemApi,removeWatchItemApi}=useWatchlist();
  const owner=useStore(state=>state.authIdentity?.userId);
  const data=useDashboardSnapshot();
  const company=useCompanyProfile(ticker);
  const companyName=company.data?.status==='ok'?(company.data.name_zh||company.data.name||displayName):displayName;
  const exchange=exchangeDisplayName(company.data?.status==='ok'?company.data.exchange:null);
  const {toast}=useToast();
  const quote=useQuery({queryKey:['dashboard-quote',ticker],queryFn:({signal})=>apiClient.fetchStockPrice(ticker,signal),enabled:Boolean(ticker),staleTime:60_000,retry:1});
  const envelope=quote.data?.data;const value=envelope?.data;
  const latest=charts.market_chart?.at(-1);const prior=charts.market_chart?.at(-2);
  const close=value?.price??snapshot.index_level??snapshot.nav??latest?.close??latest?.value;
  const previous=prior?.close??prior?.value;
  const change=value?.change??(close!=null&&previous!=null?close-previous:null);
  const percent=value?.change_percent??(change!=null&&previous?change/previous*100:null);
  const kind=value?.data_kind??envelope?.data_kind;
  const quoteDetails=value as typeof value & {market_session?:string;delay_seconds?:number;exchange?:string};
  const timestamp=value?.source_timestamp??envelope?.as_of??data?.meta?.market_chart?.as_of;
  const source=sourceDisplayName(envelope?.provider??data?.meta?.market_chart?.provider);
  const session=quoteDetails?.market_session;
  const isDaily=kind==='daily_close'||session==='regular_close'||(!value&&Boolean(latest));
  const timeText=timestamp?isDaily?timestamp.slice(5,10).replace('-','/'):/^\d{4}-\d{2}-\d{2}$/.test(timestamp)?timestamp.slice(5).replace('-','/'):new Intl.DateTimeFormat('zh-CN',{timeZone:'America/New_York',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(timestamp))+' ET':'时间未注明';
  const status=isDaily?`${timeText} 收盘价 · 非实时 · ${source}`:`${({pre_market:'盘前',after_hours:'盘后',regular:'盘中'} as Record<string,string>)[session||'']||'行情快照'} · ${quoteDetails?.delay_seconds!=null?`延迟 ${Math.round(quoteDetails.delay_seconds/60)} 分钟`:'延迟情况未注明'} · ${timeText} · ${source}`;
  const inWatchlist=watchlist.some(item=>item.symbol===ticker);
  const toggle=async()=>{try{if(inWatchlist)await removeWatchItemApi(ticker);else await addWatchItemApi(ticker);}catch(error){toast({type:'error',title:'自选操作未完成',message:error instanceof Error?error.message:'请稍后重试'});}};
  return <header className="dashboard-header"><div><div className="dashboard-stock-name"><h1>{companyName||ticker}</h1>{(companyName!==ticker||exchange)&&<span className="num text-[13px] text-t-text3">{ticker}{exchange?` · ${exchange}`:''}</span>}</div><div className="dashboard-price-line">
    {loading&&!close?<div className="t-skeleton h-11 w-36"/>:<span className="dashboard-price num">{typeof close==='number'&&Number.isFinite(close)?close.toFixed(2):'暂无'}</span>}
    {change!=null&&percent!=null&&<span className={`num text-[15px] ${change>=0?'text-t-up':'text-t-down'}`}>{change>=0?'+':''}{change.toFixed(2)} ({percent>=0?'+':''}{percent.toFixed(2)}%)</span>}
    <span className="design-caption inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full" style={{background:'var(--t-amber)'}}/>{close==null?'行情暂时取不到，刷新后重试':status}</span>
  </div></div><div className="dashboard-actions">{onResearch&&<button type="button" onClick={onResearch} className="design-ghost design-primary"><MessageSquare size={14}/>问 AI</button>}{owner&&<button type="button" className="design-ghost" onClick={()=>void toggle()}><Star size={14} fill={inWatchlist?'currentColor':'none'}/>{inWatchlist?'已加入自选':'加入自选'}</button>}{controls}</div></header>;
}
export default StockHeader;
