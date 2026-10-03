import { ArrowLeft, Target } from 'lucide-react';
import { Link } from 'react-router-dom';
import { BenchmarkTrackRecordView } from '../components/track-record/BenchmarkTrackRecord';

export { TrackRecordContent } from '../components/track-record/BenchmarkTrackRecord';

export function TrackRecordPage() {
  return <main id="main-content" className="h-screen overflow-y-auto bg-t-bg px-4 py-6 md:px-8">
    <div className="mx-auto max-w-3xl">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-t-divider pb-6">
        <div>
          <p className="flex items-center gap-2 text-xs font-medium text-t-accent"><Target size={16} />FinSight · 公开只读账本</p>
          <h1 className="mt-3 text-2xl font-semibold text-t-text">US20 预测战绩</h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-t-text2">固定美股样本的 5 日前瞻预测，分别评价方向与回撤事件，保留每次机会及实际结果。</p>
        </div>
        <Link to="/welcome" className="inline-flex min-h-10 items-center gap-2 rounded-md border border-t-border px-3 text-sm text-t-text2 hover:bg-t-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent"><ArrowLeft size={15} />返回 FinSight</Link>
      </header>
      <BenchmarkTrackRecordView />
    </div>
  </main>;
}
