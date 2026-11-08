import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { PersonalTrackRecordView } from '../components/right-panel/RightPanelTrackRecordTab';
import { useStore } from '../store/useStore';
import { BenchmarkTrackRecordView } from '../components/track-record/BenchmarkTrackRecord';
import Sidebar from '../components/Sidebar';
export { TrackRecordContent } from '../components/track-record/BenchmarkTrackRecord';
export function TrackRecordPage(){
 const navigate=useNavigate();const [params]=useSearchParams();const owner=useStore(state=>state.authIdentity?.userId);const personal=params.get('scope')==='personal';const ticker=params.get('ticker')||undefined;const [mobileOpen,setMobileOpen]=useState(false);
 return <div className="flex h-dvh min-h-0 bg-t-bg"><Sidebar onChatClick={()=>navigate('/chat')} onHistoryClick={()=>navigate('/history')} onDashboardClick={symbol=>navigate(`/dashboard/${encodeURIComponent(symbol)}`)} onTodayClick={()=>navigate('/today')} onTrackRecordClick={()=>navigate('/track-record')} isMobileOpen={mobileOpen} onMobileOpen={()=>setMobileOpen(true)} onMobileClose={()=>setMobileOpen(false)}/><main id="main-content" className="track-record-page min-w-0 flex-1 max-lg:ml-14"><div className="track-record-shell">{personal?<><header className="track-record-header"><div><h1>{ticker||'我的'}预测记录</h1><p>这里是你的预测记录，和公开战绩分开统计。</p></div><Link className="design-ghost" to="/track-record">查看公开战绩</Link></header>{owner?<PersonalTrackRecordView symbol={ticker}/>:<p className="design-card">登录后查看自己的预测记录。<Link className="ml-2 text-t-accent" to="/welcome?from=%2Ftrack-record">去登录</Link></p>}</>:<BenchmarkTrackRecordView/>}</div></main></div>;
}
