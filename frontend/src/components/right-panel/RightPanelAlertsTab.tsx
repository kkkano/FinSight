import type { AlertSubscription } from './types';

type RightPanelAlertsTabProps = {
  alerts: AlertSubscription[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onSubscribeClick?: () => void;
};

const formatTypes = (alertTypes: string[]) => {
  if (!alertTypes.length) return '--';
  return alertTypes
    .map((item) => item.replaceAll('_', ' '))
    .join(', ');
};

export function RightPanelAlertsTab({
  alerts,
  loading = false,
  error = null,
  onRetry,
  onSubscribeClick,
}: RightPanelAlertsTabProps) {
  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-fin-text-secondary">Subscriptions</span>
        <span className="text-2xs text-fin-muted bg-fin-bg px-1.5 rounded">{alerts.length} items</span>
      </div>

      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, idx) => (
            <div key={`alerts-skeleton-${idx}`} className="border border-fin-border rounded-lg p-2 animate-pulse">
              <div className="h-3 w-24 bg-fin-border rounded mb-2" />
              <div className="h-2.5 w-32 bg-fin-border rounded" />
            </div>
          ))}
        </div>
      )}

      {!loading && error && (
        <div className="border border-fin-danger/30 bg-fin-danger/10 rounded-lg p-3 space-y-2">
          <p className="text-xs text-fin-danger">{error}</p>
          <button
            type="button"
            onClick={onRetry}
            className="text-2xs px-2 py-1 rounded border border-fin-border text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors"
          >
            重试
          </button>
        </div>
      )}

      {!loading && !error && (
        <div className="space-y-2">
          {alerts.slice(0, 10).map((item) => (
            <article key={item.id} className="border border-fin-border rounded-lg p-2 space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="text-xs font-semibold text-fin-text">{item.ticker}</div>
                <span
                  className={`text-2xs px-1.5 py-0.5 rounded ${
                    item.disabled
                      ? 'bg-fin-muted/20 text-fin-muted'
                      : 'bg-fin-primary/15 text-fin-primary'
                  }`}
                >
                  {item.disabled ? 'disabled' : 'active'}
                </span>
              </div>
              <div className="text-2xs text-fin-text-secondary">{formatTypes(item.alertTypes)}</div>
              <div className="flex flex-wrap gap-1 text-2xs text-fin-muted">
                {item.priceThreshold !== null && item.priceThreshold !== undefined && (
                  <span className="px-1.5 py-0.5 rounded bg-fin-bg-secondary">
                    price ±{item.priceThreshold}%
                  </span>
                )}
                {item.riskThreshold && (
                  <span className="px-1.5 py-0.5 rounded bg-fin-bg-secondary">
                    risk {item.riskThreshold}
                  </span>
                )}
              </div>
              {item.lastAlertAt && (
                <div className="text-2xs text-fin-muted">
                  Last alert: {new Date(item.lastAlertAt).toLocaleString()}
                </div>
              )}
            </article>
          ))}
          {!alerts.length && <div className="text-xs text-fin-muted py-4 text-center">No active subscriptions</div>}
        </div>
      )}

      <button
        type="button"
        onClick={onSubscribeClick}
        className="w-full py-2 border border-dashed border-fin-border rounded-lg text-xs text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors"
      >
        + Manage subscriptions
      </button>
    </div>
  );
}
