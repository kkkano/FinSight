import type { RawSSEEvent, TraceViewMode } from '../../types';

// Event type color/label configuration
export const EVENT_TYPE_CONFIG: Record<string, { color: string; bg: string; label: string; icon: string }> = {
  token:            { color: 'text-fin-muted',   bg: 'bg-fin-muted/10',  label: 'TKN',  icon: '\u25b8' },
  thinking:         { color: 'text-cyan-400',   bg: 'bg-cyan-500/10',   label: 'THINK', icon: '\u25c8' },
  tool_start:       { color: 'text-amber-400',  bg: 'bg-amber-500/10',  label: 'TOOL\u25b6', icon: '\u2699' },
  tool_end:         { color: 'text-amber-300',  bg: 'bg-amber-500/10',  label: 'TOOL\u25a0', icon: '\u2713' },
  tool_call:        { color: 'text-orange-400', bg: 'bg-orange-500/10', label: 'CALL',  icon: '\u26a1' },
  llm_call:         { color: 'text-purple-400', bg: 'bg-purple-500/10', label: 'LLM',   icon: '\ud83e\udde0' },
  llm_start:        { color: 'text-purple-400', bg: 'bg-purple-500/10', label: 'LLM\u25b6',  icon: '\ud83e\udde0' },
  llm_end:          { color: 'text-purple-300', bg: 'bg-purple-500/10', label: 'LLM\u25a0',  icon: '\ud83e\udde0' },
  cache_hit:        { color: 'text-emerald-400',bg: 'bg-emerald-500/10',label: 'CACHE\u2713',icon: '\ud83d\udce6' },
  cache_miss:       { color: 'text-yellow-400', bg: 'bg-yellow-500/10', label: 'CACHE\u2717',icon: '\ud83d\udce6' },
  cache_set:        { color: 'text-emerald-300',bg: 'bg-emerald-500/10',label: 'CACHE+',icon: '\ud83d\udce6' },
  data_source:      { color: 'text-sky-400',    bg: 'bg-sky-500/10',    label: 'DATA',  icon: '\ud83d\udcca' },
  api_call:         { color: 'text-pink-400',   bg: 'bg-pink-500/10',   label: 'API',   icon: '\ud83c\udf10' },
  agent_step:       { color: 'text-teal-400',   bg: 'bg-teal-500/10',   label: 'STEP',  icon: '\u25c8' },
  step_done:        { color: 'text-green-300',  bg: 'bg-green-500/10',  label: 'STEP\u2713', icon: '\u2713' },
  step_start:       { color: 'text-teal-400',   bg: 'bg-teal-500/10',   label: 'STEP\u25b6', icon: '\u25b6' },
  step_error:       { color: 'text-red-400',    bg: 'bg-red-500/10',    label: 'STEP\u2717', icon: '\u2717' },
  plan_ready:       { color: 'text-violet-400',  bg: 'bg-violet-500/10', label: 'PLAN',  icon: '\ud83d\udccb' },
  system:           { color: 'text-slate-400',  bg: 'bg-slate-500/10',  label: 'SYS',   icon: '\u2699' },
  done:             { color: 'text-green-400',  bg: 'bg-green-500/10',  label: 'DONE',  icon: '\u2705' },
  error:            { color: 'text-red-400',    bg: 'bg-red-500/10',    label: 'ERR',   icon: '\u2717' },
  supervisor_start: { color: 'text-blue-400',   bg: 'bg-blue-500/10',   label: 'SUP\u25b6',  icon: '\u25b6' },
  agent_start:      { color: 'text-teal-400',   bg: 'bg-teal-500/10',   label: 'AGT\u25b6',  icon: '\u25b6' },
  agent_done:       { color: 'text-teal-300',   bg: 'bg-teal-500/10',   label: 'AGT\u25a0',  icon: '\u25a0' },
  agent_error:      { color: 'text-red-400',    bg: 'bg-red-500/10',    label: 'AGT\u2717',  icon: '\u2717' },
  forum_start:      { color: 'text-indigo-400', bg: 'bg-indigo-500/10', label: 'FRM\u25b6',  icon: '\u25b6' },
  forum_done:       { color: 'text-indigo-300', bg: 'bg-indigo-500/10', label: 'FRM\u25a0',  icon: '\u25a0' },
  any:              { color: 'text-fin-muted',  bg: 'bg-fin-muted/10',  label: 'UNK',   icon: '?' },
};

