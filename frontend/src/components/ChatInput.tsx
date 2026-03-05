import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { ThinkingStep, AgentLogSource } from '../types/index';
import { SendHorizontal, Paperclip, X } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import type { ChatContext } from '../api/client';
import { useStore } from '../store/useStore';
import { useDashboardStore } from '../store/dashboardStore';
import { useToast } from './ui';

const TICKER_STOPWORDS = new Set([
  'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS',
  'PE', 'EPS', 'MACD', 'RSI', 'KDJ', 'GDP', 'CPI', 'PPI', 'FOMC',
  'WITH', 'VIEW', 'FROM', 'FOR', 'OVER', 'NEWS', 'WHAT', 'WHEN', 'WHERE',
  'WHY', 'THIS', 'THAT', 'THE', 'AND', 'ARE', 'WAS', 'WERE',
]);

const MAX_AUTO_CHART_TICKERS = 3;
const TICKER_PATTERN = /^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/;

const mergeTickerCandidates = (...sources: Array<string[] | undefined>): string[] => {
  const merged: string[] = [];
  const seen = new Set<string>();
  for (const source of sources) {
    for (const raw of source ?? []) {
      const ticker = String(raw || '').trim().toUpperCase();
      if (!ticker || seen.has(ticker)) continue;
      if (TICKER_STOPWORDS.has(ticker)) continue;
      if (!TICKER_PATTERN.test(ticker)) continue;
      seen.add(ticker);
      merged.push(ticker);
      if (merged.length >= MAX_AUTO_CHART_TICKERS) return merged;
    }
  }
  return merged;
};

const extractTickers = (text: string): string[] => {
  if (!text || !text.trim()) return [];

  const seen = new Set<string>();
  const tickers: string[] = [];
  const addTicker = (raw: string) => {
    const symbol = String(raw || '').trim().toUpperCase();
    if (!symbol || seen.has(symbol)) return;
    if (symbol.length > 20 || /\s/.test(symbol)) return;
    seen.add(symbol);
    tickers.push(symbol);
  };

  // Structured symbols: index/crypto/futures/China market suffix.
  for (const match of text.matchAll(/\^([A-Za-z]{1,8})\b/g)) {
    addTicker(`^${match[1]}`);
  }
  for (const match of text.matchAll(/\b(\d{5,6}\.(?:SS|SZ|BJ|HK))\b/gi)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\b([A-Za-z]{1,8}-[A-Za-z]{2,5})\b/g)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\b([A-Za-z]{1,4}=F)\b/g)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\$([A-Za-z]{1,6})\b/g)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\b([A-Za-z]{1,6}[.-][A-Za-z]{1,4})\b/g)) {
    addTicker(match[1]);
  }

  // Plain words: only accept user-explicit uppercase tokens (e.g. AAPL, TSLA).
  const alphaTokens = Array.from(text.matchAll(/\b([A-Za-z]{2,6})\b/g)).map((match) => match[1]);
  for (const token of alphaTokens) {
    if (token !== token.toUpperCase()) continue;
    const upper = token.toUpperCase();
    if (TICKER_STOPWORDS.has(upper)) continue;
    addTicker(upper);
  }

  return tickers.slice(0, MAX_AUTO_CHART_TICKERS);
};

const extractTicker = (text: string): string | null => {
  const tickers = extractTickers(text);
  return tickers.length ? tickers[0] : null;
};
const chartKeywords = ['trend', 'chart', 'kline', 'k-line', '走势', '图表', 'k线'];
const DEFAULT_HISTORY_LIMIT = Number(import.meta.env.VITE_CHAT_HISTORY_MAX_MESSAGES) || 12;

// Agent 阶段到日志源的映射 (stage -> AgentLogSource)
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
  if (stage.startsWith('langgraph_')) return 'supervisor';
  if (stage.startsWith('executor_step')) return 'supervisor';
  if (stage.startsWith('llm_')) return 'supervisor';
  if (stage.startsWith('cache_')) return 'system';
  if (stage === 'api_call' || stage === 'data_source') return 'system';
  if (stage === 'agent_step') return 'planner';
  // 未匹配时尝试根据 stage 名称匹配 agent
  if (stage.includes('news')) return 'news_agent';
  if (stage.includes('price')) return 'price_agent';
  if (stage.includes('fundamental')) return 'fundamental_agent';
  if (stage.includes('technical')) return 'technical_agent';
  if (stage.includes('macro')) return 'macro_agent';
  if (stage.includes('deep_search') || stage.includes('search')) return 'deep_search_agent';
  return mapping[stage] || 'system';
};

