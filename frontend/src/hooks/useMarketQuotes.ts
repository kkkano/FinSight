import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../api/client';

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
  { label: '沪深300', ticker: '000300.SS', flag: '🇨🇳' },
  { label: '黄金', ticker: 'GC=F', flag: '🌕' },
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
          const payload = response?.data ?? response;
          const data = payload?.data ?? payload;
          let price: number | undefined;
          let changePct: number | undefined;
          if (typeof data === 'object' && data.price) {
            price = Number(data.price);
            changePct = data.change_percent !== undefined ? Number(data.change_percent) : undefined;
          } else if (typeof data === 'string') {
            const priceMatch = data.match(/\$([0-9.,]+)/);
            const pctMatch = data.match(/\(([-+]?[0-9.]+)%\)/);
            price = priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : undefined;
            changePct = pctMatch ? Number(pctMatch[1]) : undefined;
          }
          return { label: item.label, flag: item.flag, price, changePct, loading: false } as MarketQuote;
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
