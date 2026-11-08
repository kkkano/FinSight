import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

/** 公司资料是公开行情，按代码缓存并供看板与标的面板共用。 */
export function useCompanyProfile(ticker: string | null | undefined) {
  const symbol = (ticker || '').trim().toUpperCase();
  return useQuery({
    queryKey: ['company-profile', symbol],
    queryFn: ({ signal }) => apiClient.fetchCompanyProfile(symbol, signal),
    enabled: Boolean(symbol),
    staleTime: 300_000,
    retry: false,
  });
}

export function exchangeDisplayName(exchange: string | null | undefined): string {
  if (!exchange) return '';
  return ({
    NMS: '纳斯达克', NGM: '纳斯达克', NCM: '纳斯达克', NasdaqGS: '纳斯达克', NasdaqGM: '纳斯达克', NasdaqCM: '纳斯达克', NASDAQ: '纳斯达克',
    NYQ: '纽约证券交易所', NYSE: '纽约证券交易所', ASE: 'NYSE American', HKG: '香港交易所', HKSE: '香港交易所', SHH: '上海证券交易所', SHZ: '深圳证券交易所',
  } as Record<string, string>)[exchange] || exchange;
}
