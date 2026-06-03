import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { Message, ThinkingStep, AgentLogSource } from '../types/index';
import { SendHorizontal, Paperclip, Square, X } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';

import { apiClient } from '../api/client';
import type { ChatContext } from '../api/client';
import { useStore } from '../store/useStore';
import { useExecutionStore } from '../store/executionStore';
import { useDashboardStore } from '../store/dashboardStore';
import { useToast } from './ui';
import { getAgentPreferences } from './settings/AgentControlPanel';
import { useSkillAutocomplete } from '../hooks/useSkillAutocomplete';
import { SkillAutocomplete } from './SkillAutocomplete';
import { SkillLibraryDrawer } from './SkillLibraryDrawer';
import { useAgentMention, parseAgentMentions } from '../hooks/useAgentMention';
import { AgentMention } from './AgentMention';
import { AiDisclaimer } from './common/AiDisclaimer';

const TICKER_STOPWORDS = new Set([
  'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS',
  'PE', 'EPS', 'MACD', 'RSI', 'KDJ', 'GDP', 'CPI', 'PPI', 'FOMC',
  'WITH', 'VIEW', 'FROM', 'FOR', 'OVER', 'NEWS', 'WHAT', 'WHEN', 'WHERE',
  'WHY', 'THIS', 'THAT', 'THE', 'AND', 'ARE', 'WAS', 'WERE',
]);

const MAX_AUTO_CHART_TICKERS = 3;
const TICKER_PATTERN = /^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/;
const EMPTY_RESEARCH_PROMPTS = new Set([
  'hi',
  'hello',
  'hey',
  '你好',
  '您好',
  '嗨',
  '哈喽',
  '在吗',
  '在么',
]);

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