// Format timestamp with millisecond precision
export const formatTs = (ts: string): string => {
  try {
    const d = new Date(ts);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    const ms = String(d.getMilliseconds()).padStart(3, '0');
    return `${h}:${m}:${s}.${ms}`;
  } catch {
    return ts;
  }
};

// Format byte size to human-readable string
export const formatSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
};

// --- Action / Reason / Result helpers ---

type ActionReasonResult = {
  action: string;
  reason: string;
  result: string;
};

const toActionReasonResult = (event: RawSSEEvent): ActionReasonResult => {
  const data = event.parsedData || {};
  switch (event.eventType) {
    case 'thinking': {
      const stage = String(data.stage || 'thinking');
      const action = stage;
      const reason = String(
        data.message ||
          data.result?.summary ||
          data.result?.decision_summary ||
          data.result?.decision_type ||
          'no_reason',
      );
      const result = String(
        data.result?.status_reason ||
          data.result?.selection_summary ||
          data.result?.fallback_reason ||
          data.result?.input_state ||
          'in_progress',
      );
      return { action, reason, result };
    }
    case 'tool_start':
      return {
        action: `tool:${String(data.name || 'any')}`,
        reason: String(data.message || 'executor_requested_tool'),
        result: 'running',
      };
    case 'tool_end':
      return {
        action: `tool:${String(data.name || 'any')}`,
        reason: String(data.message || 'tool_finished'),
        result: String(data.success === false ? 'error' : 'done'),
      };
    case 'llm_start':
      return {
        action: `llm:${String(data.model || 'any')}`,
        reason: String(data.message || 'planner_or_synthesizer_requested'),
        result: 'running',
      };
    case 'llm_end':
      return {
        action: `llm:${String(data.model || 'any')}`,
        reason: String(data.error || data.message || 'llm_completed'),
        result: String(data.success === false ? 'error' : 'done'),
      };
    case 'error':
      return {
        action: 'pipeline:error',
        reason: String(data.message || 'unknown_error'),
        result: 'error',
      };
    case 'done':
      return {
        action: 'pipeline:done',
        reason: String(data.intent || 'response_ready'),
        result: 'done',
      };
    default:
      return {
        action: event.eventType,
        reason: String(data.message || data.stage || 'n/a'),
        result: String(data.status || 'ok'),
      };
  }
};

const formatActionReasonResult = (event: RawSSEEvent): string => {
  const parts = toActionReasonResult(event);
  return `\u52a8\u4f5c:${parts.action} \uff5c \u539f\u56e0:${parts.reason} \uff5c \u7ed3\u679c:${parts.result}`;
};