const estimateProgress = (stage: string, current: number): number => {
  const langgraphNodeProgress: Record<string, number> = {
    normalize_ui_context: 5,
    resolve_subject: 12,
    clarify: 18,
    parse_operation: 25,
    policy_gate: 35,
    planner: 50,
    execute_plan: 72,
    synthesize: 88,
    render: 95,
  };

  if (stage.startsWith('langgraph_')) {
    const node = stage
      .replace(/^langgraph_/, '')
      .replace(/_(start|done)$/, '');
    const base = langgraphNodeProgress[node];
    if (typeof base === 'number') {
      return stage.endsWith('_done') ? Math.min(99, base + 4) : base;
    }
  }

  const staticProgress: Record<string, number> = {
    classifying: 8,
    classified: 15,
    reference_resolution: 20,
    intent_classification: 26,
    agent_gate: 35,
    agent_selected: 38,
    tool_selected: 45,
    supervisor_start: 5,
    forum_start: 90,
    forum_done: 98,
    complete: 100,
  };
  if (typeof staticProgress[stage] === 'number') {
    return staticProgress[stage];
  }

  if (stage === 'executor_step_start' || stage === 'agent_start') {
    return Math.max(current, 72);
  }
  if (stage === 'executor_step_done' || stage === 'agent_done') {
    return Math.min(96, Math.max(current, current + 3));
  }
  if (stage.includes('error')) {
    return current;
  }
  return current;
};

const formatExecutionStep = (stage: string, message?: string): string => {
  if (message && message.trim()) {
    return message.trim();
  }
  if (stage.startsWith('langgraph_')) {
    const label = stage
      .replace(/^langgraph_/, '')
      .replace(/_(start|done)$/, '')
      .replace(/_/g, ' ');
    return `LangGraph: ${label}`;
  }
  return stage.replace(/_/g, ' ');
};

interface ChatInputProps {
  onDashboardRequest?: (symbol: string) => void;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const ChatInput: React.FC<ChatInputProps> = ({ onDashboardRequest: _onDashboardRequest }) => {
  const [input, setInput] = useState('');
  const [outputMode, setOutputMode] = useState<'brief' | 'investment_report'>('brief');
  const {
    addMessage,
    updateMessage,
    setLoading,
    isChatLoading,
    setTicker,
    setStatus,
    setExecutionState,
    resetExecutionState,
    draft,
    setDraft,
    currentTicker,
    subscriptionEmail,
    sessionId,
    setSessionId,
    // Agent Logs
    addAgentLog,
    updateAgentStatus,
    // Raw SSE Events
    addRawEvent,
    traceRawEnabled,
    setRequestMetrics,
  } = useStore();
  const { toast } = useToast();
  const { activeAsset, activeSelections, clearSelection } = useDashboardStore();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const shouldGenerateChart = async (
    query: string,
    currentTicker?: string | null,
  ): Promise<{ tickers: string[]; chartType: string | null }> => {
    try {
      const response = await apiClient.detectChartType(query, currentTicker || undefined);
      const apiCandidates = Array.isArray(response?.ticker_candidates)
        ? response.ticker_candidates.map((value: unknown) => String(value))
        : [];
      const resolvedTicker = typeof response?.resolved_ticker === 'string' && response.resolved_ticker.trim()
        ? [response.resolved_ticker]
        : [];
      const localCandidates = extractTickers(query);
      const contextual = currentTicker ? [currentTicker] : [];
      const merged = mergeTickerCandidates(apiCandidates, resolvedTicker, localCandidates, contextual);

      if (response.success && response.should_generate) {
        return {
          tickers: merged,
          chartType: response.chart_type || 'line',
        };
      }
    } catch (error) {
      console.error('Chart detection failed:', error);
    }

    const lowerQuery = query.toLowerCase();
    const hasChartKeyword = chartKeywords.some((keyword) => lowerQuery.includes(keyword));
    if (!hasChartKeyword) return { tickers: [], chartType: null };

    const localCandidates = extractTickers(query);
    const contextual = currentTicker ? [currentTicker] : [];
    return { tickers: mergeTickerCandidates(localCandidates, contextual), chartType: 'line' };
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
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.overflowY = 'hidden';
    }

    // Build history before appending new messages.
    const currentMessages = useStore.getState().messages;
    const history = currentMessages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-DEFAULT_HISTORY_LIMIT)
      .map((m) => ({ role: m.role, content: m.content }));

