import React, { useState } from 'react';
import { LayoutDashboard, MessageCircle, Star } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { apiClient } from '../../api/client';
import { useDashboardStore } from '../../store/dashboardStore';
import { useStore } from '../../store/useStore';
import { buildScreenerAskAiPrompt, buildScreenerFilterSummary } from '../../utils/screenerLinkage';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { useToast } from '../ui/Toast';

export const ScreenerResultPanel: React.FC = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { watchlist, addWatchItemApi, setActiveAsset } = useDashboardStore();
  const setDraft = useStore((state) => state.setDraft);
  const [market, setMarket] = useState<'US' | 'CN' | 'HK'>('US');
  const [sector, setSector] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capabilityNote, setCapabilityNote] = useState<string | null>(null);
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [addingTicker, setAddingTicker] = useState<string | null>(null);
  const filterSummary = buildScreenerFilterSummary(market, sector);

  const normalizeTicker = (item: Record<string, unknown>) => String(item.symbol || '').trim().toUpperCase();

  const activateTicker = (ticker: string, name?: string) => {
    setActiveAsset({
      symbol: ticker,
      type: 'equity',
      display_name: name?.trim() || ticker,
    });
  };

  const openDashboard = (item: Record<string, unknown>) => {
    const ticker = normalizeTicker(item);
    if (!ticker) return;
    activateTicker(ticker, String(item.name || ''));
    navigate(`/dashboard/${encodeURIComponent(ticker)}`);
  };

  const askAi = (item: Record<string, unknown>) => {
    const ticker = normalizeTicker(item);
    if (!ticker) return;
    const prompt = buildScreenerAskAiPrompt(ticker, filterSummary);
    activateTicker(ticker, String(item.name || ''));
    setDraft(prompt);
    navigate(`/chat?prompt=${encodeURIComponent(prompt)}`);
  };

  const addToWatchlist = async (item: Record<string, unknown>) => {
    const ticker = normalizeTicker(item);
    if (!ticker || addingTicker) return;
    setAddingTicker(ticker);
    try {
      await addWatchItemApi(ticker);
      toast({ type: 'success', title: '已加入自选', message: ticker });
    } catch (caught) {
      toast({
        type: 'error',
        title: '加入自选失败',
        message: caught instanceof Error ? caught.message : '请稍后重试',
      });
    } finally {
      setAddingTicker(null);
    }
  };

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiClient.runScreener({
        market,
        filters: sector.trim() ? { sector: sector.trim() } : {},
        limit: 20,
        page: 1,
        sort_by: 'marketCap',
        sort_order: 'desc',
      });
      if (!result.success) {
        setItems([]);
        setCapabilityNote(result.capability_note || null);
        setError(result.error || '筛选失败');
      } else {
        setItems(Array.isArray(result.items) ? result.items : []);
        setCapabilityNote(result.capability_note || null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '筛选失败');
      setItems([]);
      setCapabilityNote(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="rounded-xl border border-fin-border bg-fin-card p-4">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-xs text-fin-muted">市场</label>
          <select
            className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text"
            value={market}
            onChange={(event) => setMarket(event.target.value as 'US' | 'CN' | 'HK')}
          >
            <option value="US">US</option>
            <option value="CN">CN</option>
            <option value="HK">HK</option>
          </select>
        </div>
        <Input
          label="行业（可选）"
          value={sector}
          onChange={(event) => setSector(event.target.value)}
          placeholder="Technology"
          className="min-w-[220px]"
        />
        <Button variant="primary" onClick={run} disabled={loading}>
          {loading ? '筛选中...' : '运行筛选'}
        </Button>
      </div>

      {error && <p className="mb-3 text-xs text-red-400">{error}</p>}
      {capabilityNote && <p className="mb-3 text-xs text-amber-400">{capabilityNote}</p>}

      <div className="max-h-72 overflow-auto rounded-lg border border-fin-border">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-fin-bg-secondary text-fin-text-secondary">
            <tr>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Price</th>
              <th className="px-3 py-2">Market Cap</th>
              <th className="px-3 py-2 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const ticker = normalizeTicker(item);
              const isWatched = watchlist.some((entry) => entry.symbol.toUpperCase() === ticker);
              return (
                <tr key={String(item.symbol || item.name || Math.random())} className="border-t border-fin-border">
                  <td className="px-3 py-2">{String(item.symbol || '-')}</td>
                  <td className="px-3 py-2">{String(item.name || '-')}</td>
                  <td className="px-3 py-2">{String(item.price ?? '-')}</td>
                  <td className="px-3 py-2">{String(item.market_cap ?? '-')}</td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => openDashboard(item)}
                        disabled={!ticker}
                        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-fin-muted transition-colors hover:bg-fin-primary/10 hover:text-fin-primary disabled:opacity-40"
                        title={`查看 ${ticker || '该标的'} 看板`}
                        aria-label={`查看 ${ticker || '该标的'} 看板`}
                        data-testid={`screener-dashboard-${ticker}`}
                      >
                        <LayoutDashboard size={15} />
                      </button>
                      <button
                        type="button"
                        onClick={() => void addToWatchlist(item)}
                        disabled={!ticker || isWatched || addingTicker !== null}
                        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-fin-muted transition-colors hover:bg-fin-warning/10 hover:text-fin-warning disabled:opacity-40"
                        title={isWatched ? `${ticker} 已在自选` : `将 ${ticker || '该标的'} 加入自选`}
                        aria-label={isWatched ? `${ticker} 已在自选` : `将 ${ticker || '该标的'} 加入自选`}
                        data-testid={`screener-watchlist-${ticker}`}
                      >
                        <Star size={15} fill={isWatched ? 'currentColor' : 'none'} />
                      </button>
                      <button
                        type="button"
                        onClick={() => askAi(item)}
                        disabled={!ticker}
                        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-fin-muted transition-colors hover:bg-fin-primary/10 hover:text-fin-primary disabled:opacity-40"
                        title={`让 AI 分析 ${ticker || '该标的'}`}
                        aria-label={`让 AI 分析 ${ticker || '该标的'}`}
                        data-testid={`screener-ask-ai-${ticker}`}
                      >
                        <MessageCircle size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {items.length === 0 && (
              <tr>
                <td className="px-3 py-6 text-center text-fin-muted" colSpan={5}>
                  暂无结果
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};

export default ScreenerResultPanel;
