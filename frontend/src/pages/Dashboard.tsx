import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, RefreshCw, Sun, Moon } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { DashboardContext, useDashboardData } from '../hooks/useDashboardData';
import { useWatchlist } from '../hooks/useWatchlist';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { StockHeader } from '../components/dashboard/StockHeader';
import { DashboardPriceChart } from '../components/dashboard/DashboardPriceChart';
import { MetricsBar } from '../components/dashboard/MetricsBar';
import { DashboardWatchlistCard } from '../components/dashboard/DashboardWatchlistCard';
import { LatestResearchCard } from '../components/dashboard/LatestResearchCard';
import { MonitorActivityFeed } from '../components/dashboard/MonitorActivityFeed';
import { OverviewTab } from '../components/dashboard/tabs/OverviewTab';
import { FinancialTab } from '../components/dashboard/tabs/FinancialTab';
import { TechnicalTab } from '../components/dashboard/tabs/TechnicalTab';
import { NewsTab } from '../components/dashboard/tabs/NewsTab';
import { getPredictionIdFromSearch } from '../components/chatChartIntent';
import { buildDashboardAskAiDraft } from '../utils/dashboardAskAi';
import { usePredictionOverlay } from '../hooks/usePredictionOverlay';
import { useChatHandoff } from '../hooks/useChatHandoff';
import { dashboardResearchContext } from '../utils/dashboardResearchContext';
import type { DashboardResearchContext } from '../types/chatHandoff';
import { researchFailureMessage } from '../utils/researchFailure';
import { zh } from '../locales/zh';
interface DashboardProps {initialSymbol?:string;onBackToChat?:()=>void;onSymbolChange?:(symbol:string)=>void}
export function Dashboard({initialSymbol,onBackToChat,onSymbolChange}:DashboardProps){
 const {activeAsset,setActiveAsset}=useDashboardStore();const {watchlist}=useWatchlist();const {theme,setTheme,authIdentity,sessionId}=useStore();
 const [searchParams,setSearchParams]=useSearchParams();const [selectedSymbol,setSelectedSymbol]=useState(()=>initialSymbol||activeAsset?.symbol||watchlist[0]?.symbol||'');const [symbolDraft,setSymbolDraft]=useState('');
 const currentSymbol=(initialSymbol||selectedSymbol).trim().toUpperCase();const handoff=useChatHandoff();const client=useQueryClient();
 const {refetch,dashboardData,asset:loadedAsset,isLoading,error}=useDashboardData(currentSymbol);
 const pageAsset=useMemo(()=>({symbol:currentSymbol,display_name:loadedAsset?.display_name||currentSymbol,type:loadedAsset?.type||'equity' as const}),[currentSymbol,loadedAsset]);
 const prediction=usePredictionOverlay(currentSymbol,getPredictionIdFromSearch(searchParams.toString()),Boolean(authIdentity?.userId),0);
 const activeTab=['financial','news','technical'].includes(searchParams.get('tab')||'')?searchParams.get('tab')!:'overview';
 useEffect(()=>{if(currentSymbol)setActiveAsset(pageAsset);},[currentSymbol,pageAsset,setActiveAsset]);
 const select=(symbol:string)=>{const value=symbol.trim().toUpperCase();if(!value)return;setSelectedSymbol(value);setActiveAsset({symbol:value,display_name:value,type:'equity'});onSymbolChange?.(value);};
 const askSelection=(selected:DashboardResearchContext)=>{if(currentSymbol)handoff({draft:buildDashboardAskAiDraft(currentSymbol,activeTab),activeSymbol:currentSymbol,sourceView:'dashboard',sourceTab:activeTab,...selected});};
 const ask=()=>askSelection(dashboardResearchContext(dashboardData?.meta?.[activeTab==='financial'?'financials':activeTab==='overview'?'market_chart':activeTab==='technical'?'technicals':'news_market']));
 const refresh=()=>{void refetch(currentSymbol);void client.invalidateQueries({queryKey:['dashboard-kline',currentSymbol]});void client.invalidateQueries({queryKey:['dashboard-quote',currentSymbol]});};
 if(!currentSymbol)return <main className="dashboard-page items-center justify-center"><section className="design-card w-full max-w-md"><h1 className="text-lg font-semibold">选择一只股票，查看真实数据</h1><p className="design-caption mt-2">输入股票代码，或从自选列表选择。</p><form className="mt-4 flex gap-2" onSubmit={event=>{event.preventDefault();select(symbolDraft);}}><input aria-label="股票代码" className="min-w-0 flex-1 rounded-lg border border-t-border bg-t-bg px-3 py-2" value={symbolDraft} onChange={event=>setSymbolDraft(event.target.value)} placeholder="股票代码，如 AAPL"/><button type="submit" className="design-ghost">查看</button></form></section></main>;
 return <DashboardContext.Provider value={{asset:pageAsset,data:dashboardData}}><main className="dashboard-page" id="main-content">

   {error&&<p role="alert" className="rounded-lg bg-t-down/10 px-3 py-2 text-sm text-t-down">{researchFailureMessage(error,zh.dashboard.failed)}<button type="button" className="ml-2 underline" onClick={refresh}>重试</button></p>}
   <StockHeader ticker={currentSymbol} displayName={pageAsset.display_name} assetType={pageAsset.type} snapshot={dashboardData?.snapshot||{}} charts={dashboardData?.charts||{}} valuation={dashboardData?.valuation} loading={isLoading&&!dashboardData} onResearch={ask} controls={<>{onBackToChat&&<button type="button" data-testid="dashboard-back-chat" onClick={onBackToChat} aria-label="返回对话" title="返回对话" className="design-ghost !px-2 max-sm:hidden"><ArrowLeft size={14}/></button>}<button type="button" aria-label="刷新数据" title="刷新数据" className="design-ghost !px-2" disabled={isLoading} onClick={refresh}><RefreshCw size={15} className={isLoading?'animate-spin':''}/></button><button type="button" aria-label="切换主题" title="切换主题" className="design-ghost !px-2" onClick={()=>setTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?<Sun size={15}/>:<Moon size={15}/>}</button></>}/>
   <nav className="dashboard-tabs" aria-label="看板内容">{[{key:'overview',label:'概览'},{key:'financial',label:'财务'},{key:'news',label:'新闻'},{key:'technical',label:'技术面'}].map(tab=><button type="button" key={tab.key} className={`dashboard-tab ${tab.key===activeTab?'on':''}`} data-testid={`dashboard-tab-${tab.key}`} aria-current={tab.key===activeTab?'page':undefined} onClick={()=>setSearchParams(previous=>{const next=new URLSearchParams(previous);if(tab.key==='overview')next.delete('tab');else next.set('tab',tab.key);return next;},{replace:true})}>{tab.label}</button>)}</nav>
   <div className="dashboard-columns"><div className="dashboard-main">{activeTab==='overview'?<><DashboardPriceChart onResearch={askSelection}/><MetricsBar valuation={dashboardData?.valuation} snapshot={dashboardData?.snapshot} ticker={currentSymbol} loading={isLoading&&!dashboardData} onSelectMetric={askSelection}/><LatestResearchCard ticker={currentSymbol} onResearch={ask}/><OverviewTab/></>:activeTab==='financial'?<FinancialTab/>:activeTab==='news'?<NewsTab/>:<TechnicalTab predictionOverlay={prediction.overlay}/>}</div><aside className="dashboard-side" aria-label="自选与盯盘"><DashboardWatchlistCard activeSymbol={currentSymbol} onSelect={select}/><MonitorActivityFeed sessionId={sessionId} symbol={currentSymbol} compact/></aside></div>
   <footer className="design-caption border-t border-t-divider pt-3">行情、财务和新闻的来源及时间见各项标注。内容为信息整理，不构成投资建议。</footer>
 </main></DashboardContext.Provider>;
}
export default Dashboard;
