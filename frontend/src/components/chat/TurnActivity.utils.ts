import type { ThinkingStep } from '../../types';
import type { RuntimeActivityDetails } from '../../types/runtime';
import { getAgentDisplayName } from '../../utils/userMessageMapper';
import { sourceDisplayName, sourceTitleDisplayName } from '../../utils/sourceDisplayName';
import { TOOL_ACTIVITY_LABELS as labels } from '../../utils/toolLabels';
import { zh } from '../../locales/zh';

export type Activity = {
  id: string; name: string; label: string; agent?: string; summary: string; target: string; seq?: number;
  status: 'running' | 'done' | 'error' | 'cancelled' | 'partial';
  kind: 'tool' | 'agent' | 'work'; details: RuntimeActivityDetails; timestamp: string; duration?: number;
};

export const text = (value: unknown) => typeof value === 'string' ? value : '';

export const fieldLabels: Record<string, string> = {
  ticker: '标的', symbol: '代码', query: '查询', task: '研究任务', role: '研究角色',
  period: '期间', start_date: '起始日期', end_date: '结束日期', limit: '数量上限',
  name: '名称', title: '标题', description: '说明', summary: '摘要', status: '状态',
  source: '来源', sources: '来源', provider: '服务来源', data_source: '数据来源', tool: '工具', tool_name: '工具', url: '链接', as_of: '数据时间', date: '日期',
  price: '价格', currency: '货币', value: '数值', unit: '单位', result_count: '结果数量',
  data: '数据', result: '结果', rows: '数据行', enabled: '已启用', tools: '工具',
  data_ref: '相关数据', data_refs: '相关数据', source_refs: '相关来源', evidence_refs: '相关资料',
  error: '错误', error_code: '错误代码', reason: '原因', limitations: '限制',
  content: '原文片段', headline: '标题', snippet: '摘要', published_at: '发布时间', published_date: '发布时间',
  preview: '资料摘要',
  max_chars: '读取长度', offset: '起始位置', next_offset: '后续位置', total_chars: '原文长度', has_more: '还有后续内容',
};

const sensitiveKey = /(?:api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token|cookie|credential)/i;

export const previewValue = (value: unknown, depth = 0): unknown => {
  if (typeof value === 'string') return value.slice(0, 2400);
  if (value == null || typeof value !== 'object') return value;
  if (depth >= 5) return zh.chat.detailsDepthLimited;
  if (Array.isArray(value)) return value.slice(0, 30).map((item) => previewValue(item, depth + 1));
  return Object.fromEntries(Object.entries(value).filter(([key]) => !sensitiveKey.test(key)).slice(0, 40)
    .map(([key, item]) => [key, previewValue(item, depth + 1)]));
};

const activityDetails = (data: Record<string, unknown>): RuntimeActivityDetails => {
  const selected: RuntimeActivityDetails = {};
  for (const key of ['inputs', 'output_preview', 'sources', 'source_refs', 'data_refs', 'evidence_refs', 'limitations'] as const) {
    if (data[key] !== undefined) selected[key] = previewValue(data[key]);
  }
  if (!selected.sources && data.source) selected.sources = previewValue(data.source);
  for (const key of ['reason', 'error_code', 'recovery_action', 'role', 'task'] as const) {
    if (text(data[key])) selected[key] = text(data[key]).slice(0, 2400);
  }
  if (!selected.reason && text(data.error)) selected.reason = text(data.error).slice(0, 1600);
  if (data.display && typeof data.display === 'object') {
    const display = data.display as Record<string, unknown>;
    selected.display = { target: text(display.target), result: text(display.result), title: text(display.title),
      kind: display.kind as NonNullable<RuntimeActivityDetails['display']>['kind'],
      status: display.status as NonNullable<RuntimeActivityDetails['display']>['status'],
      key_facts: Array.isArray(display.key_facts) ? display.key_facts.flatMap((fact) => fact && typeof fact === 'object'
        && typeof fact.label === 'string' ? [{ label: fact.label, value: previewValue(fact.value) }] : []) : undefined };
  }
  return selected;
};

const agentLabel = (data: Record<string, unknown>, fallback?: string): string => {
  const supplied = text(data.agent_label || data.label || data.title);
  if (supplied && !/^agent[_-][a-f0-9]+$/i.test(supplied)) return supplied;
  const role = text(data.role || data.name || data.agent);
  if (role === 'research_lead' || role === 'root') return '主研究员';
  if (role && !/^agent[_-][a-f0-9]+$/i.test(role)) return getAgentDisplayName(role);
  return fallback || '专业研究员';
};

