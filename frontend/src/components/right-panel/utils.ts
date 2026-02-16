import { parseQuotePayload } from '../../utils/quote';

export const parsePricePayload = (payload: unknown): { price?: number; change?: number; changePct?: number } =>
  parseQuotePayload(payload);

export const formatPct = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};
