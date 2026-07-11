import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { apiClient } from '../api/client';
import { ReportView } from '../components/report/ReportView';
import type { ReportIR } from '../types';

export function SharedReportPage() {
  const { token = '' } = useParams();
  const [report, setReport] = useState<ReportIR | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setReport(null);
    setError(null);
    apiClient.getSharedReport(token)
      .then((response) => {
        if (active) setReport(response.report);
      })
      .catch(() => {
        if (active) setError('分享链接不存在或已撤销');
      });
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <main id="main-content" className="min-h-screen bg-fin-bg px-4 py-8 md:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="mb-5 border-b border-fin-border pb-4">
          <div className="font-mono text-xs uppercase tracking-[0.2em] text-fin-primary">FinSight Shared Research</div>
          <h1 className="mt-2 text-xl font-semibold text-fin-text">只读研究报告</h1>
          <p className="mt-1 text-sm text-fin-muted">此页面仅展示分享时的报告内容，不包含内部执行诊断。</p>
        </header>

        {!report && !error && (
          <div className="rounded-lg border border-fin-border bg-fin-card p-8 text-center text-fin-muted">
            正在加载报告…
          </div>
        )}
        {error && (
          <div role="alert" className="rounded-lg border border-fin-danger/40 bg-fin-danger/10 p-8 text-center text-fin-danger">
            {error}
          </div>
        )}
        {report && <ReportView report={report} readOnly />}
      </div>
    </main>
  );
}
