import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useDashboardAsset } from '../../hooks/useDashboardData';
import { useStore } from '../../store/useStore';
import { apiClient } from '../../api/client';
import { sourceDisplayName } from '../../utils/sourceDisplayName';
import EChart from '../charts/EChart';
import { chartTokens } from './visualTokens';
const periods=[{value:'1mo',label:'1月'},{value:'3mo',label:'3月'},{value:'6mo',label:'6月'},{value:'1y',label:'1年'}];
export function DashboardPriceChart(){
 const asset=useDashboardAsset();const dark=useStore(s=>s.theme==='dark');const [period,setPeriod]=useState('3mo');
 const query=useQuery({queryKey:['dashboard-kline',asset?.symbol,period],queryFn:({signal})=>apiClient.fetchKline(asset!.symbol,period,'1d',signal),enabled:Boolean(asset?.symbol),staleTime:60_000,retry:1});
 const envelope=query.data?.data;const rows=(envelope?.kline_data||envelope?.data||[]).filter(point=>Number.isFinite(point.close));
 const option=useMemo(()=>{const color=chartTokens();return {animation:false,grid:{left:10,right:55,top:15,bottom:24},tooltip:{trigger:'axis'},xAxis:{type:'category',boundaryGap:false,data:rows.map(row=>row.time.slice(0,10)),axisLine:{lineStyle:{color:color.border}},axisTick:{show:false},axisLabel:{color:color.text,fontFamily:'JetBrains Mono Variable',fontSize:10}},yAxis:{type:'value',scale:true,position:'right',axisLabel:{color:color.text,fontFamily:'JetBrains Mono Variable',fontSize:10},splitLine:{lineStyle:{color:color.line}}},series:[{type:'line',name:'收盘价',data:rows.map(row=>row.close),showSymbol:false,lineStyle:{color:color.accent,width:2},areaStyle:{color:color.accentSoft}}]};},[rows,dark]);
 return <section className="design-card" aria-label="股价走势"><div className="dashboard-card-title"><h2>股价走势</h2><div className="flex gap-0.5" role="group" aria-label="股价走势时间范围">{periods.map(item=><button type="button" key={item.value} className={`design-segment !h-7 !px-2.5 ${period===item.value?'on':''}`} onClick={()=>setPeriod(item.value)}>{item.label}</button>)}</div></div>
 {query.isPending?<div className="t-skeleton h-[244px]"/>:query.isError||!rows.length?<div className="design-empty">行情暂时取不到，不能绘制真实走势。<button type="button" onClick={()=>void query.refetch()} className="ml-2 text-t-accent">重试</button></div>:<EChart option={option} style={{height:244}}/>}
 <p className="design-caption mt-1">{sourceDisplayName(envelope?.provider)} · {rows.length?`${rows[0].time.slice(0,10)} 至 ${rows.at(-1)!.time.slice(0,10)} · 日收盘价，非实时`:'暂无可用行情区间'}</p></section>;
}
