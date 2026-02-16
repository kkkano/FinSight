import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../api/client';
import { parseQuotePayload } from '../utils/quote';

export type MarketQuoteSeed = {
  label: string;
  ticker: string;
  flag: string;
};

export type MarketQuote = {
  label: string;
  flag: string;
  price?: number;
  changePct?: number;
  loading?: boolean;
};

export const MARKET_INDICES: MarketQuoteSeed[] = [
  { label: 'NASDAQ', ticker: '^IXIC', flag: '🇺🇸' },
  { label: 'S&P 500', ticker: '^GSPC', flag: '🇺🇸' },
  { label: 'CSI 300', ticker: '000300.SS', flag: '🇨🇳' },
  { label: 'Gold', ticker: 'GC=F', flag: '🥇' },
  { label: 'BTC', ticker: 'BTC-USD', flag: '₿' },
];

export function useMarketQuotes(seeds: MarketQuoteSeed[] = MARKET_INDICES) {
  const [quotes, setQuotes] = useState<MarketQuote[]>(
    seeds.map((m) => ({ label: m.label, flag: m.flag, loading: true })),
  );

  const refresh = useCallback(async () => {
    const results = await Promise.all(
      seeds.map(async (item) => {
        try {
          const response = await apiClient.fetchStockPrice(item.ticker);
          const quote = parseQuotePayload(response?.data ?? response);

          return {
            label: item.label,
            flag: item.flag,
            price: quote.price,
            changePct: quote.changePct,
            loading: false,
          } as MarketQuote;
        } catch {
          return { label: item.label, flag: item.flag, loading: false } as MarketQuote;
        }
      }),
    );
    setQuotes(results);
  }, [seeds]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 60_000);
    return () => clearInterval(timer);
  }, [refresh]);

  return { quotes, refresh };
}
