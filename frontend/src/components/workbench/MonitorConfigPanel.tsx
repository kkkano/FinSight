/**
 * MonitorConfigPanel.tsx —— 监控配置（侧栏）
 *
 * - 盯盘对象列表：ticker + 类型 + 阈值 + 开关（switch 切换 enabled）
 * - 「添加监控」：输入 ticker + 价格异动阈值（默认 5%）→ POST
 * - 持仓自动监控说明文案
 */
import { useState, type KeyboardEvent } from 'react';
import { Pencil, Plus, Radio, Trash2, X } from 'lucide-react';

import { useMonitorTargets } from '../../hooks/useMonitorTargets';
import { useToast } from '../ui';
import type { MonitorTarget, MonitorTargetType } from '../../types/monitor';
import { ThresholdEditForm } from './ThresholdEditForm';
import { NotificationSettings } from './NotificationSettings';

interface MonitorConfigPanelProps {
  sessionId: string | null | undefined;
}

/** 默认价格异动阈值（%） */
const DEFAULT_PRICE_MOVE_PCT = 5;

/** 类型中文名 */
const TYPE_LABEL: Record<MonitorTargetType, string> = {
  holding: '持仓',
  watchlist: '自选',
  custom: '自定义',
};

/** 提取主阈值文案 */
function describeThreshold(config: Record<string, number>): string {
  if (config.price_move_pct != null) return `价格异动 ±${config.price_move_pct}%`;
  if (config.concentration_pct != null) return `集中度 >${config.concentration_pct}%`;
  const firstKey = Object.keys(config)[0];
  return firstKey ? `${firstKey}=${config[firstKey]}` : '默认阈值';
}

