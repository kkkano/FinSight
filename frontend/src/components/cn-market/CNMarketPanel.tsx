import React, { useState, useCallback } from 'react';
import { RefreshCw, TrendingUp, Globe, BarChart3, Layers, ArrowUpDown } from 'lucide-react';
import { apiClient } from '../../api/client';

type TabKey = 'fund_flow' | 'northbound' | 'limit_board' | 'lhb' | 'concept';
type RowData = Record<string, unknown>;

interface TabConfig {
  key: TabKey;
  label: string;
  icon: React.ReactNode;
}

const TABS: TabConfig[] = [
  { key: 'fund_flow',   label: '资金流向', icon: <TrendingUp size={13} /> },
  { key: 'northbound',  label: '北向资金', icon: <Globe size={13} /> },
  { key: 'limit_board', label: '涨跌停',   icon: <ArrowUpDown size={13} /> },
  { key: 'lhb',         label: '龙虎榜',   icon: <BarChart3 size={13} /> },
  { key: 'concept',     label: '概念板块', icon: <Layers size={13} /> },
];

// --- Formatters ---

function fmtFlow(val: unknown): string {
  const n = Number(val);
  if (!Number.isFinite(n)) return '-';
  const abs = Math.abs(n);
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
  return n.toFixed(2);
}

