import React, { useState } from 'react';
import { apiClient } from '../../api/client';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';

export const ScreenerResultPanel: React.FC = () => {
  const [market, setMarket] = useState<'US' | 'CN' | 'HK'>('US');
  const [sector, setSector] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capabilityNote, setCapabilityNote] = useState<string | null>(null);
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);

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
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={String(item.symbol || item.name || Math.random())} className="border-t border-fin-border">
                <td className="px-3 py-2">{String(item.symbol || '-')}</td>
                <td className="px-3 py-2">{String(item.name || '-')}</td>
                <td className="px-3 py-2">{String(item.price ?? '-')}</td>
                <td className="px-3 py-2">{String(item.market_cap ?? '-')}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td className="px-3 py-6 text-center text-fin-muted" colSpan={4}>
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
