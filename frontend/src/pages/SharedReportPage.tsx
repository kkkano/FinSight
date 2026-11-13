import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { apiClient } from '../api/client';
import { ReportView } from '../components/report/ReportView';
import type { ReportIR } from '../types';
import { zh } from '../locales/zh';

export function SharedReportHeader({ report, publishedAt }: { report: ReportIR | null; publishedAt?: string | null }) {
  const date = publishedAt ? new Date(publishedAt) : null;
  const sourceCount = new Set((report?.citations ?? []).map((source) => source.source_id || source.url)).size;
  return <header className="mb-5 border-b border-fin-border pb-4">
    <div className="text-xs text-fin-primary">FinSight · <span>{zh.share.readOnly}</span></div>
    <h1 className="mt-2 text-xl font-semibold text-fin-text">{report?.title || '只读研究报告'}</h1>
    {report && <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-fin-muted">
      <span>{date && Number.isFinite(date.getTime()) ? zh.share.published(date.toLocaleString('zh-CN', { hour12: false })) : zh.share.publishedUnknown}</span>
      <span>{zh.share.sources(sourceCount)}</span>
    </p>}
    <p className="mt-1 text-sm text-fin-muted">{zh.share.description}</p>
  </header>;
}

export function SharedReportPage() {
  const { token = '' } = useParams();
  const [report, setReport] = useState<ReportIR | null>(null);
  const [publishedAt, setPublishedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setReport(null);
    setPublishedAt(null);
    setError(null);
    apiClient.getSharedReport(token)
      .then((response) => {
        if (active) { setReport(response.report); setPublishedAt(response.published_at ?? null); }
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
        <SharedReportHeader report={report} publishedAt={publishedAt} />

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
