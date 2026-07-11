import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { apiClient } from '../api/client';
import type { BacktestPrefillConfig } from '../api/contracts';
import { BacktestPanel } from '../components/backtest/BacktestPanel';

export const BacktestPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const reportId = searchParams.get('prefill')?.trim() || '';
  const [prefill, setPrefill] = useState<BacktestPrefillConfig | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [prefillError, setPrefillError] = useState<string | null>(null);
  const [prefillLoading, setPrefillLoading] = useState(false);

  useEffect(() => {
    let active = true;
    if (!reportId) {
      setPrefill(null);
      setWarnings([]);
      setPrefillError(null);
      return () => { active = false; };
    }

    setPrefillLoading(true);
    setPrefill(null);
    setWarnings([]);
    setPrefillError(null);
    void apiClient.prefillBacktestFromReport(reportId)
      .then((payload) => {
        if (!active) return;
        setPrefill(payload.config);
        setWarnings(payload.warnings || []);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setPrefill(null);
        setWarnings([]);
        setPrefillError(error instanceof Error ? error.message : '报告预填失败');
      })
      .finally(() => {
        if (active) setPrefillLoading(false);
      });

    return () => { active = false; };
  }, [reportId]);

  return (
    <main id="main-content" className="min-h-screen bg-fin-bg px-4 py-6 md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-fin-text">策略回测</h1>
            <p className="text-sm text-fin-muted">用历史行情验证策略表现与风险</p>
          </div>
          <Link
            to="/workbench"
            className="rounded-md border border-fin-border px-3 py-2 text-sm text-fin-text hover:bg-fin-bg-secondary"
          >
            返回工作台
          </Link>
        </header>

        {prefillLoading && <p className="text-sm text-fin-muted">正在读取报告并生成回测配置...</p>}
        {prefillError && <p className="rounded-lg border border-fin-danger/30 bg-fin-danger/5 px-3 py-2 text-sm text-fin-danger">{prefillError}</p>}
        {warnings.map((warning) => (
          <p key={warning} className="rounded-lg border border-fin-warning/30 bg-fin-warning/5 px-3 py-2 text-sm text-fin-warning">
            {warning}
          </p>
        ))}
        <BacktestPanel initialConfig={prefill} />
      </div>
    </main>
  );
};

export default BacktestPage;
