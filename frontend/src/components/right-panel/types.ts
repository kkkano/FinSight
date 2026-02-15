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

