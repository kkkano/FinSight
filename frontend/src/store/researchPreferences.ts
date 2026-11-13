export interface ResearchPreferences {
  watchlistAutoConfirm: boolean;
  showProviderReasoning: boolean;
}

const defaults = (): ResearchPreferences => ({ watchlistAutoConfirm: false, showProviderReasoning: false });
const preferenceKey = (owner: string) => `finsight-research-preferences:${encodeURIComponent(owner)}`;

/** 授权与原始字段显示按账号保存，不继承其它账号的选择。 */
export function readResearchPreferences(owner?: string | null): ResearchPreferences {
  if (!owner || typeof window === 'undefined') return defaults();
  try {
    const raw = window.localStorage.getItem(preferenceKey(owner));
    const value = raw ? JSON.parse(raw) : null;
    return { watchlistAutoConfirm: value?.watchlistAutoConfirm === true, showProviderReasoning: value?.showProviderReasoning === true };
  } catch { return defaults(); }
}

export function writeResearchPreferences(owner: string | null | undefined, value: ResearchPreferences): void {
  if (!owner || typeof window === 'undefined') return;
  try { window.localStorage.setItem(preferenceKey(owner), JSON.stringify(value)); } catch { /* 当前账号的内存选择仍可使用。 */ }
}