export function MonitorConfigPanel({ sessionId }: MonitorConfigPanelProps) {
  const { targets, loading, error, createTarget, patchTarget, deleteTarget } =
    useMonitorTargets(sessionId);
  const { toast } = useToast();

  const [adding, setAdding] = useState(false);
  const [ticker, setTicker] = useState('');
  const [threshold, setThreshold] = useState(String(DEFAULT_PRICE_MOVE_PCT));
  const [submitting, setSubmitting] = useState(false);
  /** 当前展开内联编辑阈值的 target id */
  const [editingTargetId, setEditingTargetId] = useState<string | null>(null);
  const [savingThreshold, setSavingThreshold] = useState(false);

  /** 保存阈值：合并入现有 config 后 PATCH，成功收起表单，失败 toast */
  const handleSaveThreshold = async (
    target: MonitorTarget,
    config: Record<string, number>,
  ) => {
    setSavingThreshold(true);
    const ok = await patchTarget(target.id, { config: { ...target.config, ...config } });
    setSavingThreshold(false);
    if (ok) {
      setEditingTargetId(null);
      toast({ type: 'success', title: '监控阈值已更新' });
    } else {
      toast({ type: 'error', title: '更新阈值失败', message: '请检查数值是否在允许范围内' });
    }
  };

  const resetForm = () => {
    setTicker('');
    setThreshold(String(DEFAULT_PRICE_MOVE_PCT));
    setAdding(false);
  };

  const handleCreate = async () => {
    const normalized = ticker.trim().toUpperCase();
    const pct = Number(threshold);
    if (!normalized || !Number.isFinite(pct) || pct <= 0) return;
    setSubmitting(true);
    const ok = await createTarget({
      type: 'custom',
      ticker: normalized,
      config: { price_move_pct: pct },
      enabled: true,
    });
    setSubmitting(false);
    if (ok) resetForm();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void handleCreate();
    } else if (e.key === 'Escape') {
      resetForm();
    }
  };

  const inputClass =
    'min-w-0 px-2 py-1 text-xs rounded-lg border border-fin-border bg-fin-bg text-fin-text placeholder:text-fin-muted focus:outline-none focus:border-fin-primary focus:ring-1 focus:ring-fin-primary/30';

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-fin-border">
        <div className="flex items-center gap-2">
          <Radio size={14} className="text-fin-primary" />
          <span className="text-xs font-semibold text-fin-text">监控配置</span>
        </div>
        <button
          type="button"
          onClick={() => setAdding(true)}
          disabled={adding}
          data-testid="monitor-add-button"
          className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Plus size={13} />
          添加监控
        </button>
      </div>

      {/* 添加表单 */}
      {adding && (
        <div className="px-3 py-2.5 border-b border-fin-border bg-fin-bg/40 space-y-2">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={handleKeyDown}
              placeholder="代码"
              aria-label="监控股票代码"
              className={`w-20 ${inputClass}`}
              autoFocus
            />
            <div className="flex items-center gap-1 flex-1">
              <span className="text-2xs text-fin-muted whitespace-nowrap">异动阈值 ±</span>
              <input
                type="number"
                inputMode="decimal"
                min="0"
                step="any"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                onKeyDown={handleKeyDown}
                aria-label="价格异动阈值百分比"
                className={`flex-1 text-right ${inputClass}`}
              />
              <span className="text-2xs text-fin-muted">%</span>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={submitting}
              className="px-2.5 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-50 transition-colors"
            >
              保存
            </button>
            <button
              type="button"
              onClick={resetForm}
              aria-label="取消添加监控"
              className="p-1 rounded text-fin-muted hover:text-fin-danger transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="px-4 py-2 text-2xs text-fin-danger bg-fin-danger/10 border-b border-fin-border">
          {error}
        </div>
      )}

      {/* 列表 */}
      <div className="divide-y divide-fin-border/40">
        {loading && targets.length === 0 ? (
          <div className="py-6 text-center text-xs text-fin-muted">正在加载监控配置...</div>
        ) : targets.length === 0 && !adding ? (
          <div className="py-6 text-center text-xs text-fin-muted px-4">
            暂无自定义监控，点击上方「添加监控」。
          </div>
        ) : (
          targets.map((target: MonitorTarget) => (
            <div key={target.id} data-testid={`monitor-target-${target.id}`}>
              <div className="group flex items-center justify-between gap-2 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-fin-text truncate">
                      {target.ticker || 'PORTFOLIO'}
                    </span>
                    <span className="shrink-0 px-1.5 py-0.5 rounded text-2xs bg-fin-border/30 text-fin-muted">
                      {TYPE_LABEL[target.type]}
                    </span>
                  </div>
                  <div className="text-2xs text-fin-muted mt-0.5">{describeThreshold(target.config)}</div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {/* 编辑阈值 */}
                  <button
                    type="button"
                    onClick={() =>
                      setEditingTargetId((prev) => (prev === target.id ? null : target.id))
                    }
                    aria-label={`编辑 ${target.ticker || 'PORTFOLIO'} 阈值`}
                    title="编辑阈值"
                    data-testid={`monitor-edit-${target.id}`}
                    className="p-1 rounded text-fin-muted hover:text-fin-primary transition-colors"
                  >
                    <Pencil size={12} />
                  </button>
                  {/* 开关 */}
                  <button
                    type="button"
                    role="switch"
                    aria-checked={target.enabled}
                    aria-label={`${target.ticker || 'PORTFOLIO'} 监控开关`}
                    onClick={() => void patchTarget(target.id, { enabled: !target.enabled })}
                    data-testid={`monitor-toggle-${target.id}`}
                    className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${
                      target.enabled ? 'bg-fin-primary' : 'bg-fin-border'
                    }`}
                  >
                    <span
                      className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                        target.enabled ? 'translate-x-3.5' : 'translate-x-0.5'
                      }`}
                    />
                  </button>
                  {/* 删除（持仓 / 自选自动纳入的不可删，仅 custom 可删） */}
                  {target.type === 'custom' && (
                    <button
                      type="button"
                      onClick={() => void deleteTarget(target.id)}
                      aria-label={`删除 ${target.ticker || 'PORTFOLIO'} 监控`}
                      title="删除"
                      className="p-1 rounded text-fin-muted hover:text-fin-danger opacity-0 group-hover:opacity-100 transition-all"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>

              {/* 内联阈值编辑表单 */}
              {editingTargetId === target.id && (
                <ThresholdEditForm
                  target={target}
                  saving={savingThreshold}
                  onSave={(config) => void handleSaveThreshold(target, config)}
                  onCancel={() => setEditingTargetId(null)}
                />
              )}
            </div>
          ))
        )}
      </div>

      {/* 持仓自动监控说明 */}
      <div className="px-4 py-2.5 border-t border-fin-border text-2xs text-fin-muted leading-relaxed">
        持仓标的自动纳入监控，无需手动添加。
      </div>

      {/* 邮件通知设置分区 */}
      <NotificationSettings sessionId={sessionId} />
    </div>
  );
}

export default MonitorConfigPanel;
