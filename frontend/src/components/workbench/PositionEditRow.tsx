/**
 * PositionEditRow.tsx —— 持仓行内编辑 / 新增表单
 *
 * 从 PortfolioEditor 拆出，复用于「添加持仓」和「编辑持仓」两种场景。
 * 字段：ticker（编辑态只读）/ 股数 / 成本价。
 */
import { useState, type KeyboardEvent } from 'react';
import { Check, Loader2, X } from 'lucide-react';

interface PositionEditRowProps {
  mode: 'create' | 'edit';
  saving: boolean;
  initialTicker?: string;
  initialShares?: number;
  initialAvgCost?: number | null;
  onSave: (ticker: string, shares: number, avgCost: number | null) => void;
  onCancel: () => void;
}

export function PositionEditRow({
  mode,
  saving,
  initialTicker = '',
  initialShares,
  initialAvgCost,
  onSave,
  onCancel,
}: PositionEditRowProps) {
  const [ticker, setTicker] = useState(initialTicker);
  const [shares, setShares] = useState(initialShares != null ? String(initialShares) : '');
  const [avgCost, setAvgCost] = useState(
    initialAvgCost != null ? String(initialAvgCost) : '',
  );

  const isEdit = mode === 'edit';

  const submit = () => {
    const parsedShares = Number(shares);
    const parsedCost = avgCost.trim() ? Number(avgCost) : null;
    onSave(
      ticker,
      parsedShares,
      parsedCost != null && Number.isFinite(parsedCost) ? parsedCost : null,
    );
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    } else if (e.key === 'Escape') {
      onCancel();
    }
  };

  const inputClass =
    'min-w-0 px-2 py-1 text-xs rounded-lg border border-fin-border bg-fin-bg text-fin-text placeholder:text-fin-muted focus:outline-none focus:border-fin-primary focus:ring-1 focus:ring-fin-primary/30 disabled:opacity-50';

  return (
    <div className="flex items-center gap-2" data-testid="position-edit-row">
      <input
        type="text"
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        onKeyDown={handleKeyDown}
        placeholder="代码"
        aria-label="股票代码"
        disabled={isEdit || saving}
        className={`w-20 ${inputClass}`}
        autoFocus={mode === 'create'}
      />
      <input
        type="number"
        inputMode="decimal"
        min="0"
        step="any"
        value={shares}
        onChange={(e) => setShares(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="股数"
        aria-label="持仓股数"
        disabled={saving}
        className={`flex-1 text-right ${inputClass}`}
      />
      <input
        type="number"
        inputMode="decimal"
        min="0"
        step="any"
        value={avgCost}
        onChange={(e) => setAvgCost(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="成本价"
        aria-label="成本价"
        disabled={saving}
        className={`flex-1 text-right ${inputClass}`}
      />
      <button
        type="button"
        onClick={submit}
        disabled={saving}
        aria-label="保存"
        title="保存"
        className="p-1 rounded text-fin-success hover:text-fin-success disabled:opacity-50 transition-colors"
      >
        {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
      </button>
      <button
        type="button"
        onClick={onCancel}
        disabled={saving}
        aria-label="取消"
        title="取消"
        className="p-1 rounded text-fin-muted hover:text-fin-danger disabled:opacity-50 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
}

export default PositionEditRow;
