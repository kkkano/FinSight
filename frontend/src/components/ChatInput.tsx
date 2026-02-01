import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { ThinkingStep, AgentLogSource } from '../types/index';
import { SendHorizontal, Paperclip, X } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import type { ChatContext } from '../api/client';
import { useStore } from '../store/useStore';
import { useDashboardStore } from '../store/dashboardStore';

const extractTickers = (text: string): string[] => {
  const tickerPattern = /\b([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,4})?)\b/g;
  const matches = text.match(tickerPattern);
  if (!matches) return [];

  const stopwords = new Set([
    'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS',
    'PE', 'EPS', 'MACD', 'RSI', 'KDJ', 'GDP', 'CPI', 'PPI', 'FOMC',
  ]);

  const seen = new Set<string>();
  const tickers: string[] = [];
  for (const match of matches) {
    const upper = match.toUpperCase();
    if (!stopwords.has(upper) && !seen.has(upper)) {
      seen.add(upper);
      tickers.push(upper);
    }
  }
  return tickers;
};

const extractTicker = (text: string): string | null => {
  const tickers = extractTickers(text);
  return tickers.length ? tickers[0] : null;
};
const chartKeywords = ['trend', 'chart', 'kline', 'k-line', '走势', '趋势', '图表'];
const DEFAULT_HISTORY_LIMIT = Number(import.meta.env.VITE_CHAT_HISTORY_MAX_MESSAGES) || 12;

// Agent 日志来源映射 (stage -> AgentLogSource)
const mapStageToSource = (stage: string): AgentLogSource => {
  const mapping: Record<string, AgentLogSource> = {
    supervisor_start: 'supervisor',
    agent_start: 'planner',
    agent_done: 'planner',
    agent_error: 'planner',
    forum_start: 'forum',
    forum_done: 'forum',
    classifying: 'router',
    classified: 'router',
    agent_selected: 'gate',
    tool_selected: 'gate',
    reasoning: 'supervisor',
    reference_resolution: 'supervisor',
    intent_classification: 'router',
    agent_gate: 'gate',
    data_collection: 'supervisor',
    processing: 'supervisor',
    complete: 'system',
    tool_call: 'system',
    llm_call: 'supervisor',
    error: 'system',
  };
  // 检查是否包含 agent 名称
  if (stage.includes('news')) return 'news_agent';
  if (stage.includes('price')) return 'price_agent';
  if (stage.includes('fundamental')) return 'fundamental_agent';
  if (stage.includes('technical')) return 'technical_agent';
  if (stage.includes('macro')) return 'macro_agent';
  if (stage.includes('deep_search') || stage.includes('search')) return 'deep_search_agent';
  return mapping[stage] || 'system';
};

interface ChatInputProps {
  onDashboardRequest?: (symbol: string) => void;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const ChatInput: React.FC<ChatInputProps> = ({ onDashboardRequest: _onDashboardRequest }) => {
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
    // Agent Logs
    addAgentLog,
    updateAgentStatus,
    // Raw SSE Events
    addRawEvent,
  } = useStore();
  const { activeAsset, activeSelections, clearSelection } = useDashboardStore();
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