const hasActionableResearchInput = (text: string): boolean => {
  const trimmed = text.trim();
  if (!trimmed) return false;

  const compact = trimmed.replace(/\s+/g, '').toLowerCase();
  const withoutPunctuation = compact.replace(/[?!,.，。！？、；;:：'"“”‘’()[\]{}<>《》]/g, '');
  if (!withoutPunctuation) return false;
  if (EMPTY_RESEARCH_PROMPTS.has(withoutPunctuation)) return false;
  if (!/[A-Za-z0-9\u3400-\u9FFF]/.test(trimmed)) return false;

  return withoutPunctuation.length >= 2 || TICKER_PATTERN.test(trimmed.toUpperCase());
};

const chartKeywords = ['trend', 'chart', 'kline', 'k-line', '走势', '图表', 'k线'];
// InlineChart 唯一数据源是 K 线，只能真实渲染以下类型；其余类型诚实跳过，避免错配。
const INLINE_RENDERABLE_TYPES = new Set(['line', 'candlestick', 'area']);
const INLINE_RENDERABLE_DATA_KINDS = new Set(['kline', 'technical']);

const isInlineChartRenderable = (
  chartType: string | null,
  dataKind: string | null,
): boolean => {
  if (!chartType) return false;
  if (!INLINE_RENDERABLE_TYPES.has(chartType)) return false;
  if (!dataKind) return true;
  return INLINE_RENDERABLE_DATA_KINDS.has(dataKind);
};

// SmartChart 数据路径：pie/bar 等非 kline 图表，数据来自 /api/chart/data。
// InlineChart 只有 K 线数据源，画不了这些；但 SmartChart 支持，只要能拿到 {labels, values}。
const SMARTCHART_DATA_TYPES = new Set(['pie', 'bar']);
const SMARTCHART_DATA_KINDS = new Set(['composition', 'comparison']);

// 纯函数：判断某 (chartType, dataKind) 是否应走 SmartChart 数据路径。
// 提取为纯函数便于单测（ChatInput 整体依赖 store/SSE，难以直接测）。
export const shouldUseSmartChartData = (
  chartType: string | null,
  dataKind: string | null,
): boolean => {
  if (!chartType || !dataKind) return false;
  return SMARTCHART_DATA_TYPES.has(chartType) && SMARTCHART_DATA_KINDS.has(dataKind);
};
const DEFAULT_HISTORY_LIMIT = Number(import.meta.env.VITE_CHAT_HISTORY_MAX_MESSAGES) || 12;
const STOPPED_GENERATION_MESSAGE = '已停止生成，保留已完成的结果。';

const buildCancelledThinkingStep = (): ThinkingStep => ({
  stage: 'cancelled',
  message: STOPPED_GENERATION_MESSAGE,
  timestamp: new Date().toISOString(),
  eventType: 'trace',
  result: {
    type: 'trace',
    stage: 'cancelled',
    status: 'cancelled',
    summary: STOPPED_GENERATION_MESSAGE,
  },
});

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
  if (stage === 'understanding' || stage.startsWith('trace_')) return 'router';
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
    understand_request: 18,
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
    understanding: 18,
    classifying: 8,
    classified: 15,
    planning: 12,
    executing: 72,
    synthesizing: 88,
    rendering: 95,
    done: 100,
    reference_resolution: 20,
    intent_classification: 18,
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

const explicitProgressFromStep = (step: any): number | null => {
  const raw = step?.result?.progress_percent ?? step?.result?.progress;
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
  return Math.min(100, Math.max(0, Math.round(raw)));
};

const formatExecutionStep = (stage: string, message?: string): string => {
  if (message && message.trim()) {
    return message.trim();
  }
  if (stage.startsWith('langgraph_')) {
    return stage.endsWith('_done') ? '处理完成' : '正在处理请求';
  }
  return stage.replace(/_/g, ' ');
};

interface ChatInputProps {
  onDashboardRequest?: (symbol: string) => void;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const ChatInput: React.FC<ChatInputProps> = ({ onDashboardRequest: _onDashboardRequest }) => {
  const [input, setInput] = useState('');
  const [outputMode, setOutputMode] = useState<'chat' | 'investment_report'>('chat');
  const {
    addMessageToSession,
    updateMessageInSession,
    setSessionLoading,
    isChatLoading,
    setTicker,
    setStatus,
    setExecutionState,
    resetExecutionState,
    setSessionAbortController,
    cancelChatStream,
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
  const lastSessionIdRef = useRef(sessionId);
  const [skillLibraryOpen, setSkillLibraryOpen] = useState(false);
  const skillAutocomplete = useSkillAutocomplete(input, (text: string) => {
    setInput(text);
    setDraft(text);
  });
  const agentMention = useAgentMention(input, (text: string) => {
    setInput(text);
    setDraft(text);
  });

  const shouldGenerateChart = async (
    query: string,
    currentTicker?: string | null,
  ): Promise<{
    tickers: string[];
    chartType: string | null;
    // 走 SmartChart 数据路径时携带：图表类型 / 取数方式 / 标题，供后续拉数注入 <chart> 标记。
    smartChart?: { chartType: string; dataKind: string; title: string } | null;
  }> => {
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
        const chartType = response.chart_type || 'line';
        const dataKind = typeof response.data_kind === 'string' ? response.data_kind : null;
        // 诚实原则：仅在 InlineChart 能真出图时注入 [CHART] 标记。
        if (isInlineChartRenderable(chartType, dataKind)) {
          return { tickers: merged, chartType };
        }
        // pie/bar 等非 kline 图表走 SmartChart 数据路径（后续按 data_kind 拉真实数据）。
        if (shouldUseSmartChartData(chartType, dataKind)) {
          const title = typeof response.title === 'string' && response.title.trim()
            ? response.title.trim()
            : '';
          return {
            tickers: merged,
            chartType: null,
            smartChart: { chartType, dataKind: dataKind as string, title },
          };
        }
        return { tickers: merged, chartType: null, smartChart: null };
      }
    } catch (error) {
      console.error('Chart detection failed:', error);
    }

    const lowerQuery = query.toLowerCase();
    const hasChartKeyword = chartKeywords.some((keyword) => lowerQuery.includes(keyword));
    if (!hasChartKeyword) return { tickers: [], chartType: null, smartChart: null };

    const localCandidates = extractTickers(query);
    const contextual = currentTicker ? [currentTicker] : [];
    return { tickers: mergeTickerCandidates(localCandidates, contextual), chartType: 'line', smartChart: null };
  };

  const handleSend = async () => {
    if (!input.trim() || isChatLoading) return;

    const userMsgContent = input.trim();
    // 手动选 Agent（@agent）：解析提及并从发给后端的 query 中剥离，
    // 用户消息仍显示原文；agents 经 options 透传到 ui_context.agents_override。
    const selectedAgents = parseAgentMentions(userMsgContent);
    const queryToSend = selectedAgents.length
      ? (userMsgContent.replace(/(?:^|\s)@[A-Za-z_]+/g, ' ').replace(/\s+/g, ' ').trim() || userMsgContent)
      : userMsgContent;

    // T2：模糊查询前端拦截 —— 仅当用户明确写"分析股票/帮我分析"等模糊动词，
    //      且 query 里既没有英文 ticker / 中文公司名 / 数字代码 / 已选股票时，
    //      直接给出澄清提示，避免把 active_symbol 误绑成上次的标的。
    const guessedTickerForGuard = extractTicker(userMsgContent);
    const hasContextSelection = Boolean(currentTicker);
    const isFuzzyAnalyze = (() => {
      const q = userMsgContent.replace(/\s+/g, '');
      // 触发词：纯模糊动词，不带任何标的线索
      const fuzzyPatterns = [
        /^帮我分析(一下)?(股票|股价|公司|这个|这只|个股)?[？?！!。.]?$/,
        /^分析(一下)?(股票|股价|公司|这个|这只|个股)$/,
        /^(看看|分析下|帮看下)$/,
        /^分析影响[？?！!。.]?$/,
      ];
      return fuzzyPatterns.some((p) => p.test(q));
    })();

    if (isFuzzyAnalyze && !guessedTickerForGuard && !hasContextSelection) {
      const activeSessionId = sessionId || useStore.getState().sessionId;
      addMessageToSession(activeSessionId, {
        id: uuidv4(),
        role: 'user',
        content: userMsgContent,
        timestamp: Date.now(),
      });
      addMessageToSession(activeSessionId, {
        id: uuidv4(),
        role: 'assistant',
        content:
          '请告诉我具体要分析哪只股票或公司，例如：\n' +
          '• 输入股票代码：`AAPL`、`TSLA`、`600036`\n' +
          '• 输入公司名：`苹果`、`特斯拉`、`招商银行`\n' +
          '• 或直接说："分析苹果最近的股价走势"',
        timestamp: Date.now(),
      });
      setInput('');
      setDraft('');
      if (inputRef.current) {
        inputRef.current.style.height = 'auto';
        inputRef.current.style.overflowY = 'hidden';
      }
      return;
    }

    const guessedTicker = guessedTickerForGuard;
    if (guessedTicker) {
      setTicker(guessedTicker);
    }
    const requestSessionId = sessionId || useStore.getState().sessionId;
    const isRequestSessionActive = () => useStore.getState().sessionId === requestSessionId;
    const updateScopedMessage = (id: string, patch: Partial<Message>) => {
      updateMessageInSession(requestSessionId, id, patch);
    };
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

    addMessageToSession(requestSessionId, {
      id: uuidv4(),
      role: 'user',
      content: userMsgContent,
      timestamp: Date.now(),
    });

    const aiMsgId = uuidv4();
    addMessageToSession(requestSessionId, {
      id: aiMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isLoading: true,
    });

    setSessionLoading(requestSessionId, true);
    if (isRequestSessionActive()) {
      setStatus('Streaming response...');
      setExecutionState('Preparing request', 0);
    }
    const streamController = new AbortController();
    setSessionAbortController(requestSessionId, streamController);

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
    // 接通底部执行指挥台（executionStore）：runId 取自首个携带 run_id 的 SSE 事件
    let execRunId: string | null = null;

    const requestStartedAt = Date.now();

    const recoverReportIfAvailable = async (): Promise<boolean> => {
      const session = requestSessionId;
      if (!session) return false;
      try {
        const index = await apiClient.listReportIndex({
          sessionId: session,
          limit: 1,
          includeBlocked: true,
        });
        const latest = index.items?.[0];
        if (!latest?.report_id) return false;

        const ts = latest.generated_at || latest.created_at || latest.updated_at || '';
        if (ts) {
          const parsed = Date.parse(ts);
          if (Number.isFinite(parsed) && parsed + 120000 < requestStartedAt) {
            return false;
          }
        }

        const replay = await apiClient.getReportReplay({
          sessionId: session,
          reportId: latest.report_id,
          includeBlocked: true,
        });
        if (!replay?.report) return false;

        updateScopedMessage(aiMsgId, {
          content: replay.report.summary || fullContent || 'Report recovered after stream interruption.',
          isLoading: false,
          report: replay.report,
          evidence_pool: replay.citations,
        });
        if (isRequestSessionActive()) {
          setExecutionState('Recovered report', 100);
          setStatus(null);
        }
        toast({
          type: 'success',
          title: '已恢复报告',
          message: '流式连接中断后已从后端取回报告',
        });
        return true;
      } catch {
        return false;
      }
    };

    const finishAbortedStream = () => {
      if (!thinkingSteps.some((step) => step.stage === 'cancelled')) {
        thinkingSteps = [...thinkingSteps, buildCancelledThinkingStep()];
      }
      updateScopedMessage(aiMsgId, {
        content: fullContent || STOPPED_GENERATION_MESSAGE,
        isLoading: false,
        thinking: thinkingSteps,
      });
      if (isRequestSessionActive()) {
        setStatus(STOPPED_GENERATION_MESSAGE);
        setExecutionState('已停止生成', useStore.getState().executionProgress ?? null);
      }
      addAgentLog({
        id: uuidv4(),
        timestamp: new Date().toISOString(),
        source: 'system',
        level: 'warn',
        message: STOPPED_GENERATION_MESSAGE,
      });
      updateAgentStatus('supervisor', {
        status: 'waiting',
        endTime: new Date().toISOString(),
        lastMessage: STOPPED_GENERATION_MESSAGE,
      });
      if (execRunId) {
        useExecutionStore.getState().completeExternalExecution({
          runId: execRunId,
          status: 'cancelled',
        });
      }
    };

    try {
      const agentPreferences = getAgentPreferences();
      await apiClient.sendMessageStream(
        queryToSend,
        (token) => {
          const safeToken = typeof token === 'string' ? token : JSON.stringify(token);
          if (safeToken) {
            fullContent += safeToken;
            if (execRunId) useExecutionStore.getState().ingestExternalToken(execRunId, safeToken);
          }
          updateScopedMessage(aiMsgId, { content: fullContent, isLoading: true });
        },
        (name) => {
          const current = useStore.getState().executionProgress ?? 0;
          if (isRequestSessionActive()) {
            setStatus(`Calling tool: ${name}...`);
            setExecutionState(`Tool: ${name}`, Math.max(current, 72));
          }
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
          const current = useStore.getState().executionProgress ?? 0;
          if (isRequestSessionActive()) {
            setStatus('Generating response...');
            setExecutionState('Synthesizing response', Math.max(current, 80));
          }
          addAgentLog({
            id: uuidv4(),
            timestamp: new Date().toISOString(),
            source: 'system',
            level: 'success',
            message: 'Tool execution completed',
          });
        },
        async (report?: any, thinking?: ThinkingStep[], meta?: any) => {
          const doneStep: ThinkingStep = {
            stage: 'done',
            message: meta?.synthetic_done ? '已根据流式输出自动完成' : '分析完成',
            timestamp: new Date().toISOString(),
            eventType: 'done',
            result: {
              type: 'done',
              status: 'done',
              synthetic_done: Boolean(meta?.synthetic_done),
              reason: meta?.reason,
            },
          };
          thinkingSteps = [...thinkingSteps, doneStep];

          const metrics = meta?.metrics || {};
          if (metrics && typeof metrics === 'object') {
            setRequestMetrics({
              llmTotalCalls: Number(metrics.llm_total_calls || 0),
              toolTotalCalls: Number(metrics.tool_total_calls || 0),
              updatedAt: new Date().toISOString(),
            });
          }

          if (isRequestSessionActive() && typeof meta?.session_id === 'string' && meta.session_id.trim() && meta.session_id !== requestSessionId) {
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
          } else if (chartInfo.smartChart && !forceMulti) {
            // SmartChart 数据路径（pie/bar）：按 data_kind 拉真实数据，成功才注入 <chart> 标记。
            // 时机与 [CHART:...] 一致——收到回复后追加到消息内容，由 ChatList 的 parseSmartChartBlocks 渲染。
            const smartTicker = tickers[0] || nextFocus || currentTicker || null;
            if (smartTicker && !/<chart\s+/i.test(fullContent)) {
              try {
                const { chartType, dataKind, title } = chartInfo.smartChart;
                const result = await apiClient.getChartData(smartTicker, dataKind);
                if (result?.success && result.data && Array.isArray(result.data.values) && result.data.values.length > 0) {
                  const safeTitle = (title || `${smartTicker} 图表`).replace(/"/g, '');
                  fullContent += `\n\n<chart type="${chartType}" title="${safeTitle}">${JSON.stringify(result.data)}</chart>`;
                  setTicker(smartTicker);
                }
                // 失败 / 无数据：诚实跳过，不出图（与现有 InlineChart 跳过行为一致）。
              } catch (chartErr) {
                console.error('SmartChart data fetch failed:', chartErr);
              }
            }
          }

          updateScopedMessage(aiMsgId, {
            content: fullContent,
            isLoading: false,
            report,
            thinking: thinkingSteps,
            evidence_pool: evidencePool,
          });
          if (execRunId) {
            useExecutionStore.getState().completeExternalExecution({
              runId: execRunId,
              status: 'done',
              report: report ?? null,
              meta,
            });
          }
          if (isRequestSessionActive()) {
            setExecutionState('Completed', 100);
            setStatus(null);
          }
        },
        (error) => {
          const handleFailure = async () => {
            const recovered = await recoverReportIfAvailable();
            if (recovered) return;

            updateScopedMessage(aiMsgId, { content: `Error: ${error}`, isLoading: false });
            if (isRequestSessionActive()) {
              setStatus('Stream interrupted');
            }
            toast({
              type: 'error',
              title: '流式连接中断',
              message: '连接被中断或服务暂不可用，请重试',
            });
            const current = useStore.getState().executionProgress ?? 0;
            if (isRequestSessionActive()) {
              setExecutionState('Execution failed', current);
            }
            addAgentLog({
              id: uuidv4(),
              timestamp: new Date().toISOString(),
              source: 'system',
              level: 'error',
              message: `Error: ${error}`,
            });
            updateAgentStatus('supervisor', { status: 'error', lastMessage: error });
            if (execRunId) {
              useExecutionStore.getState().completeExternalExecution({
                runId: execRunId,
                status: 'error',
                error: String(error),
              });
            }
          };

          void handleFailure();
        },
        (step) => {
          // 接通底部指挥台：把同一条 SSE 事件喂给 executionStore（step.result 即原始 payload，
          // 内部 pipelineReducer 自动解析 plan/step/agent/decision/stage）
          const stepRunId = (typeof step.runId === 'string' && step.runId)
            || (step.result && typeof (step.result as Record<string, unknown>).run_id === 'string'
              ? (step.result as Record<string, string>).run_id
              : null);
          if (stepRunId) {
            const execStore = useExecutionStore.getState();
            if (execRunId !== stepRunId) {
              execRunId = stepRunId;
              execStore.beginExternalExecution({
                runId: stepRunId,
                query: userMsgContent,
                tickers: extractTickers(userMsgContent),
                source: 'chat',
                outputMode: effectiveOutputMode,
              });
            }
            execStore.ingestExternalThinking(stepRunId, step);
          }
          thinkingSteps = [...thinkingSteps, step];
          updateScopedMessage(aiMsgId, { thinking: thinkingSteps });
          const current = useStore.getState().executionProgress ?? 0;
          const explicitProgress = explicitProgressFromStep(step);
          const progress = explicitProgress ?? estimateProgress(step.stage, current);
          const stepLabel = formatExecutionStep(step.stage, step.message);
          if (isRequestSessionActive()) {
            setExecutionState(stepLabel, progress);
          }

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
              agent_preferences: agentPreferences,
              agents: selectedAgents.length ? selectedAgents : undefined,
            }
          : {
              output_mode: 'chat',
              confirmation_mode: 'skip' as const,
              trace_raw_override: traceRawEnabled ? 'on' : 'off',
              agent_preferences: agentPreferences,
              agents: selectedAgents.length ? selectedAgents : undefined,
            },
        requestSessionId || undefined,
        traceRawEnabled,
        { signal: streamController.signal },
      );
      if (streamController.signal.aborted) {
        finishAbortedStream();
      }
    } catch (error) {
      if (streamController.signal.aborted) {
        finishAbortedStream();
        return;
      }
      updateScopedMessage(aiMsgId, {
        content: 'Network request failed. Please confirm the backend service is running.',
        isLoading: false,
      });
      if (isRequestSessionActive()) {
        setStatus('Request failed');
      }
      toast({
        type: 'error',
        title: '请求失败',
        message: '网络异常或服务不可用，请稍后重试',
      });
      const current = useStore.getState().executionProgress ?? 0;
      if (isRequestSessionActive()) {
        setExecutionState('Request failed', current);
      }
      addAgentLog({
        id: uuidv4(),
        timestamp: new Date().toISOString(),
        source: 'system',
        level: 'error',
        message: error instanceof Error ? error.message : 'Network request failed',
      });
    } finally {
      const wasAborted = streamController.signal.aborted;
      setSessionLoading(requestSessionId, false);
      if (isRequestSessionActive()) {
        if (wasAborted) {
          setStatus(STOPPED_GENERATION_MESSAGE);
          setExecutionState('已停止生成', useStore.getState().executionProgress ?? null);
        } else {
          setStatus(null);
          resetExecutionState();
        }
      }
      setSessionAbortController(requestSessionId, null);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  };

  useEffect(() => {
    setInput(draft || '');
    if (draft && inputRef.current) {
      inputRef.current.focus();
    }
  }, [draft]);

  useEffect(() => {
    if (lastSessionIdRef.current !== sessionId) {
      lastSessionIdRef.current = sessionId;
      const nextDraft = useStore.getState().draft || '';
      setInput(nextDraft);
    }
    setOutputMode('chat');
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.overflowY = 'hidden';
    }
  }, [sessionId]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (skillAutocomplete.handleKeyDown(e)) return;
    if (agentMention.handleKeyDown(e)) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canGenerateReport = Boolean(
    activeAsset?.symbol
    || currentTicker
    || activeSelections.length > 0
    || hasActionableResearchInput(input)
  );

  useEffect(() => {
    if (!canGenerateReport && outputMode === 'investment_report') {
      setOutputMode('chat');
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
      <div className="max-w-5xl mx-auto mb-2 flex items-center justify-end gap-2 text-xs">
        <button
          type="button"
          data-testid="chat-report-toggle-btn"
          onClick={() => setOutputMode(outputMode === 'investment_report' ? 'chat' : 'investment_report')}
          disabled={isChatLoading || !canGenerateReport}
          className={`px-2 py-1 rounded border transition-colors ${
            outputMode === 'investment_report'
              ? 'border-amber-500 text-amber-500 bg-amber-500/10'
              : 'border-fin-border text-fin-text-secondary hover:border-amber-500/50'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
          title={canGenerateReport ? '生成结构化长报告' : '输入可研究的问题、选择标的或引用内容后启用报告'}
        >
          报告
        </button>
      </div>
      <div className="relative flex items-end max-w-5xl mx-auto">
        {skillAutocomplete.isOpen && (
          <SkillAutocomplete
            skills={skillAutocomplete.filteredSkills}
            selectedIndex={skillAutocomplete.selectedIndex}
            onSelect={skillAutocomplete.selectSkill}
            onOpenLibrary={() => setSkillLibraryOpen(true)}
          />
        )}
        {agentMention.isOpen && (
          <AgentMention
            agents={agentMention.filteredAgents}
            selectedIndex={agentMention.selectedIndex}
            onSelect={agentMention.selectAgent}
          />
        )}
        <textarea
          ref={inputRef}
          id="chat-input"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setDraft(e.target.value);
            const el = e.target;
            el.style.height = 'auto';
            el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
            el.style.overflowY = el.scrollHeight > 160 ? 'auto' : 'hidden';
          }}
          onKeyDown={handleKeyDown}
          placeholder="Ask about markets, macro, themes, or a ticker... (e.g., AAPL price trend)"
          disabled={isChatLoading}
          aria-label="输入聊天消息"
          rows={1}
          /* 移动端触摸目标：min-h-[44px] 确保输入框可点击区域 ≥44px */
          className="w-full bg-fin-panel text-fin-text border border-fin-border rounded-xl py-3 pl-4 pr-28 focus:outline-none focus:ring-2 focus:ring-fin-primary/50 focus:border-fin-primary transition-all disabled:opacity-50 disabled:cursor-not-allowed placeholder-fin-muted resize-none overflow-y-hidden min-h-[44px] max-h-[160px]"
        />

        <div className="absolute right-2 flex items-center gap-2">
          {isChatLoading ? (
            <button
              data-testid="chat-stop-btn"
              onClick={cancelChatStream}
              aria-label="停止生成"
              /* 移动端触摸目标：max-lg 下放大到 44px 满足可点击区域 */
              className="p-2 max-lg:min-h-[44px] max-lg:min-w-[44px] flex items-center justify-center bg-fin-danger text-white rounded-lg hover:bg-red-600 transition-colors"
              title="停止生成"
            >
              <Square size={16} fill="currentColor" />
            </button>
          ) : (
            <button
              data-testid="chat-send-btn"
              onClick={() => handleSend()}
              disabled={!input.trim()}
              aria-label={outputMode === 'investment_report' ? '发送并生成报告' : '发送消息'}
              /* 移动端触摸目标：max-lg 下放大到 44px 满足可点击区域 */
              className="p-2 max-lg:min-h-[44px] max-lg:min-w-[44px] flex items-center justify-center bg-fin-primary text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title={outputMode === 'investment_report' ? '发送并生成报告' : '发送'}
            >
              <SendHorizontal size={18} />
            </button>
          )}
        </div>
      </div>
      <SkillLibraryDrawer
        open={skillLibraryOpen}
        onClose={() => setSkillLibraryOpen(false)}
        onSelectSkill={(text) => {
          setInput(text);
          setDraft(text);
          inputRef.current?.focus();
        }}
      />
      <div className="text-center mt-2">
        <AiDisclaimer variant="compact" />
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
