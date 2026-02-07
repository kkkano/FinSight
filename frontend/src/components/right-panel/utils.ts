export const parsePricePayload = (payload: any): { price?: number; change?: number; changePct?: number } => {
  if (!payload) return {};
  if (typeof payload === 'object' && payload.price) {
    return {
      price: Number(payload.price),
      change: payload.change !== undefined ? Number(payload.change) : undefined,
      changePct: payload.change_percent !== undefined ? Number(payload.change_percent) : undefined,
    };
  }

  const text = typeof payload === 'string' ? payload : String(payload);
  const priceMatch = text.match(/Current Price:\s*\$([0-9.,]+)/i);
  const changeMatch = text.match(/Change:\s*([+-]?[0-9.]+)/i);
  const pctMatch = text.match(/\(([-+]?[0-9.]+)%\)/);
  const fallbackPrice = text.match(/\$([0-9]+(?:\.[0-9]+)?)/);

  return {
    price: priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : fallbackPrice ? Number(fallbackPrice[1]) : undefined,
    change: changeMatch ? Number(changeMatch[1]) : undefined,
    changePct: pctMatch ? Number(pctMatch[1]) : undefined,
  };
};

export const formatPct = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

