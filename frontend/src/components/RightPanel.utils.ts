

export function observedMessageTickers(message?: { thinking?: Array<{ result?: Record<string, unknown> }> }): string[] {
  return [...new Set((message?.thinking ?? []).flatMap((step) => {
    const result = step.result ?? {};
    const payload = result.payload && typeof result.payload === 'object' ? result.payload as Record<string, unknown> : result;
    const inputs = payload.inputs && typeof payload.inputs === 'object' ? payload.inputs as Record<string, unknown> : {};
    return typeof inputs.ticker === 'string' && inputs.ticker ? [inputs.ticker.toUpperCase()] : [];
  }))];
}
