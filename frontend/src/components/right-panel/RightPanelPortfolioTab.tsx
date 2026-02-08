import type { Dispatch, SetStateAction } from 'react';
import type { PortfolioRow, PortfolioSummary } from './types';
import { formatPct } from './utils';

type RightPanelPortfolioTabProps = {
  positionRows: PortfolioRow[];
  portfolioSummary: PortfolioSummary | null;
  isPortfolioEditing: boolean;
  positionDrafts: Record<string, string>;
  setPositionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  onStartPortfolioEdit: () => void;
  onCancelPortfolioEdit: () => void;
  onSavePortfolioEdit: () => void;
};

export function RightPanelPortfolioTab({
  positionRows,
  portfolioSummary,
  isPortfolioEditing,
  positionDrafts,
  setPositionDrafts,
  onStartPortfolioEdit,
  onCancelPortfolioEdit,
  onSavePortfolioEdit,
}: RightPanelPortfolioTabProps) {
  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-fin-text-secondary">Portfolio</span>
        <button
          type="button"
          onClick={() => (isPortfolioEditing ? onSavePortfolioEdit() : onStartPortfolioEdit())}
          className="text-2xs px-2 py-0.5 rounded-full border border-fin-border text-fin-muted hover:text-fin-primary hover:border-fin-primary transition-colors"
        >
          {isPortfolioEditing ? 'Save' : 'Edit'}
        </button>
      </div>

      {isPortfolioEditing ? (
        <div className="space-y-3">
          {positionRows.length > 0 ? (
            <div className="space-y-2">
              {positionRows.map((item) => (
                <div key={item.ticker} className="flex items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-fin-text">{item.ticker}</span>
                    <span className="text-2xs text-fin-muted">
                      {typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : '--'}
                    </span>
                  </div>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.01"
                    value={positionDrafts[item.ticker] ?? ''}
                    onChange={(event) =>
                      setPositionDrafts((prev) => ({ ...prev, [item.ticker]: event.target.value }))
                    }
                    className="w-20 px-2 py-1 rounded border border-fin-border bg-fin-bg text-fin-text text-right text-xs focus:outline-none focus:border-fin-primary"
                    placeholder="0"
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-fin-muted">Add watchlist tickers to set holdings.</div>
          )}
          <div className="flex items-center justify-between text-2xs text-fin-muted">
            <span>Blank or 0 removes a position.</span>
            <button type="button" onClick={onCancelPortfolioEdit} className="hover:text-fin-text">
              Cancel
            </button>
          </div>
        </div>
      ) : portfolioSummary ? (
        <div className="space-y-3">
          <div className="space-y-1">
            <div className="text-xl font-bold text-fin-text">${portfolioSummary.totalValue.toLocaleString()}</div>
            <div className={`text-sm font-medium ${portfolioSummary.dayChange >= 0 ? 'text-fin-success' : 'text-fin-danger'}`}>
              {portfolioSummary.dayChange >= 0 ? '+' : ''}
              {portfolioSummary.dayChange.toFixed(2)} ({formatPct(portfolioSummary.avgChange)})
            </div>
            <div className="text-2xs text-fin-muted">Holdings {portfolioSummary.holdingsCount}</div>
          </div>
          <div className="space-y-2">
            {portfolioSummary.holdings.map((item) => (
              <div key={item.ticker} className="flex items-center justify-between text-xs">
                <div className="flex flex-col">
                  <span className="font-semibold text-fin-text">{item.ticker}</span>
                  <span className="text-2xs text-fin-muted">
                    {item.shares} shares{typeof item.price === 'number' ? ` @ $${item.price.toFixed(2)}` : ''}
                  </span>
                </div>
                <div className="text-right">
                  <div className="text-fin-text">${item.value.toLocaleString()}</div>
                  <div className={`text-2xs ${item.dayChange >= 0 ? 'text-fin-success' : 'text-fin-danger'}`}>
                    {item.dayChange >= 0 ? '+' : ''}
                    {item.dayChange.toFixed(2)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-xs text-fin-muted py-4 text-center">Set holdings to generate portfolio summary.</div>
      )}
    </div>
  );
}

