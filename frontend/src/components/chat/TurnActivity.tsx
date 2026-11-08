import { useEffect, useMemo, useState } from 'react';
import { Calculator, ChartNoAxesCombined, Check, ChevronDown, ChevronRight, CircleAlert, Loader2, Search, Square, TrendingUp, Users } from 'lucide-react';
import type { ThinkingStep } from '../../types';
import type { RuntimeActivityDetails } from '../../types/runtime';
import { getAgentDisplayName } from '../../utils/userMessageMapper';
import { researchFailureMessage } from '../../store/researchStream';
import styles from './ChatDesign.module.css';
import { sourceDisplayName, sourceTitleDisplayName } from '../../utils/sourceDisplayName';

export type Activity = {
  id: string; name: string; label: string; agent?: string; summary: string; target: string; seq?: number;
  status: 'running' | 'done' | 'error' | 'cancelled' | 'partial';
  kind: 'tool' | 'agent' | 'work'; details: RuntimeActivityDetails; timestamp: string; duration?: number;
};
const labels: Record<string, string> = {
  get_stock_price: '获取行情', get_company_news: '读取公司新闻', search: '搜索资料',
  fetch_url_content: '读取网页', get_stock_historical_data: '获取历史行情',
  get_sec_company_facts_quarterly: '读取季度财报', get_local_market_filings: '读取公司公告',
  search_knowledge: '检索历史资料', read_document: '读取文档', search_memory: '检索研究记录',
  run_analysis_code: '分析数据', run_python_compute: '计算指标', render_chart: '绘制图表',
  delegate_research: '分工研究', send_agent_message: '补充问题', await_agent_results: '汇总结果',
  discover_tools: '查找工具', enable_tools: '启用工具', read_evidence: '读取资料',
  read_selection: '读取选中资料', get_earnings_estimates: '获取盈利预期', get_eps_revisions: '获取盈利预期修正',
  get_company_info: '获取公司信息', get_financial_statements: '读取财务报表', get_current_datetime: '查看时间',
  get_technical_snapshot: '计算技术指标', get_market_benchmark_history: '获取基准行情',
  get_relative_strength: '计算相对强弱', analyze_historical_drawdowns: '分析历史回撤',
  get_performance_comparison: '比较价格表现', get_option_chain_metrics: '读取期权指标',
  get_news_sentiment: '分析新闻情绪', get_event_calendar: '读取事件日历',
  score_news_source_reliability: '核查新闻来源', get_market_sentiment: '读取市场情绪',
  get_fred_data: '读取宏观数据', get_official_macro_releases: '读取官方宏观公告',
  get_economic_events: '读取经济事件', get_factor_exposure: '计算风险因子敞口',
  analyze_dataset: '分析数据', get_watchlist: '读取自选清单',
  mark_report: '整理研究报告', propose_action: '提出待确认操作',
  discover_skills: '查找技能', use_skill: '应用技能',
};
const text = (value: unknown) => typeof value === 'string' ? value : '';
const fieldLabels: Record<string, string> = {
  ticker: '标的', symbol: '代码', query: '查询', task: '研究任务', role: '研究角色',
  period: '期间', start_date: '起始日期', end_date: '结束日期', limit: '数量上限',
  name: '名称', title: '标题', description: '说明', summary: '摘要', status: '状态',
  source: '来源', sources: '来源', provider: '服务来源', data_source: '数据来源', tool: '工具', tool_name: '工具', url: '链接', as_of: '数据时间', date: '日期',
  price: '价格', currency: '货币', value: '数值', unit: '单位', result_count: '结果数量',
  data: '数据', result: '结果', rows: '数据行', enabled: '已启用', tools: '工具',
  data_ref: '相关数据', data_refs: '相关数据', source_refs: '相关来源', evidence_refs: '相关资料',
  error: '错误', error_code: '错误代码', reason: '原因', limitations: '限制',
};
const sensitiveKey = /(?:api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token|cookie|credential)/i;
const previewValue = (value: unknown, depth = 0): unknown => {
  if (typeof value === 'string') return value.slice(0, 2400);
  if (value == null || typeof value !== 'object') return value;
  if (depth >= 5) return '内容过长，已省略更深层级';
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
    selected.display = { target: text(display.target), result: text(display.result) };
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
    const status: Activity['status'] = /error|failed|unavailable/.test(event + ':' + text(data.status)) ? 'error'
      : /partial|limited|degraded/.test(text(data.status)) ? 'partial'
      : /cancel|interrupted/.test(event + ':' + text(data.status)) ? 'cancelled'
      : /done|end|result|finished|complete|activated/.test(event + ':' + text(data.status)) ? 'done' : 'running';
    let existing = -1;
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      if (rows[i].id === key && (explicitId || rows[i].status === 'running')) { existing = i; break; }
    }
    const previous = rows[existing];
    const label = isAgent ? agentLabel(data, previous?.label)
      : text(data.label || data.title) || (step.stage === 'understanding' ? '理解问题' : '') || labels[name] || '整理资料';
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
  return rows.slice(-100).map((row) => !loading && row.status === 'running' ? { ...row, status: 'cancelled' } : row);
}