function fmtPct(val: unknown): string {
  const n = Number(val);
  if (!Number.isFinite(n)) return '-';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function pctColor(val: unknown): string {
  const n = Number(val);
  if (!Number.isFinite(n)) return 'text-fin-muted';
  return n > 0 ? 'text-fin-success' : n < 0 ? 'text-fin-danger' : 'text-fin-muted';
}

function flowColor(val: unknown): string {
  const n = Number(val);
  if (!Number.isFinite(n)) return 'text-fin-muted';
  return n > 0 ? 'text-fin-success' : n < 0 ? 'text-fin-danger' : 'text-fin-muted';
}

// --- Sub-tables ---

function FundFlowTable({ rows }: { rows: RowData[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-fin-muted border-b border-fin-border">
          <th className="pb-1.5 text-left font-medium">代码</th>
          <th className="pb-1.5 text-left font-medium">名称</th>
          <th className="pb-1.5 text-right font-medium">涨跌幅</th>
          <th className="pb-1.5 text-right font-medium">主力净流入</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-fin-border/30">
        {rows.map((row, i) => (
          <tr key={String(row.symbol ?? i)} className="hover:bg-fin-hover/30 transition-colors">
            <td className="py-1.5 font-mono text-fin-muted">{String(row.symbol ?? '-')}</td>
            <td className="py-1.5 text-fin-text max-w-[80px] truncate">{String(row.name ?? '-')}</td>
            <td className={`py-1.5 text-right ${pctColor(row.change_percent)}`}>{fmtPct(row.change_percent)}</td>
            <td className={`py-1.5 text-right ${flowColor(row.main_net_inflow)}`}>{fmtFlow(row.main_net_inflow)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LimitBoardTable({ rows }: { rows: RowData[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-fin-muted border-b border-fin-border">
          <th className="pb-1.5 text-left font-medium">代码</th>
          <th className="pb-1.5 text-left font-medium">名称</th>
          <th className="pb-1.5 text-right font-medium">涨跌幅</th>
          <th className="pb-1.5 text-right font-medium">换手率</th>
          <th className="pb-1.5 text-right font-medium">量比</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-fin-border/30">
        {rows.map((row, i) => (
          <tr key={String(row.symbol ?? i)} className="hover:bg-fin-hover/30 transition-colors">
            <td className="py-1.5 font-mono text-fin-muted">{String(row.symbol ?? '-')}</td>
            <td className="py-1.5 text-fin-text max-w-[80px] truncate">{String(row.name ?? '-')}</td>
            <td className={`py-1.5 text-right ${pctColor(row.change_percent)}`}>{fmtPct(row.change_percent)}</td>
            <td className="py-1.5 text-right text-fin-text">{String(row.turnover_rate ?? '-')}</td>
            <td className="py-1.5 text-right text-fin-text">{String(row.volume_ratio ?? '-')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LhbTable({ rows }: { rows: RowData[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-fin-muted border-b border-fin-border">
          <th className="pb-1.5 text-left font-medium">代码</th>
          <th className="pb-1.5 text-left font-medium">名称</th>
          <th className="pb-1.5 text-right font-medium">涨跌幅</th>
          <th className="pb-1.5 text-right font-medium">净买入</th>
          <th className="pb-1.5 text-left font-medium pl-2">上榜原因</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-fin-border/30">
        {rows.map((row, i) => (
          <tr key={String(row.symbol ?? i)} className="hover:bg-fin-hover/30 transition-colors">
            <td className="py-1.5 font-mono text-fin-muted">{String(row.symbol ?? '-')}</td>
            <td className="py-1.5 text-fin-text max-w-[70px] truncate">{String(row.name ?? '-')}</td>
            <td className={`py-1.5 text-right ${pctColor(row.change_percent)}`}>{fmtPct(row.change_percent)}</td>
            <td className={`py-1.5 text-right ${flowColor(row.net_buy)}`}>{fmtFlow(row.net_buy)}</td>
            <td className="py-1.5 pl-2 text-fin-muted max-w-[100px] truncate" title={String(row.reason ?? '')}>
              {String(row.reason ?? '-')}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConceptTable({ rows }: { rows: RowData[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-fin-muted border-b border-fin-border">
          <th className="pb-1.5 text-left font-medium">板块名称</th>
          <th className="pb-1.5 text-right font-medium">涨跌幅</th>
          <th className="pb-1.5 text-right font-medium">主力净流入</th>
          <th className="pb-1.5 text-right font-medium">涨/跌家数</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-fin-border/30">
        {rows.map((row, i) => (
          <tr key={String(row.concept_code ?? i)} className="hover:bg-fin-hover/30 transition-colors">
            <td className="py-1.5 text-fin-text max-w-[110px] truncate">{String(row.concept_name ?? '-')}</td>
            <td className={`py-1.5 text-right ${pctColor(row.change_percent)}`}>{fmtPct(row.change_percent)}</td>
            <td className={`py-1.5 text-right ${flowColor(row.main_net_inflow)}`}>{fmtFlow(row.main_net_inflow)}</td>
            <td className="py-1.5 text-right">
              <span className="text-fin-success">{String(row.up_count ?? '-')}</span>
              <span className="text-fin-muted mx-0.5">/</span>
              <span className="text-fin-danger">{String(row.down_count ?? '-')}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// --- Main Panel ---

const makeTabState = <T,>(init: T): Record<TabKey, T> => ({
  fund_flow: init, northbound: init, limit_board: init, lhb: init, concept: init,
});

export const CNMarketPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('fund_flow');
  const [tabData, setTabData]     = useState<Record<TabKey, RowData[]>>(makeTabState([]));
  const [loading, setLoading]     = useState<Record<TabKey, boolean>>(makeTabState(false));
  const [errors, setErrors]       = useState<Record<TabKey, string | null>>(makeTabState(null));

  const loadTab = useCallback(async (tab: TabKey) => {
    setLoading(prev => ({ ...prev, [tab]: true }));
    setErrors(prev => ({ ...prev, [tab]: null }));
    try {
      let result;
      switch (tab) {
        case 'fund_flow':   result = await apiClient.getCNFundFlow(20);          break;
        case 'northbound':  result = await apiClient.getCNNorthbound(20);        break;
        case 'limit_board': result = await apiClient.getCNLimitBoard(20);        break;
        case 'lhb':         result = await apiClient.getCNLhb(20);               break;
        case 'concept':     result = await apiClient.getCNConcept({ limit: 20 }); break;
        default:            result = { items: [] };
      }
      setTabData(prev => ({ ...prev, [tab]: Array.isArray(result.items) ? result.items : [] }));
    } catch (e) {
      setErrors(prev => ({ ...prev, [tab]: e instanceof Error ? e.message : '加载失败' }));
    } finally {
      setLoading(prev => ({ ...prev, [tab]: false }));
    }
  }, []);

  const handleTabClick = (tab: TabKey) => {
    setActiveTab(tab);
    if (tabData[tab].length === 0 && !loading[tab] && !errors[tab]) {
      loadTab(tab);
    }
  };

  const rows      = tabData[activeTab];
  const isLoading = loading[activeTab];
  const error     = errors[activeTab];

  return (
    <section className="rounded-xl border border-fin-border bg-fin-card p-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-fin-text">A股市场</h3>
        <button
          type="button"
          onClick={() => loadTab(activeTab)}
          disabled={isLoading}
          className="p-1.5 rounded-lg text-fin-muted hover:text-fin-text hover:bg-fin-hover transition-colors disabled:opacity-40"
          title="刷新"
        >
          <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-3 border-b border-fin-border pb-2 overflow-x-auto">
        {TABS.map(({ key, label, icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => handleTabClick(key)}
            className={[
              'flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap transition-colors',
              activeTab === key
                ? 'bg-fin-primary/15 text-fin-primary'
                : 'text-fin-muted hover:text-fin-text hover:bg-fin-hover',
            ].join(' ')}
          >
            {icon}
            {label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && <p className="mb-2 text-xs text-fin-danger">{error}</p>}

      {/* Loading skeleton */}
      {isLoading && rows.length === 0 && (
        <div className="space-y-1.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-7 rounded bg-fin-border/30 animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty prompt */}
      {!isLoading && !error && rows.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8 text-fin-muted gap-2">
          <p className="text-xs">暂无数据，点击立即加载</p>
          <button
            type="button"
            onClick={() => loadTab(activeTab)}
            className="text-xs text-fin-primary hover:underline"
          >
            立即加载
          </button>
        </div>
      )}

      {/* Table */}
      {rows.length > 0 && (
        <div className="overflow-x-auto max-h-72 overflow-y-auto">
          {(activeTab === 'fund_flow' || activeTab === 'northbound') && <FundFlowTable rows={rows} />}
          {activeTab === 'limit_board' && <LimitBoardTable rows={rows} />}
          {activeTab === 'lhb' && <LhbTable rows={rows} />}
          {activeTab === 'concept' && <ConceptTable rows={rows} />}
        </div>
      )}
    </section>
  );
};

export default CNMarketPanel;
