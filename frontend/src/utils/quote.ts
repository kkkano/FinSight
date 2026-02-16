export interface ParsedQuote {
  price?: number;
  change?: number;
  changePct?: number;
}

const toNumber = (value: unknown): number | undefined => {
  if (value === null || value === undefined) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const parseFromObject = (payload: Record<string, unknown>): ParsedQuote | null => {
  const price = toNumber(payload.price);
  if (price === undefined) return null;

  return {
    price,
    change: toNumber(payload.change),
    changePct: toNumber(payload.change_percent ?? payload.changePct),
  };
};

export const parseQuotePayload = (payload: unknown): ParsedQuote => {
  if (!payload) return {};

  if (typeof payload === 'object') {
    const objectPayload = payload as Record<string, unknown>;

    if ('data' in objectPayload) {
      const nested = parseQuotePayload(objectPayload.data);
      if (nested.price !== undefined) return nested;
    }

    const fromObject = parseFromObject(objectPayload);
    if (fromObject) return fromObject;
  }

  const text = typeof payload === 'string' ? payload : String(payload);
  const priceMatch = text.match(/Current Price:\s*\$([0-9.,]+)/i);
  const changeMatch = text.match(/Change:\s*([+-]?[0-9.]+)/i);
  const pctMatch = text.match(/\(([-+]?[0-9.]+)%\)/);
  const fallbackPrice = text.match(/\$([0-9]+(?:\.[0-9]+)?)/);

  return {
    price: priceMatch
      ? toNumber(priceMatch[1].replace(/,/g, ''))
      : fallbackPrice
        ? toNumber(fallbackPrice[1])
        : undefined,
    change: changeMatch ? toNumber(changeMatch[1]) : undefined,
    changePct: pctMatch ? toNumber(pctMatch[1]) : undefined,
  };
};