    // 记录请求开始日志
    addAgentLog({
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      source: 'system',
      level: 'info',
      message: `New query: "${userMsgContent.slice(0, 50)}${userMsgContent.length > 50 ? '...' : ''}"`,
    });
    // 重置所有 Agent 状态为 idle
    updateAgentStatus('supervisor', { status: 'running', startTime: new Date().toISOString() });

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
          // 记录工具调用日志
          addAgentLog({
            id: uuidv4(),
            timestamp: new Date().toISOString(),
            source: 'system',
            level: 'info',
            message: `Tool started: ${name}`,
            tool_name: name,
          });
        },
        // onToolEnd
        () => {
          setStatus('Generating response...');
          // 记录工具完成日志
          addAgentLog({
            id: uuidv4(),
            timestamp: new Date().toISOString(),
            source: 'system',
            level: 'success',
            message: 'Tool execution completed',
          });
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

          const evidencePool = meta?.evidence_pool ?? meta?.data?.evidence_pool;

          const chartInfo = await shouldGenerateChart(userMsgContent, nextFocus || currentTicker || null);
          const markerRegex = /\[CHART:([A-Z0-9.-]+):([a-z]+)\]/g;
          const existingTickers = new Set(
            Array.from(fullContent.matchAll(markerRegex)).map((match) => match[1])
          );
          const tickers = extractTickers(userMsgContent);
          const forceMulti = tickers.length > 1;
          if (chartInfo.chartType || forceMulti) {
            const targetTickers = tickers.length ? tickers : (chartInfo.ticker ? [chartInfo.ticker] : []);
            const missingTickers = targetTickers.filter((ticker) => !existingTickers.has(ticker));
            if (missingTickers.length > 0) {
              const chartType = forceMulti ? "line" : (chartInfo.chartType || "line");
              missingTickers.forEach((ticker) => {
                fullContent += `

[CHART:${ticker}:${chartType}]`;
              });
              if (targetTickers.length === 1) {
                setTicker(targetTickers[0]);
              }
            }
          }
          updateMessage(aiMsgId, { content: fullContent, isLoading: false, report, thinking: thinkingSteps, evidence_pool: evidencePool });
          setStatus(null); // 清除状态，不再显示"Streaming response"
        },
        // onError
        (error) => {
          updateMessage(aiMsgId, { content: `Error: ${error}`, isLoading: false });
          setStatus('Error occurred');
          // 记录错误日志
          addAgentLog({
            id: uuidv4(),
            timestamp: new Date().toISOString(),
            source: 'system',
            level: 'error',
            message: `Error: ${error}`,
          });
          // 更新所有运行中的 Agent 状态为错误
          updateAgentStatus('supervisor', { status: 'error', lastMessage: error });
        },
        // onThinking
        (step) => {
          thinkingSteps = [...thinkingSteps, step];
          updateMessage(aiMsgId, { thinking: thinkingSteps });

          // 将 thinking 事件转换为 AgentLog
          const source = mapStageToSource(step.stage);
          const isError = step.stage.includes('error');
          const isComplete = step.stage.includes('done') || step.stage.includes('complete');
          const isStart = step.stage.includes('start');

          // 添加日志
          addAgentLog({
            id: uuidv4(),
            timestamp: step.timestamp || new Date().toISOString(),
            source,
            level: isError ? 'error' : isComplete ? 'success' : 'info',
            message: step.message || step.stage,
            details: step.result,
          });

          // 更新 Agent 状态
          if (isStart) {
            updateAgentStatus(source, {
              status: 'running',
              startTime: step.timestamp || new Date().toISOString(),
              lastMessage: step.message,
            });
          } else if (isComplete) {
            updateAgentStatus(source, {
              status: 'success',
              endTime: step.timestamp || new Date().toISOString(),
              lastMessage: step.message,
            });
          } else if (isError) {
            updateAgentStatus(source, {
              status: 'error',
              endTime: step.timestamp || new Date().toISOString(),
              lastMessage: step.message,
            });
          }
        },
        // history - 传递对话历史用于上下文理解
        history,
        // onRawEvent - 原始 SSE 事件推送到控制台
        (event) => {
          addRawEvent(event);
        },
        // context - 临时上下文（Selection + Active Symbol）
        (() => {
          const ctx: ChatContext = {};
          if (activeAsset?.symbol) {
            ctx.active_symbol = activeAsset.symbol;
            ctx.view = 'chat';
          }
          if (activeSelections.length === 1) ctx.selection = activeSelections[0];
          if (activeSelections.length > 1) ctx.selections = activeSelections;
          return Object.keys(ctx).length > 0 ? ctx : undefined;
        })()
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
      {/* Selection Pill - 显示当前选中的新闻/报告 */}
      {activeSelections.length > 0 && (
        <div className="max-w-5xl mx-auto mb-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/10 text-amber-500 text-xs font-medium max-w-[400px] border border-amber-500/20">
            <Paperclip size={12} className="shrink-0" />
            <span className="truncate">
              {activeSelections[0].type === 'news' ? '📰' : '📊'}{' '}
              引用: {activeSelections.length === 1
                ? `${activeSelections[0].title.slice(0, 40)}${activeSelections[0].title.length > 40 ? '...' : ''}`
                : `${activeSelections.length}条${activeSelections[0].type === 'news' ? '新闻' : '报告'}`}
            </span>
            <button
              onClick={clearSelection}
              className="shrink-0 p-0.5 rounded-full hover:bg-amber-500/20 transition-colors"
              title="取消引用"
            >
              <X size={12} />
            </button>
          </span>
        </div>
      )}
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
