export type RightPanelTab = 'alerts' | 'portfolio' | 'chart' | 'execution';

export type WatchlistItem = {
  ticker: string;
  label: string;
  price?: number | null;
  change?: number | null;
  changePct?: number | null;
};

export type PortfolioRow = WatchlistItem & {
  shares: number;
  value: number;
  dayChange: number;
};

export type PortfolioSummary = {
  holdings: PortfolioRow[];
  holdingsCount: number;
  totalValue: number;
  dayChange: number;
  avgChange: number;
};

export type AlertSubscription = {
  id: string;
  ticker: string;
  alertTypes: string[];
  disabled: boolean;
  priceThreshold?: number | null;
  riskThreshold?: string | null;
  lastAlertAt?: string | null;
  updatedAt?: string | null;
  source: 'polling';
};

export type AlertEvent = {
  id: string;
  ticker: string;
  eventType: string;
  severity: 'low' | 'medium' | 'high' | 'critical' | string;
  title: string;
  message: string;
  triggeredAt: string;
  metadata?: Record<string, unknown>;
};
