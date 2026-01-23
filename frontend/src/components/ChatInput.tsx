import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { ThinkingStep } from '../types/index';
import { SendHorizontal } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

const extractTicker = (text: string): string | null => {
  const tickerPattern = /\b([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,4})?)\b/g;
  const matches = text.match(tickerPattern);
  if (!matches) return null;

  const stopwords = new Set([
    'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS',
    'PE', 'EPS', 'MACD', 'RSI', 'KDJ', 'GDP', 'CPI', 'PPI', 'FOMC',
  ]);

  for (const match of matches) {
    const upper = match.toUpperCase();
    if (!stopwords.has(upper)) return upper;
  }
  return null;
};

const chartKeywords = ['trend', 'chart', 'kline', 'k-line', '走势', '趋势', '图表'];
const DEFAULT_HISTORY_LIMIT = Number(import.meta.env.VITE_CHAT_HISTORY_MAX_MESSAGES) || 12;

export const ChatInput: React.FC = () => {
  const [input, setInput] = useState('');
  const {
    addMessage,
    updateMessage,
    setLoading,
    isChatLoading,
    setTicker,
    setStatus,
    draft,
    setDraft,
    currentTicker,
    chatMode,  // 获取当前聊天模式
  } = useStore();
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
    const guessedTicker = extractTicker(userMsgContent);
    if (guessedTicker) {
      setTicker(guessedTicker);
    }
    setInput('');
    setDraft('');

    // 获取当前消息列表用于构建历史（在添加新消息之前）
    const currentMessages = useStore.getState().messages;
    const history = currentMessages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .slice(-DEFAULT_HISTORY_LIMIT)  // 最近 N 条消息（可配置）
      .map(m => ({ role: m.role, content: m.content }));

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
    let thinkingSteps: ThinkingStep[] = [];

    try {
      await apiClient.sendMessageStream(
        userMsgContent,
        // onToken - 逐字更新
        (token) => {
          const safeToken = typeof token === 'string' ? token : JSON.stringify(token);
          if (safeToken) {
            fullContent += safeToken;
          }
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
        // onDone - Phase 2: 支持 report 数据
        async (report?: any, thinking?: ThinkingStep[], meta?: any) => {
          console.log('[ChatInput] onDone called, report:', report); // Debug Log
          // 合并实时收集的 thinking 和 done 事件中的 thinking
          // 如果 done 事件中有 thinking，优先使用（通常是完整版），但也保留之前的实时步骤
          if (thinking && thinking.length) {
            // 如果 done 事件中的 thinking 已包含完整流程，直接使用
            // 否则合并两者（去重）
            const existingStages = new Set(thinkingSteps.map(s => `${s.stage}-${s.message}`));
            const newSteps = thinking.filter(s => !existingStages.has(`${s.stage}-${s.message}`));
            if (newSteps.length > 0 && thinkingSteps.length > 0) {
              // 合并：保留实时步骤 + 添加新步骤
              thinkingSteps = [...thinkingSteps, ...newSteps];
            } else if (thinking.length >= thinkingSteps.length) {
              // done 事件中的更完整，直接使用
              thinkingSteps = thinking;
            }
            // else: 保留现有的 thinkingSteps
          }
          if (!fullContent || fullContent.trim() === '' || fullContent.trim() === '[object Object]') {
            const fallback = typeof meta?.response === 'string'
              ? meta.response
              : (report?.summary || '');
            if (fallback) {
              fullContent = fallback;
            }
          }
          // 检测是否需要图表
          const nextFocus = meta?.current_focus || report?.ticker || guessedTicker || null;
          if (nextFocus) {
            setTicker(nextFocus);
          }

          const chartInfo = await shouldGenerateChart(userMsgContent, nextFocus || currentTicker || null);
          if (chartInfo.ticker && chartInfo.chartType) {
            fullContent += `\n\n[CHART:${chartInfo.ticker}:${chartInfo.chartType}]`;
            if (chartInfo.ticker) setTicker(chartInfo.ticker);
          }
          updateMessage(aiMsgId, { content: fullContent, isLoading: false, report, thinking: thinkingSteps });
          setStatus(null); // 清除状态，不再显示"Streaming response"
        },
        // onError
        (error) => {
          updateMessage(aiMsgId, { content: `Error: ${error}`, isLoading: false });
          setStatus('Error occurred');
        },
        // onThinking
        (step) => {
          thinkingSteps = [...thinkingSteps, step];
          updateMessage(aiMsgId, { thinking: thinkingSteps });
        },
        // mode - 传递当前聊天模式
        chatMode,
        // history - 传递对话历史用于上下文理解
        history
      );
    } catch (error) {
      updateMessage(aiMsgId, {
        content: 'Network request failed. Please confirm the backend service is running.',
        isLoading: false,
      });
      setStatus('Request failed');
    } finally {
      setLoading(false);
      setStatus(null); // 立即清除状态
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
            onClick={() => setInput('NVDA 最新股价和技术面分析')}
            disabled={isChatLoading}
          >
            NVDA 技术分析
          </button>
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('对比 AAPL 和 MSFT 哪个更值得投资')}
            disabled={isChatLoading}
          >
            AAPL vs MSFT 对比
          </button>
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('特斯拉最近有什么重大新闻')}
            disabled={isChatLoading}
          >
            特斯拉新闻
          </button>
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('详细分析苹果公司，生成投资报告')}
            disabled={isChatLoading}
          >
            苹果深度报告
          </button>
        </div>
      </div>
    </div>
  );
};