export function buildTurnActivities(steps: ThinkingStep[], loading: boolean): Activity[] {
  const rows: Activity[] = [];
  for (const step of steps) {
    const original = step.result && typeof step.result === 'object' ? step.result : {};
    const data: Record<string, unknown> = { ...original,
      ...(original.payload && typeof original.payload === 'object' ? original.payload : {}) };
    const event = text(data.runtime_type) || text(step.eventType) || step.stage;
    const isAgent = /^agent[._]/.test(event) || (/^step[._]/.test(event) && data.kind === 'agent');
    const isTool = !isAgent && /^(tool[._]|step[._])/.test(event);
    const isWork = /^(activity[._]|skill[._])/.test(event)
      || (event === 'trace' && (data.visibility === 'user' || (!data.visibility && ['understanding', 'retrieval'].includes(step.stage) && typeof data.summary === 'string')) && !['done', 'cancelled', 'error'].includes(step.stage));
    if (!isTool && !isAgent && !isWork) continue;
    if (isWork && /_model$/.test(text(data.activity_id || data.name))
      && !/error|failed|retry/.test(event + ':' + text(data.status))) continue;
    const name = text(data.name || data.tool || data.tool_name || data.agent || data.agent_id);
    const explicitId = text(data.tool_call_id || data.call_id || data.step_id || data.activity_id
      || (event.startsWith('skill.') ? `skill:${text(data.agent_id)}:${text(data.skill_id)}` : '') || (isAgent ? data.agent_id : ''));
    const key = explicitId || ((isAgent ? 'agent:' : isTool ? 'tool:' : 'work:') + name);
    const display = data.display && typeof data.display === 'object' ? data.display as Record<string, unknown> : {};
    const declaredStatus = text(display.status ?? data.status);
    const status: Activity['status'] = display.status === 'empty' ? 'partial'
      : /error|failed|unavailable/.test(event + ':' + declaredStatus) ? 'error'
      : /partial|limited|degraded/.test(declaredStatus) ? 'partial'
      : /cancel|interrupted/.test(event + ':' + declaredStatus) ? 'cancelled'
      : /done|end|result|finished|complete|activated/.test(event + ':' + declaredStatus) ? 'done' : 'running';
    let existing = -1;
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      if (rows[i].id === key && (explicitId || rows[i].status === 'running')) { existing = i; break; }
    }
    const previous = rows[existing];
    const label = key === 'model_capability' ? zh.chat.checkingModel : isAgent ? agentLabel(data, previous?.label)
      : text(display.title || data.label || data.title) || (step.stage === 'understanding' ? zh.chat.understandingQuestion : '') || labels[name] || zh.chat.organizingSources;
    const details = { ...previous?.details, ...activityDetails(data) };
    if (isAgent && data.summary && details.output_preview === undefined) details.output_preview = previewValue(data.summary);
    const summary = details.display?.result || (isAgent ? details.task : details.reason) || text(data.summary || data.message) || text(step.message);
    const generatedSummary = summary === `${name} Agent` || summary === `${name} start` || summary === `${name} end`
      || /^(?:step|tool)\s+\S+\s+(?:start|started|end|done|error)$/i.test(summary);
    const duration = data.duration_ms !== undefined ? Number(data.duration_ms) : previous?.duration;
    const row: Activity = {
      id: key, name, label, agent: text(data.agent_id || data.agent) || previous?.agent,
      target: details.display?.target || '', seq: previous?.seq ?? (typeof data.seq === 'number' ? data.seq : undefined),
      summary: summary === label || generatedSummary ? '' : summary.slice(0, 200),
      status, kind: isAgent ? 'agent' : isTool ? 'tool' : 'work',
      details, timestamp: step.timestamp, duration: duration !== undefined && Number.isFinite(duration) ? duration : undefined,
    };
    if (existing >= 0) rows[existing] = { ...rows[existing], ...row };
    else rows.push(row);
  }
  return rows.filter((row) => row.id !== 'model_capability' || row.status !== 'done').slice(-100)
    .map((row) => !loading && row.status === 'running' ? { ...row, status: 'cancelled' } : row);
}

export function isActivityVisible(row: Activity, now = Date.now()): boolean {
  return row.id !== 'model_capability' || row.status === 'error'
    || (row.status !== 'done' && Number.isFinite(Date.parse(row.timestamp)) && now - Date.parse(row.timestamp) >= 2000);
}

export function detailRows(value: unknown, prefix = '', field = ''): Array<{ label: string; value: string }> {
  if (value === null || value === undefined) return [{ label: prefix, value: zh.chat.missingDetailValue }];
  if (Array.isArray(value)) return value.flatMap((item, index) => detailRows(item, prefix ? `${prefix} ${index + 1}` : String(index + 1), field)).slice(0, 10);
  if (typeof value === 'object') return Object.entries(value).flatMap(([key, item]) =>
    detailRows(item, [prefix, fieldLabels[key] || key].filter(Boolean).join(' · '), key)).slice(0, 10);
  const displayed = typeof value === 'string' && ['source', 'provider', 'data_source'].includes(field) ? sourceDisplayName(value)
    : typeof value === 'string' && ['title', 'name', 'tool', 'tool_name', 'tools', 'enabled'].includes(field) ? sourceTitleDisplayName(value)
      : typeof value === 'boolean' ? value ? '是' : '否' : String(value);
  return [{ label: prefix, value: displayed }];
}
