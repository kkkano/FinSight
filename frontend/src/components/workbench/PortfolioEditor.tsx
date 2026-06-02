/**
 * PortfolioEditor.tsx —— 持仓录入 / 管理
 *
 * 解决「持仓永远为空」的玩具感根源：让用户能直接在工作台录入持仓。
 * - 表格：ticker / 股数 / 成本价 / 现价+盈亏 / 操作（编辑 / 删除）
 * - 顶部「添加持仓」→ 行内表单 → 保存调 API
 * - 空状态：引导文案 + 添加按钮
 * - 操作后刷新 summary
 */
import { useCallback, useState } from 'react';
import { Pencil, Plus, Trash2, Wallet } from 'lucide-react';

import { apiClient, type PortfolioSummaryPosition, type PortfolioSummaryResponse } from '../../api/client';
import { useStore } from '../../store/useStore';
import { useToast } from '../ui';
import { formatCurrency } from '../../utils/format';
import { PositionEditRow } from './PositionEditRow';

interface PortfolioEditorProps {
  data: PortfolioSummaryResponse | null;
  loading: boolean;
  /** 持仓变更后刷新 summary */
  onChanged: () => void;
}

/** 盈亏配色 */
function pnlColor(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return 'text-fin-muted';
  return value > 0 ? 'text-fin-success' : 'text-fin-danger';
}

function formatPnl(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${formatCurrency(value)}`;
}

export function PortfolioEditor({ data, loading, onChanged }: PortfolioEditorProps) {
  const sessionId = useStore((s) => s.sessionId);
  const { toast } = useToast();

  const [adding, setAdding] = useState(false);
  const [editingTicker, setEditingTicker] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const positions = data?.positions ?? [];
  const isEmpty = positions.length === 0;

  /** 保存（新增 / 编辑共用）：调 PUT 单条更新 */
  const handleSave = useCallback(
    async (ticker: string, shares: number, avgCost: number | null) => {
      const normalized = ticker.trim().toUpperCase();
      if (!normalized || !Number.isFinite(shares) || shares <= 0) {
        toast({ type: 'warning', title: '请输入有效的股票代码和股数' });
        return;
      }
      setSaving(true);
      try {
        await apiClient.updatePortfolioPosition(sessionId, normalized, shares, avgCost);
        setAdding(false);
        setEditingTicker(null);
        onChanged();
      } catch (err) {
        const message = err instanceof Error ? err.message : '保存失败，请稍后重试';
        toast({ type: 'error', title: '保存持仓失败', message });
      } finally {
        setSaving(false);
      }
    },
    [sessionId, toast, onChanged],
  );

  /** 删除单条持仓 */
  const handleDelete = useCallback(
    async (ticker: string) => {
      setSaving(true);
      try {
        await apiClient.deletePortfolioPosition(sessionId, ticker);
        if (editingTicker === ticker) setEditingTicker(null);
        onChanged();
      } catch (err) {
        const message = err instanceof Error ? err.message : '删除失败，请稍后重试';
        toast({ type: 'error', title: '删除持仓失败', message });
      } finally {
        setSaving(false);
      }
    },
    [sessionId, toast, onChanged, editingTicker],
  );

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-fin-border">
        <div className="flex items-center gap-2">
          <Wallet size={14} className="text-fin-primary" />
          <span className="text-xs font-semibold text-fin-text">持仓管理</span>
        </div>
        <button
          type="button"
          onClick={() => {
            setAdding(true);
            setEditingTicker(null);
          }}
          disabled={adding || saving}
          data-testid="portfolio-add-button"
          className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Plus size={13} />
          添加持仓
        </button>
      </div>

      {/* 新增行内表单 */}
      {adding && (
        <div className="px-3 py-2.5 border-b border-fin-border bg-fin-bg/40">
          <PositionEditRow
            mode="create"
            saving={saving}
            onSave={handleSave}
            onCancel={() => setAdding(false)}
          />
        </div>
      )}

      {/* 列表 / 空状态 */}
      {loading && positions.length === 0 ? (
        <div className="py-8 text-center text-xs text-fin-muted" data-testid="portfolio-loading">
          正在加载持仓...
        </div>
      ) : isEmpty && !adding ? (
        <div
          className="flex flex-col items-center justify-center py-10 gap-3 text-center px-4"
          data-testid="portfolio-empty"
        >
          <Wallet size={28} className="text-fin-muted/40" />
          <div className="text-xs text-fin-muted max-w-[220px] leading-relaxed">
            录入持仓后，AI 会自动帮你盯盘——价格异动、集中度风险都会在「今日发现」里提醒你。
          </div>
          <button
            type="button"
            onClick={() => setAdding(true)}
            data-testid="portfolio-empty-add"
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 transition-colors"
          >
            <Plus size={13} />
            添加第一笔持仓
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto scrollbar-hide">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-fin-border/60 text-2xs text-fin-muted">
                <th className="px-3 py-2 text-left font-medium">代码</th>
                <th className="px-3 py-2 text-right font-medium">股数</th>
                <th className="px-3 py-2 text-right font-medium">成本价</th>
                <th className="px-3 py-2 text-right font-medium">现价 / 盈亏</th>
                <th className="px-3 py-2 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos: PortfolioSummaryPosition) =>
                editingTicker === pos.ticker ? (
                  <tr key={pos.ticker} className="border-b border-fin-border/30 bg-fin-bg/40">
                    <td colSpan={5} className="px-3 py-2.5">
                      <PositionEditRow
                        mode="edit"
                        saving={saving}
                        initialTicker={pos.ticker}
                        initialShares={pos.shares}
                        initialAvgCost={pos.avg_cost ?? null}
                        onSave={handleSave}
                        onCancel={() => setEditingTicker(null)}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr
                    key={pos.ticker}
                    className="group border-b border-fin-border/30 hover:bg-fin-hover/40 transition-colors"
                    data-testid={`portfolio-row-${pos.ticker}`}
                  >
                    <td className="px-3 py-2 font-medium text-fin-text whitespace-nowrap">{pos.ticker}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-fin-text">{pos.shares}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-fin-text-secondary">
                      {pos.avg_cost != null ? `$${pos.avg_cost.toFixed(2)}` : '--'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      <div className="text-fin-text">
                        {pos.live_price != null ? `$${pos.live_price.toFixed(2)}` : '--'}
                      </div>
                      <div className={`text-2xs ${pnlColor(pos.unrealized_pnl)}`}>
                        {formatPnl(pos.unrealized_pnl)}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          type="button"
                          onClick={() => {
                            setEditingTicker(pos.ticker);
                            setAdding(false);
                          }}
                          aria-label={`编辑 ${pos.ticker}`}
                          title="编辑"
                          className="p-1 rounded text-fin-muted hover:text-fin-primary transition-colors"
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDelete(pos.ticker)}
                          aria-label={`删除 ${pos.ticker}`}
                          title="删除"
                          className="p-1 rounded text-fin-muted hover:text-fin-danger transition-colors"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default PortfolioEditor;
