import { zh } from '../locales/zh';

export interface ChatSuggestion {
  label: string;
  prompt: string;
  report?: boolean;
}

export const buildChatSuggestions = (watchlist: Array<{ symbol: string }>): ChatSuggestion[] => {
  const tickers = watchlist
    .map((item) => item.symbol.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 4);
  if (tickers.length > 0) {
    return tickers.map((ticker) => ({
      label: `> ${ticker} 分析`,
      prompt: `分析一下 ${ticker} 的最新基本面、技术面、催化剂与主要风险`,
    }));
  }
  return [
    { label: zh.chat.suggestions.nvdaLabel, prompt: zh.chat.suggestions.nvdaPrompt },
    { label: zh.chat.suggestions.compareLabel, prompt: zh.chat.suggestions.comparePrompt },
    { label: zh.chat.suggestions.teslaLabel, prompt: zh.chat.suggestions.teslaPrompt },
    { label: zh.chat.suggestions.reportLabel, prompt: zh.chat.suggestions.reportPrompt, report: true },
  ];
};
