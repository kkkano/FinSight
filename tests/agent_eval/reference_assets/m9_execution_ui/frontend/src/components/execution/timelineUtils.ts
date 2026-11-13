import type { TimelineEvent } from '../../types/execution';

function getRawValue(event: TimelineEvent, key: string): string {
  const raw = event.raw as Record<string, unknown> | undefined;
  const value = raw?.[key];
  return typeof value === 'string' ? value : '';
}

function getSubject(event: TimelineEvent): string {
  return event.agent || event.tool || event.name || event.stepId || event.kind || '系统';
}

const SUBJECT_LABELS: Record<string, string> = {
  get_stock_price: '获取行情',
  get_stock_price_market: '获取行情',
  analyze_historical_drawdowns: '分析历史回撤',
  get_factor_exposure: '分析因子暴露',
  get_technical_snapshot: '计算技术指标',
  get_option_chain_metrics: '分析期权信号',
  price: '价格分析',
  technical: '技术分析',
  risk: '风险分析',
  fundamental: '基本面分析',
  news: '新闻分析',
  macro: '宏观分析',
  deep_search: '深度检索',
  planning: '规划',
  executing: '执行',
  synthesizing: '综合分析',
  rendering: '生成回答',
  done: '完成',
};

export function executionSubjectLabel(subject: string): string {
  return SUBJECT_LABELS[subject.replace(/_agent$/, '')] ?? subject;
}

export function formatTimelineTime(iso?: string): string {
  if (!iso) return '--:--:--';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function summarizeTimelineEvent(event: TimelineEvent): string {
  if (event.userMessage?.trim()) return event.userMessage.trim();
  if (event.message && event.message.trim()) return event.message.trim();

  const subject = getSubject(event);
  const method = getRawValue(event, 'method');
  const endpoint = getRawValue(event, 'endpoint');
  const source = getRawValue(event, 'source');
  const queryType = getRawValue(event, 'query_type');
  const cacheKey = getRawValue(event, 'key');
  const step = getRawValue(event, 'step');

  switch (event.eventType) {
    case 'step_start':
      return `[步骤] ${subject} 开始`;
    case 'step_done':
      return `[步骤] ${subject} 完成${event.cached ? '（缓存）' : event.skipped ? '（跳过）' : ''}`;
    case 'step_error':
      return `[步骤] ${subject} 失败`;
    case 'tool_call':
      return `[工具] ${subject} 已发起调用`;
    case 'tool_start':
      return `[工具] ${subject} 开始执行`;
    case 'tool_end':
      return `[工具] ${subject} 执行完成`;
    case 'agent_start':
      return `[Agent] ${subject} 开始`;
    case 'agent_step':
      return `[Agent] ${event.agent || subject} ${step || '处理中'}`;
    case 'agent_done':
      return `[Agent] ${subject} 完成`;
    case 'agent_error':
      return `[Agent] ${subject} 失败`;
    case 'supervisor_start':
      return '[调度] Supervisor 开始';
    case 'forum_start':
      return '[协作] Forum 开始';
    case 'forum_done':
      return '[协作] Forum 完成';
    case 'cache_hit':
      return `[缓存] 命中 ${cacheKey || subject}`;
    case 'cache_miss':
      return `[缓存] 未命中 ${cacheKey || subject}`;
    case 'cache_set':
      return `[缓存] 写入 ${cacheKey || subject}`;
    case 'api_call':
      return `[API] ${method || 'GET'} ${endpoint || subject}`.trim();
    case 'data_source':
      return `[数据源] ${source || subject}${queryType ? ` · ${queryType}` : ''}`;
    case 'plan_ready':
      return '[计划] 执行计划已生成';
    case 'system':
      return `[系统] ${subject}`;
    case 'error':
      return '[系统] 执行出错';
    default:
      if (event.stage && event.stage !== event.eventType) {
        return `[${event.stage}] ${subject}`;
      }
      return `[事件] ${event.eventType || 'unknown'}`;
  }
}

export function isTimelineError(event: TimelineEvent): boolean {
  return (
    event.eventType === 'error'
    || event.eventType === 'agent_error'
    || event.eventType === 'step_error'
    || event.stage === 'error'
    || event.status === 'error'
    || event.status === 'failed'
  );
}
