import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../../api/client';
import { useStore } from '../../store/useStore';
export function LatestResearchCard({ticker,onResearch}:{ticker:string;onResearch:()=>void}){
 const owner=useStore(s=>s.authIdentity?.userId);const select=useStore(s=>s.selectConversation);const navigate=useNavigate();
 const query=useQuery({queryKey:['dashboard-latest-research',owner,ticker],queryFn:({signal})=>apiClient.listReportIndex({ticker,limit:1,includeBlocked:false},signal),enabled:Boolean(owner&&ticker),retry:1});
 const item=query.data?.items[0];
 return <section className="design-card"><div className="dashboard-card-title"><h2>最近一次 AI 分析</h2><span className="design-caption">已保存的研究</span>{item&&<span className="design-caption num">{(item.generated_at||item.created_at||'').slice(0,10)||'日期未注明'}</span>}</div>
 {item?<><p className="text-sm font-medium">{item.title||`${ticker} 研究分析`}</p><p className="mt-2 line-clamp-3 text-[13.5px] leading-7 text-t-text2">{item.summary||'这份分析没有摘要，可打开原对话查看依据。'}</p><p className="design-caption mt-3">分析后股价变化：暂无（这条记录没有保存分析时的价格）</p><button type="button" onClick={()=>{select(item.session_id);navigate(`/chat?report_id=${encodeURIComponent(item.report_id)}`);}} className="mt-3 text-[13px] text-t-accent">查看当时的对话 →</button></>:<div className="design-empty">{query.isPending&&owner?'正在读取保存的分析…':query.isError?'暂时无法读取分析记录。':owner?'还没有这只股票已保存的分析。':'登录后可查看自己的历史分析。'}<button type="button" onClick={onResearch} className="ml-2 text-t-accent">问 AI</button></div>}</section>;
}