export function detailRows(value: unknown, prefix = '', field = ''): Array<{ label: string; value: string }> {
  if (value === null || value === undefined) return [{ label: prefix, value: '未提供' }];
  if (Array.isArray(value)) return value.flatMap((item, index) => detailRows(item, prefix ? `${prefix} ${index + 1}` : String(index + 1), field)).slice(0, 10);
  if (typeof value === 'object') return Object.entries(value).flatMap(([key, item]) =>
    detailRows(item, [prefix, fieldLabels[key] || key].filter(Boolean).join(' · '), key)).slice(0, 10);
  const displayed = typeof value === 'string' && ['source', 'provider', 'data_source'].includes(field) ? sourceDisplayName(value)
    : typeof value === 'string' && ['title', 'name', 'tool', 'tool_name', 'tools', 'enabled'].includes(field) ? sourceTitleDisplayName(value)
      : typeof value === 'boolean' ? value ? '是' : '否' : String(value);
  return [{ label: prefix, value: displayed }];
}

function DetailValue({ value }: { value: unknown }) {
  const rows = detailRows(value);
  return <table className={styles.detailTable}><tbody>{rows.map((row, index) => <tr key={index}>
    {row.label && <th>{row.label}</th>}<td>{/^https?:\/\/\S+$/.test(row.value)
      ? <a href={row.value} target="_blank" rel="noopener noreferrer" className="text-t-accent underline">{row.value}</a>
      : row.value}</td></tr>)}</tbody></table>;
}

