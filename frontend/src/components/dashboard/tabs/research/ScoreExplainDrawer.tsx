import type { InsightCard, ScoreBreakdownItem } from '../../../../types/dashboard';

interface ScoreExplainDrawerProps {
  open: boolean;
  title: string;
  insight: InsightCard | null;
  onClose: () => void;
}

function contributionColor(value: number): string {
  if (value > 0) return 'bg-fin-success/80';
  if (value < 0) return 'bg-fin-danger/80';
  return 'bg-fin-muted/60';
}

function normalizeWidth(item: ScoreBreakdownItem, maxAbs: number): number {
  if (maxAbs <= 0) return 0;
  return Math.min(100, Math.round((Math.abs(item.contribution) / maxAbs) * 100));
}

export function ScoreExplainDrawer({
  open,
  title,
  insight,
  onClose,
}: ScoreExplainDrawerProps) {
  if (!open) return null;

  const breakdown = insight?.score_breakdown ?? [];
  const maxAbsContribution = breakdown.reduce((max, item) => Math.max(max, Math.abs(item.contribution)), 0);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" role="dialog" aria-modal="true">
      <div className="w-full max-w-md h-full bg-fin-card border-l border-fin-border shadow-2xl overflow-y-auto">
        <div className="sticky top-0 z-10 px-4 py-3 border-b border-fin-border bg-fin-card/95 backdrop-blur">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-fin-text">{title} 评分构成</h3>
              <p className="text-2xs text-fin-muted mt-0.5">
                总分 {insight?.score?.toFixed(1) ?? '--'} / 10 · {insight?.score_label ?? ''}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-fin-muted hover:text-fin-text transition-colors"
            >
              关闭
            </button>
          </div>
        </div>

        <div className="p-4 space-y-3">
          {breakdown.length === 0 ? (
            <div className="text-xs text-fin-muted border border-fin-border rounded-lg p-3">
              暂无可解释因子
            </div>
          ) : (
            breakdown.map((item) => (
              <div key={item.factor_key} className="border border-fin-border rounded-lg p-3">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-xs font-medium text-fin-text">{item.label}</span>
                  <span className="text-2xs text-fin-muted">
                    权重 {(item.weight * 100).toFixed(0)}% · 贡献 {item.contribution.toFixed(2)}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-fin-bg-secondary overflow-hidden">
                  <div
                    className={`h-full ${contributionColor(item.contribution)}`}
                    style={{ width: `${normalizeWidth(item, maxAbsContribution)}%` }}
                  />
                </div>
                <div className="mt-2 text-2xs text-fin-muted">
                  数值 {item.value.toFixed(2)}
                </div>
                {item.rationale && (
                  <div className="mt-1 text-2xs text-fin-text/80 leading-relaxed">
                    {item.rationale}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
      <button
        type="button"
        aria-label="close"
        className="flex-1 cursor-default"
        onClick={onClose}
      />
    </div>
  );
}

export default ScoreExplainDrawer;
