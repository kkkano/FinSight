type RightPanelAlertsTabProps = {
  alerts: any[];
  onSubscribeClick?: () => void;
};

export function RightPanelAlertsTab({ alerts, onSubscribeClick }: RightPanelAlertsTabProps) {
  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-fin-text-secondary">Subscriptions</span>
        <span className="text-2xs text-fin-muted bg-fin-bg px-1.5 rounded">{alerts.length} items</span>
      </div>
      <div className="space-y-2">
        {alerts.slice(0, 10).map((item: any, idx: number) => (
          <div key={`${item.ticker || 't'}-${idx}`} className="border-b border-fin-border/50 pb-2 last:border-0">
            <div className="text-xs font-semibold text-fin-text">{item.ticker || '--'} alert</div>
            <div className="text-2xs text-fin-text-secondary">{(item.alert_types || []).join(', ') || '--'}</div>
          </div>
        ))}
        {!alerts.length && <div className="text-xs text-fin-muted py-4 text-center">No active subscriptions</div>}
      </div>
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