    addMessage({
      id: uuidv4(),
      role: 'user',
      content: userMsgContent,
      timestamp: Date.now(),
    });

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
    setExecutionState('Preparing request', 0);

    addAgentLog({
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      source: 'system',
      level: 'info',
      message: `New query: "${userMsgContent.slice(0, 50)}${userMsgContent.length > 50 ? '...' : ''}"`,
    });
    updateAgentStatus('supervisor', { status: 'running', startTime: new Date().toISOString() });

    let fullContent = '';
    let thinkingSteps: ThinkingStep[] = [];
    const effectiveOutputMode = outputMode;

    try {
      await apiClient.sendMessageStream(
        userMsgContent,
        (token) => {
          const safeToken = typeof token === 'string' ? token : JSON.stringify(token);
          if (safeToken) {
            fullContent += safeToken;
          }
          updateMessage(aiMsgId, { content: fullContent, isLoading: true });
        },
        (name) => {
          setStatus(`Calling tool: ${name}...`);
          const current = useStore.getState().executionProgress ?? 0;
          setExecutionState(`Tool: ${name}`, Math.max(current, 72));
          addAgentLog({
            id: uuidv4(),
            timestamp: new Date().toISOString(),
            source: 'system',
            level: 'info',
            message: `Tool started: ${name}`,
            tool_name: name,
          });
        },
        () => {
          setStatus('Generating response...');
          const current = useStore.getState().executionProgress ?? 0;
          setExecutionState('Synthesizing response', Math.max(current, 80));
          addAgentLog({
            id: uuidv4(),
            timestamp: new Date().toISOString(),
            source: 'system',
            level: 'success',
            message: 'Tool execution completed',
          });
        },
        async (report?: any, thinking?: ThinkingStep[], meta?: any) => {
          const metrics = meta?.metrics || {};
          if (metrics && typeof metrics === 'object') {
            setRequestMetrics({
              llmTotalCalls: Number(metrics.llm_total_calls || 0),
              toolTotalCalls: Number(metrics.tool_total_calls || 0),
              updatedAt: new Date().toISOString(),
            });
          }

          if (typeof meta?.session_id === 'string' && meta.session_id.trim() && meta.session_id !== sessionId) {
            setSessionId(meta.session_id);
          }

          if (thinking && thinking.length) {
            const existingStages = new Set(thinkingSteps.map((s) => `${s.stage}-${s.message}`));
            const newSteps = thinking.filter((s) => !existingStages.has(`${s.stage}-${s.message}`));
            if (newSteps.length > 0 && thinkingSteps.length > 0) {
              thinkingSteps = [...thinkingSteps, ...newSteps];
            } else if (thinking.length >= thinkingSteps.length) {
              thinkingSteps = thinking;
            }
          }

          if (!fullContent || fullContent.trim() === '' || fullContent.trim() === '[object Object]') {
            const blockedReport = meta?.blocked_report && typeof meta.blocked_report === 'object'
              ? meta.blocked_report : null;
            const fallback = typeof meta?.response === 'string' && meta.response.trim()
              ? meta.response
              : report?.summary || blockedReport?.summary || '';
            if (fallback) {
              fullContent = fallback;
            }
          }

          // 当 report 为空但 blocked_report 存在时，使用 blocked_report
          if (!report && meta?.blocked_report && typeof meta.blocked_report === 'object') {
            report = meta.blocked_report;
          }

          const nextFocus = meta?.current_focus || report?.ticker || guessedTicker || null;
          if (nextFocus) {
            setTicker(nextFocus);
          }

          const evidencePool = meta?.evidence_pool ?? meta?.data?.evidence_pool;
          const chartInfo = await shouldGenerateChart(userMsgContent, nextFocus || currentTicker || null);
          const markerRegex = /\[CHART:([A-Z0-9.^=-]+):([a-z]+)\]/g;
          const existingTickers = new Set(Array.from(fullContent.matchAll(markerRegex)).map((match) => match[1]));
          const tickers = chartInfo.tickers.length ? chartInfo.tickers : extractTickers(userMsgContent);
          const forceMulti = tickers.length > 1;

          if (chartInfo.chartType || forceMulti) {
            const targetTickers = tickers.slice(0, MAX_AUTO_CHART_TICKERS);
            const missingTickers = targetTickers.filter((ticker) => !existingTickers.has(ticker));
            if (missingTickers.length > 0) {
              const chartType = forceMulti ? 'line' : chartInfo.chartType || 'line';
              missingTickers.forEach((ticker) => {
                fullContent += `\n\n[CHART:${ticker}:${chartType}]`;
              });
              if (targetTickers.length === 1) {
                setTicker(targetTickers[0]);
              }
            }
          }

          updateMessage(aiMsgId, {
            content: fullContent,
            isLoading: false,
            report,
            thinking: thinkingSteps,
            evidence_pool: evidencePool,
          });
          setExecutionState('Completed', 100);
          setStatus(null);
        },
        (error) => {
          updateMessage(aiMsgId, { content: `Error: ${error}`, isLoading: false });
          setStatus('Error occurred');
          toast({
            type: 'error',
            title: '网络请求失败',
            message: '请确认后端服务已启动',
          });
          const current = useStore.getState().executionProgress ?? 0;
          setExecutionState('Execution failed', current);
          addAgentLog({
            id: uuidv4(),
            timestamp: new Date().toISOString(),
            source: 'system',
            level: 'error',
            message: `Error: ${error}`,
          });
          updateAgentStatus('supervisor', { status: 'error', lastMessage: error });
        },
        (step) => {
          thinkingSteps = [...thinkingSteps, step];
          updateMessage(aiMsgId, { thinking: thinkingSteps });
          const current = useStore.getState().executionProgress ?? 0;
          const progress = estimateProgress(step.stage, current);
          const stepLabel = formatExecutionStep(step.stage, step.message);
          setExecutionState(stepLabel, progress);

          const source = mapStageToSource(step.stage);
          const isError = step.stage.includes('error');
          const isComplete = step.stage.includes('done') || step.stage.includes('complete');
          const isStart = step.stage.includes('start');

          addAgentLog({
            id: uuidv4(),
            timestamp: step.timestamp || new Date().toISOString(),
            source,
            level: isError ? 'error' : isComplete ? 'success' : 'info',
            message: step.message || step.stage,
            details: step.result,
          });

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
        history,
        (event) => {
          addRawEvent(event);
        },
        (() => {
          const ctx: ChatContext = {};
          if (activeAsset?.symbol) {
            ctx.active_symbol = activeAsset.symbol;
            ctx.view = 'chat';
          }
          if (activeSelections.length === 1) ctx.selection = activeSelections[0];
          if (activeSelections.length > 1) ctx.selections = activeSelections;
          if (subscriptionEmail) ctx.user_email = subscriptionEmail;
          return Object.keys(ctx).length > 0 ? ctx : undefined;
        })(),
        effectiveOutputMode === 'investment_report'
          ? {
              output_mode: 'investment_report',
              strict_selection: false,
              confirmation_mode: 'skip' as const,
              trace_raw_override: traceRawEnabled ? 'on' : 'off',
            }
          : { output_mode: 'brief', confirmation_mode: 'skip' as const, trace_raw_override: traceRawEnabled ? 'on' : 'off' },
        sessionId || undefined,
        traceRawEnabled,
      );
    } catch {
      updateMessage(aiMsgId, {
        content: 'Network request failed. Please confirm the backend service is running.',
        isLoading: false,
      });
      setStatus('Request failed');
      toast({
        type: 'error',
        title: '网络请求失败',
        message: '请确认后端服务已启动',
      });
      const current = useStore.getState().executionProgress ?? 0;
      setExecutionState('Request failed', current);
    } finally {
      setLoading(false);
      setStatus(null);
      resetExecutionState();
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  };

  useEffect(() => {
    setInput(draft || '');
    if (draft && inputRef.current) {
      inputRef.current.focus();
      setDraft('');
    }
  }, [draft, setDraft]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canGenerateReport = Boolean(activeAsset?.symbol || currentTicker || activeSelections.length > 0);

  useEffect(() => {
    if (!canGenerateReport && outputMode === 'investment_report') {
      setOutputMode('brief');
    }
  }, [canGenerateReport, outputMode]);

  return (
    <div className="p-4 bg-fin-bg border-t border-fin-border">
      {/* Selection Pill - 显示当前选中的内容引用 */}
      {activeSelections.length > 0 && (
        <div className="max-w-5xl mx-auto mb-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/10 text-amber-500 text-xs font-medium max-w-[400px] border border-amber-500/20">
            <Paperclip size={12} className="shrink-0" />
            <span className="truncate">
              {activeSelections[0].type === 'news' ? '新闻' : activeSelections[0].type === 'risk' ? '风险' : activeSelections[0].type === 'insight' ? '洞察' : '报告'}{' '}
              已选: {activeSelections.length === 1
                ? `${activeSelections[0].title.slice(0, 40)}${activeSelections[0].title.length > 40 ? '...' : ''}`
                : `${activeSelections.length} 条${activeSelections[0].type === 'news' ? '新闻' : activeSelections[0].type === 'risk' ? '风险' : activeSelections[0].type === 'insight' ? '洞察' : '报告'}`}
            </span>
            <button
              onClick={clearSelection}
              className="shrink-0 p-0.5 rounded-full hover:bg-amber-500/20 transition-colors"
              title="清除选择"
              aria-label="清除选择"
            >
              <X size={12} />
            </button>
          </span>
        </div>
      )}
      <div className="max-w-5xl mx-auto mb-2 flex items-center gap-2 text-xs">
        <span className="text-fin-muted">输出模式</span>
        <button
          type="button"
          data-testid="chat-mode-brief-btn"
          onClick={() => setOutputMode('brief')}
          disabled={isChatLoading}
          className={`px-2 py-1 rounded border transition-colors ${
            outputMode === 'brief'
              ? 'border-fin-primary text-fin-primary bg-fin-primary/10'
              : 'border-fin-border text-fin-text-secondary hover:border-fin-primary/50'
          }`}
        >
          简报
        </button>
        <button
          type="button"
          data-testid="chat-mode-deep-btn"
          onClick={() => setOutputMode('investment_report')}
          disabled={isChatLoading || !canGenerateReport}
          className={`px-2 py-1 rounded border transition-colors ${
            outputMode === 'investment_report'
              ? 'border-amber-500 text-amber-500 bg-amber-500/10'
              : 'border-fin-border text-fin-text-secondary hover:border-amber-500/50'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
          title={canGenerateReport ? '切换到深度分析模式' : '请选择标的或引用内容后启用深度分析'}
        >
          深度
        </button>
      </div>
      <div className="relative flex items-end max-w-5xl mx-auto">
        <textarea
          ref={inputRef}
          id="chat-input"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            const el = e.target;
            el.style.height = 'auto';
            el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
            el.style.overflowY = el.scrollHeight > 160 ? 'auto' : 'hidden';
          }}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything about a ticker... (e.g., AAPL price trend)"
          disabled={isChatLoading}
          aria-label="输入聊天消息"
          rows={1}
          className="w-full bg-fin-panel text-fin-text border border-fin-border rounded-xl py-3 pl-4 pr-28 focus:outline-none focus:ring-2 focus:ring-fin-primary/50 focus:border-fin-primary transition-all disabled:opacity-50 disabled:cursor-not-allowed placeholder-fin-muted resize-none overflow-y-hidden max-h-[160px]"
        />

        <div className="absolute right-2 flex items-center gap-2">
          <button
            data-testid="chat-send-btn"
            onClick={() => handleSend()}
            disabled={!input.trim() || isChatLoading}
            aria-label={outputMode === 'investment_report' ? '发送（深度分析模式）' : '发送消息'}
            className="p-2 bg-fin-primary text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title={outputMode === 'investment_report' ? '发送（深度分析模式）' : '发送'}
          >
            <SendHorizontal size={18} />
          </button>
        </div>
      </div>
      <div className="text-center mt-2">
        <p className="text-xs text-fin-muted">
          FinSight AI generated content may be inaccurate. Not financial advice.
        </p>
        <div className="mt-2 flex justify-center gap-2 text-[11px] text-fin-muted">
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('英伟达（NVDA）技术面分析：RSI、MACD、关键支撑阻力位')}
            disabled={isChatLoading}
          >
            NVDA 技术面
          </button>
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('对比 AAPL 与 MSFT：营收增长、估值水平、技术面强弱')}
            disabled={isChatLoading}
          >
            AAPL 对比 MSFT
          </button>
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => setInput('特斯拉最新关键新闻（24小时）及对股价影响解读')}
            disabled={isChatLoading}
          >
            特斯拉新闻
          </button>
          <button
            className="px-2 py-1 rounded border border-fin-border hover:border-fin-primary transition-colors"
            onClick={() => {
              setOutputMode('investment_report');
              setInput('请做 Apple 深度投资报告（deep report，filing document longform），重点引用 10-K/10-Q、业绩电话会与权威媒体来源，并给出明确结论与风险清单');
            }}
            disabled={isChatLoading}
          >
            Apple 深度研报
          </button>
        </div>
      </div>
    </div>
  );
};