// Get event summary string (developer/raw view)
export const getEventSummary = (event: RawSSEEvent): string => {
  const data = event.parsedData;
  switch (event.eventType) {
    case 'token':
      return `"${(data.content || '').slice(0, 80)}${(data.content || '').length > 80 ? '...' : ''}"`;
    case 'thinking':
      return formatActionReasonResult(event).slice(0, 180);
    case 'tool_start':
      return formatActionReasonResult(event);
    case 'tool_end':
      return formatActionReasonResult(event);
    case 'tool_call': {
      const toolName = data.name || '?';
      const input = data.input;
      const inputIsEmptyObject = input && typeof input === 'object' && !Array.isArray(input) && Object.keys(input).length === 0;
      if (!input || inputIsEmptyObject) {
        return `${toolName}()`;
      }
      return `${toolName}(${JSON.stringify(input).slice(0, 80)})`;
    }
    case 'llm_call':
      return `model=${data.model || '?'} tokens=${data.tokens || '?'}`;
    case 'llm_start':
      return formatActionReasonResult(event);
    case 'llm_end':
      return formatActionReasonResult(event);
    case 'cache_hit':
      return `\ud83d\udce6 \u7f13\u5b58\u547d\u4e2d: ${data.key || '?'}`;
    case 'cache_miss':
      return `\ud83d\udce6 \u7f13\u5b58\u672a\u547d\u4e2d: ${data.key || '?'}`;
    case 'cache_set':
      return `\ud83d\udce6 \u7f13\u5b58\u5199\u5165: ${data.key || '?'}${data.ttl ? ` (TTL: ${data.ttl}s)` : ''}`;
    case 'data_source':
      {
        const dsStatus = data.success ? '\u2713' : '\u2717';
        const dsFallback = data.fallback ? ' [\u56de\u9000]' : '';
        const dsDuration = data.duration_ms ? ` [${data.duration_ms}ms]` : '';
        const triedSources = Array.isArray(data.tried_sources)
          ? data.tried_sources.filter((item: unknown) => typeof item === 'string' && item.trim().length > 0)
          : [];
        const fallbackPath = triedSources.length > 0 ? ` [\u8def\u5f84:${triedSources.join(' -> ')}]` : '';
        return `\ud83d\udcca ${data.source || '?'}: ${data.query_type || '?'}${data.ticker ? ` (${data.ticker})` : ''} ${dsStatus}${dsFallback}${dsDuration}${fallbackPath}`;
      }
    case 'api_call':
      {
        const apiStatus = data.status ? ` \u2192 ${data.status}` : '';
        const apiDuration = data.duration_ms ? ` [${data.duration_ms}ms]` : '';
        return `\ud83c\udf10 ${data.method || 'GET'} ${data.endpoint || '?'}${apiStatus}${apiDuration}`;
      }
    case 'agent_step':
      return `\u25c8 ${data.agent || '?'}: ${data.step || '?'}`;
    case 'system':
      return data.message || 'System event';
    case 'done':
      return `report=${!!data.report} thinking_steps=${(data.thinking || []).length}`;
    case 'error':
      return data.message || 'Unknown error';
    case 'supervisor_start':
      return `Supervisor started \u2192 agents: ${JSON.stringify(data.agents || [])}`;
    case 'agent_start':
      return `${data.agent || '?'} Agent started${data.query ? ` - ${data.query.slice(0, 50)}...` : ''}`;
    case 'agent_done':
      {
        const agentDuration = data.duration_ms ? ` [${data.duration_ms}ms]` : '';
        return `${data.agent || '?'} Agent completed${agentDuration}`;
      }
    case 'agent_error':
      return `${data.agent || '?'} Agent error: ${data.message || ''}`;
    case 'forum_start':
      return 'Forum synthesis started';
    case 'forum_done':
      return 'Forum synthesis completed';
    case 'step_start':
      return `${data.kind || 'step'}:${data.name || '?'} started (${data.step_id || '?'})`;
    case 'step_error':
      return `${data.kind || 'step'}:${data.name || '?'} error: ${data.error || data.message || '?'}`;
    case 'plan_ready':
      return `Plan ready: ${data.step_count || '?'} steps, agents=[${(data.agents || []).join(', ')}]`;
    case 'step_done':
      return `${data.kind || 'step'}:${data.name || '?'} done (${data.step_id || '?'})`;
    default:
      if (data.message) return data.message.slice(0, 120);
      return JSON.stringify(data).slice(0, 100);
  }
};

// Get event summary by view mode (user / expert / dev)
export const getEventSummaryByMode = (event: RawSSEEvent, mode: TraceViewMode): string => {
  if (mode === 'user') {
    const data = event.parsedData || {};
    if (event.eventType === 'thinking') {
      return String(data.message || data.result?.summary || data.result?.decision_type || '\u5904\u7406\u4e2d').slice(0, 160);
    }
    if (event.eventType === 'error') {
      return String(data.message || '\u53d1\u751f\u9519\u8bef').slice(0, 160);
    }
    if (event.eventType === 'done') {
      return '\u5206\u6790\u5b8c\u6210';
    }
    if (event.eventType === 'data_source') {
      return `\u6570\u636e\u6e90: ${String(data.source || '?')}${data.fallback ? '\uff08\u542b\u56de\u9000\uff09' : ''}`;
    }
    return getEventSummary(event);
  }

  if (mode === 'expert') {
    const data = event.parsedData || {};
    if (event.eventType === 'thinking') {
      const decisionType = data.result?.decision_type ? ` type=${data.result.decision_type}` : '';
      const summary = data.result?.summary || data.message || data.result?.decision_summary || 'n/a';
      return `${summary}${decisionType}`.slice(0, 180);
    }
    return getEventSummary(event);
  }

  return getEventSummary(event);
};

// Event stats shape
export interface EventStats {
  total: number;
  totalBytes: number;
  typeCounts: Record<string, number>;
  filtered: number;
}
