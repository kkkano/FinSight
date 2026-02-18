import type {
  AlertEvent,
  AlertEventState,
  AlertSubscription,
  AlertSubscriptionState,
} from './types';

type RightPanelAlertsTabProps = {
  subscriptions: AlertSubscription[];
  events: AlertEvent[];
  emailConfigured: boolean;
  eventState: AlertEventState;
  subscriptionState: AlertSubscriptionState;
  unreadCount: number;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onMarkRead?: () => void;
  onSubscribeClick?: () => void;
};

const formatTypes = (alertTypes: string[]) => {
  if (!alertTypes.length) return '--';
  return alertTypes.map((item) => item.replaceAll('_', ' ')).join(', ');
};

const severityClass: Record<string, string> = {
  critical: 'bg-fin-danger/20 text-fin-danger border-fin-danger/30',
  high: 'bg-fin-danger/10 text-fin-danger border-fin-danger/20',
  medium: 'bg-fin-warning/10 text-fin-warning border-fin-warning/20',
  low: 'bg-fin-success/10 text-fin-success border-fin-success/20',
};

function renderEventEmptyState(state: AlertEventState) {
  if (state === 'no_email') return '未配置订阅邮箱，无法加载预警事件';
  if (state === 'no_events') return '暂无触发事件';
  if (state === 'error') return '预警事件加载失败';
  return '暂无触发事件';
}

function renderSubscriptionEmptyState(state: AlertSubscriptionState) {
  if (state === 'no_email') return '先配置订阅邮箱后再管理订阅';
  if (state === 'no_subscriptions') return '无活跃订阅配置';
  if (state === 'error') return '订阅配置加载失败';
  return '无活跃订阅配置';
}

export function RightPanelAlertsTab({
  subscriptions,
  events,
  emailConfigured,
  eventState,
  subscriptionState,
  unreadCount,
  loading = false,
  error = null,
  onRetry,
  onMarkRead,
  onSubscribeClick,
}: RightPanelAlertsTabProps) {
  const showLoading = loading || eventState === 'loading' || subscriptionState === 'loading';
  const showError = Boolean(error) || eventState === 'error' || subscriptionState === 'error';

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-fin-text-secondary">最近触发事件</span>
        <div className="flex items-center gap-2">
          <span className="text-2xs text-fin-muted bg-fin-bg px-1.5 rounded">
            未读 {unreadCount}
          </span>
          <button
            type="button"
            onClick={onMarkRead}
            className="text-2xs px-2 py-1 rounded border border-fin-border text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors"
          >
            标记已读
          </button>
        </div>
      </div>

      {showLoading && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, idx) => (
            <div key={`alerts-skeleton-${idx}`} className="border border-fin-border rounded-lg p-2 animate-pulse">
              <div className="h-3 w-24 bg-fin-border rounded mb-2" />
              <div className="h-2.5 w-32 bg-fin-border rounded" />
            </div>
          ))}
        </div>
      )}

      {!showLoading && showError && (
        <div className="border border-fin-danger/30 bg-fin-danger/10 rounded-lg p-3 space-y-2">
          <p className="text-xs text-fin-danger">{error || '预警数据加载失败'}</p>
          <button
            type="button"
            onClick={onRetry}
            className="text-2xs px-2 py-1 rounded border border-fin-border text-fin-text-secondary hover:text-fin-primary hover:border-fin-primary transition-colors"
          >
            重试
          </button>
        </div>
      )}

      {!showLoading && !showError && (
        <>
          <div className="space-y-2">
            {eventState === 'ready' && events.slice(0, 20).map((event) => (
              <article key={event.id} className="border border-fin-border rounded-lg p-2 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-fin-text truncate">
                    {event.ticker} · {event.title}
                  </div>
                  <span
                    className={`text-2xs px-1.5 py-0.5 rounded border ${
                      severityClass[event.severity] ?? 'bg-fin-bg text-fin-muted border-fin-border'
                    }`}
                  >
                    {event.severity}
                  </span>
                </div>
                {event.message && (
                  <div className="text-2xs text-fin-text-secondary line-clamp-2">{event.message}</div>
                )}
                <div className="text-2xs text-fin-muted">
                  {new Date(event.triggeredAt).toLocaleString()}
                </div>
              </article>
            ))}
            {eventState !== 'ready' && (
              <div className="text-xs text-fin-muted py-3 text-center border border-fin-border rounded-lg">
                {renderEventEmptyState(eventState)}
              </div>
            )}
            {!emailConfigured && eventState === 'ready' && (
              <div className="text-xs text-fin-muted py-3 text-center border border-fin-border rounded-lg">
                未配置订阅邮箱，无法加载预警事件
              </div>
            )}
          </div>

          <div className="pt-2 border-t border-fin-border/60 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-fin-text-secondary">当前订阅配置</span>
              <span className="text-2xs text-fin-muted bg-fin-bg px-1.5 rounded">
                {subscriptions.length} items
              </span>
            </div>
            {subscriptionState === 'ready' && subscriptions.slice(0, 10).map((item) => (
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
              </article>
            ))}
            {subscriptionState !== 'ready' && (
              <div className="text-xs text-fin-muted py-3 text-center border border-fin-border rounded-lg">
                {renderSubscriptionEmptyState(subscriptionState)}
              </div>
            )}
          </div>
        </>
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