function SourceDetails({ value }: { value: unknown }) {
  const sources = Array.isArray(value) ? value : [value];
  return <ul className="space-y-1.5">{sources.slice(0, 10).map((source, index) => {
    if (!source || typeof source !== 'object') return <li key={index}>{sourceTitleDisplayName(text(source))}</li>;
    const row = source as Record<string, unknown>;
    const title = sourceTitleDisplayName(text(row.title), text(row.source));
    const url = text(row.url);
    return <li key={index} className="flex flex-wrap items-baseline gap-x-2">
      {/^https?:\/\//.test(url) ? <a href={url} target="_blank" rel="noopener noreferrer" className="text-t-accent underline" title={url}>{title}</a> : <span>{title}</span>}
      {text(row.source) && <span className="text-t-text3">{sourceDisplayName(text(row.source))}</span>}
      {text(row.as_of) && <time className="text-t-text3">{text(row.as_of).slice(0, 10)}</time>}
    </li>;
  })}</ul>;
}

export function ActivityRow({ row, children }: { row: Activity; children?: React.ReactNode }) {
  const detail = row.details;
  const hasRecordedDetails = detail.inputs !== undefined || detail.output_preview !== undefined
    || Boolean(detail.reason || detail.error_code || detail.task || detail.limitations);
  const failure = detail.reason || detail.error_code ? researchFailureMessage({ reason: detail.reason, error_code: detail.error_code }) : '';
  const category = row.kind === 'agent' ? 'agent' : /render_chart|chart/.test(row.name) ? 'chart'
    : /analy|compute|python/.test(row.name) ? 'compute' : /fetch_url|read_|filing|financial_statement|sec_company/.test(row.name) ? 'search'
      : /^get_|^fetch_/.test(row.name) ? 'data' : 'search';
  const Icon = category === 'agent' ? Users : category === 'chart' ? ChartNoAxesCombined
    : category === 'compute' ? Calculator : category === 'data' ? TrendingUp : Search;
  const color = category === 'data' ? 'var(--t-amber)' : category === 'compute' ? 'var(--t-violet)'
    : category === 'chart' ? 'var(--t-teal)' : 'rgb(var(--t-accent))';
  return <details className="tool-activity">
    <summary className="tool-activity-row">
      <Icon size={15} style={{ color }} />
      <span className="tool-activity-name">{row.label}</span><span className="tool-activity-summary" title={[row.target, row.summary].filter(Boolean).join(' · ')}>
        {[row.target, row.status === 'running' ? '…' : row.summary].filter(Boolean).join(' · ')}</span>
      <span className="num text-xs text-t-text3">{row.duration !== undefined ? `${(row.duration / 1000).toFixed(1)}s` : ''}</span>
      {row.status === 'running' ? <Loader2 size={13} className="animate-spin text-t-text3" />
        : row.status === 'done' ? <Check size={13} className="text-fin-success" />
          : row.status === 'partial' ? <CircleAlert size={13} className="text-fin-warning" />
            : row.status === 'error' ? <CircleAlert size={13} className="text-fin-danger" /> : <Square size={11} className="text-t-text3" />}
    </summary>
    <div className="tool-activity-details space-y-3">
      {row.summary && row.summary !== detail.task && row.summary !== failure && <p>{row.summary}</p>}
      {detail.task && <div><p className="mb-1 font-medium">研究任务</p><DetailValue value={detail.task} /></div>}
      {failure && <div className="text-fin-danger"><p className="mb-1 font-medium">失败原因</p><p>{failure}</p>
        {detail.error_code && <p className="mt-1 text-xs text-t-text3">错误代码：{detail.error_code}</p>}</div>}
      {detail.recovery_action && <div><p className="mb-1 font-medium">建议</p><p>{detail.recovery_action}</p></div>}
      {(detail.inputs !== undefined || detail.output_preview !== undefined) && <div className={styles.toolPreview}>
        {detail.inputs !== undefined && <div><p className="mb-1 font-medium">参数</p><DetailValue value={detail.inputs} /></div>}
        {detail.output_preview !== undefined && <div><p className="mb-1 font-medium">结果</p><DetailValue value={detail.output_preview} /></div>}
      </div>}
      {detail.sources !== undefined && <div><p className="mb-1 font-medium">来源</p><SourceDetails value={detail.sources} /></div>}
      {(['source_refs', 'data_refs', 'evidence_refs'] as const).filter((key) => detail[key] !== undefined).map((key) =>
        <div key={key}><p className="mb-1 font-medium">{fieldLabels[key]}</p><DetailValue value={detail[key]} /></div>)}
      {row.duration !== undefined && <p>耗时：{(row.duration / 1000).toFixed(1)} 秒</p>}
      {detail.limitations !== undefined && <div><p className="mb-1 font-medium">数据限制</p><DetailValue value={detail.limitations} /></div>}
      {!hasRecordedDetails && row.kind === 'tool' && <p className="text-t-text3">{row.status === 'running' ? '正在等待结果…' : '这条记录没有保存详细信息。'}</p>}
      {row.status === 'error' && !failure && <p className="text-t-text3">这条记录没有提供具体的失败原因。</p>}
    </div>{children}
  </details>;
}

export function ActivityRows({ rows }: { rows: Activity[] }) {
  return <div className={styles.activityRows}>
    {rows.filter((row) => row.kind === 'agent' || !rows.some((agent) => agent.kind === 'agent' && agent.agent && agent.agent === row.agent)).map((row, index) => {
      const children = row.kind === 'agent' ? rows.filter((child) => child.kind !== 'agent' && child.agent && child.agent === row.agent) : [];
      return <ActivityRow key={row.id + ':' + index} row={row}>
        {children.length > 0 && <div className={styles.nested}>{children.map((child, childIndex) => <ActivityRow row={child} key={child.id + ':' + childIndex} />)}</div>}
      </ActivityRow>;
    })}
  </div>;
}

export function TurnActivity({ thinking = [], isLoading = false, startedAt, error, runStatus, summaryOnly = false, expanded, onExpandedChange, hasProgress = false }: {
  thinking?: ThinkingStep[]; isLoading?: boolean; startedAt?: number; error?: string; runStatus?: string;
  summaryOnly?: boolean; expanded?: boolean; onExpandedChange?: (value: boolean) => void;
  hasProgress?: boolean;
}) {
  const rows = useMemo(() => buildTurnActivities(thinking, isLoading), [thinking, isLoading]);
  const [localOpen, setOpen] = useState(false);
  const open = expanded ?? localOpen;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!isLoading) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [isLoading]);
  const terminal = [...thinking].reverse().find((step) => ['done', 'cancelled', 'error'].includes(step.stage));
  const stopped = runStatus === 'cancelled' || terminal?.stage === 'cancelled';
  const failed = Boolean(error) || terminal?.stage === 'error' || ['failed', 'interrupted', 'persistence_failed'].includes(runStatus || '');
  const partial = !failed && (runStatus === 'partial' || terminal?.result?.status === 'partial');
  const end = terminal ? Date.parse(terminal.timestamp) : now;
  const elapsed = startedAt && (isLoading || terminal) ? Math.max(0, Math.round((end - startedAt) / 1000)) : undefined;
  if (!rows.length && !isLoading && !stopped && !failed && !partial && !hasProgress) return null;
  const count = rows.filter((row) => row.kind === 'tool').length;
  const current = [...rows].reverse().find((row) => row.status === 'running');
  const caption = isLoading ? (current ? current.label.startsWith('正在') ? current.label : `正在${current.label}…` : '正在处理你的问题')
    : stopped ? '已停止' : runStatus === 'persistence_failed' ? '保存失败' : failed ? '未完成' : partial ? '已完成，部分信息待确认' : elapsed === undefined ? '已完成' : '已处理';
  return <section className="turn-activity" aria-label="研究过程">
    <button type="button" className="turn-activity-toggle" onClick={() => { setOpen(!open); onExpandedChange?.(!open); }} aria-expanded={open}>
      {isLoading ? <Loader2 size={14} className="animate-spin" /> : open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      <span>{caption}{elapsed !== undefined ? ' ' + elapsed + ' 秒' : ''}{count ? ' · ' + count + ' 次工具调用' : ''}</span>
    </button>
    {open && !summaryOnly && <div>
      {terminal?.message && (failed || partial) && <p className="px-2 py-2 text-sm text-t-text2">{terminal.message}</p>}
      <ActivityRows rows={rows} />
      {!rows.length && <p className="px-2 py-2 text-sm text-t-text3">暂时没有过程记录。</p>}
    </div>}
    {!open && rows.some((row) => row.status === 'error' || row.status === 'partial') && <p className="mt-1 text-xs text-fin-danger">
      有些资料没能获取，展开查看原因。
    </p>}
  </section>;
}

