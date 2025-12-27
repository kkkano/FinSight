import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { SendHorizontal } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

const extractTicker = (text: string): string | null => {
  const tickerPattern = /\b([A-Z]{1,5})\b/g;
  const matches = text.match(tickerPattern);
  return matches && matches.length > 0 ? matches[0] : null;
};

const chartKeywords = ['trend', 'chart', 'kline', 'k-line', '走势', '趋势', '图表'];

export const ChatInput: React.FC = () => {
  const [input, setInput] = useState('');
  const { addMessage, updateMessage, setLoading, isChatLoading, setTicker, setStatus, draft, setDraft } = useStore();
  const inputRef = useRef<HTMLInputElement>(null);

  const shouldGenerateChart = async (
    query: string,
    currentTicker?: string | null,
  ): Promise<{ ticker: string | null; chartType: string | null }> => {
    try {
      const response = await apiClient.detectChartType(query, currentTicker || undefined);

      if (response.success && response.should_generate) {
        const ticker = extractTicker(query) ?? currentTicker ?? null;
        return {
          ticker,
          chartType: response.chart_type || 'line',
        };
      }
    } catch (error) {
      console.error('Chart detection failed:', error);
    }

    const lowerQuery = query.toLowerCase();
    const hasChartKeyword = chartKeywords.some((keyword) => lowerQuery.includes(keyword));
    if (!hasChartKeyword) return { ticker: null, chartType: null };

    const ticker = extractTicker(query) ?? currentTicker ?? null;
    return { ticker, chartType: 'line' };
  };

  const handleSend = async () => {
    if (!input.trim() || isChatLoading) return;

    const userMsgContent = input.trim();
    setInput('');
    setDraft('');

    addMessage({
      id: uuidv4(),
      role: 'user',
      content: userMsgContent,
      timestamp: Date.now(),
    });

    // 创建 AI 消息占位符
    const aiMsgId = uuidv4();
    addMessage({
      id: aiMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isLoading: true,
    });

    setLoading(true);
    setStatus('Streaming response...');

    let fullContent = '';

    try {
      await apiClient.sendMessageStream(
        userMsgContent,
        // onToken - 逐字更新
        (token) => {
          fullContent += token;
          updateMessage(aiMsgId, { content: fullContent, isLoading: true });
        },
        // onToolStart
        (name) => {
          setStatus(`Calling tool: ${name}...`);
        },
        // onToolEnd
        () => {
          setStatus('Generating response...');
        },
        // onDone
        async () => {
          // 检测是否需要图表
          const chartInfo = await shouldGenerateChart(userMsgContent, null);
          if (chartInfo.ticker && chartInfo.chartType) {
            fullContent += `\n\n[CHART:${chartInfo.ticker}:${chartInfo.chartType}]`;
            if (chartInfo.ticker) setTicker(chartInfo.ticker);
          }
          updateMessage(aiMsgId, { content: fullContent, isLoading: false });
          setStatus('Completed');
        },
        // onError
        (error) => {
          updateMessage(aiMsgId, { content: `Error: ${error}`, isLoading: false });
          setStatus('Error occurred');
        }
      );
    } catch (error) {
      updateMessage(aiMsgId, {
        content: 'Network request failed. Please confirm the backend service is running.',
        isLoading: false,
      });
      setStatus('Request failed');
    } finally {
      setLoading(false);
      setTimeout(() => setStatus(null), 2000);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  };

  // 同步外部草稿（重试/编辑时填充输入框）
  useEffect(() => {
    setInput(draft || '');
    if (draft && inputRef.current) {
      inputRef.current.focus();
    }
  }, [draft]);

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="p-4 bg-fin-bg border-t border-fin-border">
      <div className="relative flex items-center max-w-5xl mx-auto">
        <input
          ref={inputRef}
          id="chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything about a ticker... (e.g., AAPL price trend)"
          disabled={isChatLoading}
          className="w-full bg-fin-panel text-fin-text border border-fin-border rounded-xl py-3 pl-4 pr-12 focus:outline-none focus:ring-2 focus:ring-fin-primary/50 focus:border-fin-primary transition-all disabled:opacity-50 disabled:cursor-not-allowed placeholder-fin-muted"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || isChatLoading}
          className="absolute right-2 p-2 bg-fin-primary text-white rounded-lg hover:bg-blue-600 disabled:opacity-0 disabled:scale-90 transition-all duration-200"
        >
          <SendHorizontal size={18} />
        </button>
      </div>
      <div className="text-center mt-2">
        <p className="text-xs text-fin-muted">
          FinSight AI generated content may be inaccurate. Not financial advice.
        </p>
        <div className="mt-2 flex justify-center gap-2 text-[11px] text-fin-muted">
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('推荐几只股票')}
            disabled={isChatLoading}
          >
            快速试用：推荐几只股票
          </button>
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('分析 AAPL 现在能不能买')}
            disabled={isChatLoading}
          >
            示例：分析 AAPL
          </button>
                    <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('用中文生成拼多多综合分析报告')}
            disabled={isChatLoading}
          >
            用中文生成拼多多综合分析报告
          </button>
        </div>
      </div>
    </div>
  );
};
