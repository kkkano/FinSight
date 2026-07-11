import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';

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
  const query = useQuery({
    queryKey: ['market-quotes', seeds],
    queryFn: () => Promise.all(
      seeds.map(async (item): Promise<MarketQuote> => {
        try {
          const response = await apiClient.fetchStockPrice(item.ticker);
          const quote = parseQuotePayload(response?.data ?? response);
          return { label: item.label, flag: item.flag, price: quote.price, changePct: quote.changePct, loading: false };
        } catch {
          return { label: item.label, flag: item.flag, loading: false };
        }
      }),
    ),
    staleTime: 5_000,
    refetchInterval: 60_000,
  });
  const { data, refetch: refetchQuery } = query;

  const refresh = useCallback(async () => {
    await refetchQuery();
  }, [refetchQuery]);

  const quotes: MarketQuote[] = data
    ?? seeds.map((item): MarketQuote => ({ label: item.label, flag: item.flag, loading: true }));

  return { quotes, refresh };
}
