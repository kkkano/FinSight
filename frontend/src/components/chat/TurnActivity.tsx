import { useEffect, useMemo, useState } from 'react';
import { Calculator, ChartNoAxesCombined, Check, ChevronDown, ChevronRight, CircleAlert, Loader2, Search, Square, TrendingUp, Users } from 'lucide-react';
import type { ThinkingStep } from '../../types';
import { researchFailureMessage } from '../../store/researchStream';
import styles from './ChatDesign.module.css';
import { sourceDisplayName, sourceTitleDisplayName } from '../../utils/sourceDisplayName';
import { ModelPickerButton } from '../settings/ModelPickerButton';
import { zh } from '../../locales/zh';
import { type Activity, text, previewValue, fieldLabels, buildTurnActivities, isActivityVisible, detailRows } from "./TurnActivity.utils";

function decodedDetail(value: unknown): unknown {
  if (typeof value === 'string' && /^[\s]*[{[]/.test(value)) {
    try { return previewValue(JSON.parse(value)); } catch { return value; }
  }
  return value;
}

const hasDetail = (value: unknown) => value !== undefined && value !== null && value !== ''
  && (typeof value !== 'object' || Object.keys(value).length > 0);

function DetailValue({ value }: { value: unknown }) {
  let decoded = decodedDetail(value);
  if (decoded && typeof decoded === 'object' && !Array.isArray(decoded) && 'content' in decoded) {
    const content = decodedDetail((decoded as Record<string, unknown>).content);
    if (content && typeof content === 'object') {
      decoded = { ...decoded, content: 'output' in content ? content.output : content };
    }
  }
  const record = decoded && typeof decoded === 'object' && !Array.isArray(decoded) ? decoded as Record<string, unknown> : {};
  const candidate = Array.isArray(decoded) ? decoded : record.news || record.articles || record.results || record.content || record.preview;
  const articles = Array.isArray(candidate) ? candidate.filter((item): item is Record<string, unknown> =>
    Boolean(item && typeof item === 'object' && (text(item.title) || text(item.headline)) && /^https?:\/\//.test(text(item.url)))) : [];
  if (articles.length) return <ul className={styles.resultArticles}>{articles.slice(0, 5).map((article, index) => <li key={index}>
    <a href={text(article.url)} target="_blank" rel="noopener noreferrer">{text(article.title) || text(article.headline)}</a>
    <div className="text-xs text-t-text3">{[text(article.source) && sourceDisplayName(text(article.source)),
      text(article.published_at || article.published_date || article.as_of).slice(0, 10)].filter(Boolean).join(' · ')}</div>
    {text(article.snippet || article.summary) && <p>{text(article.snippet || article.summary)}</p>}
  </li>)}</ul>;
  const rows = detailRows(decoded);
  if (!rows.length) return <p className="text-t-text3">{zh.chat.noMoreFields}</p>;
  return <dl className={styles.detailPairs}>{rows.map((row, index) => <div key={index}
    className={`${styles.detailPair} ${!row.label || row.value.length > 100 || /\n|\\n/.test(row.value) ? styles.detailWide : ''}`}>
    {row.label && <dt>{row.label}</dt>}<dd>{/^https?:\/\/\S+$/.test(row.value)
      ? <a href={row.value} target="_blank" rel="noopener noreferrer" className="text-t-accent underline">{row.value}</a>
      : row.value.replace(/\\n/g, '\n')}</dd></div>)}</dl>;
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
  const hasRecordedDetails = hasDetail(detail.inputs) || hasDetail(detail.output_preview) || hasDetail(detail.sources)
    || Boolean(detail.reason || detail.error_code || detail.task || detail.limitations || detail.display?.key_facts?.length);
  const failure = detail.reason || detail.error_code ? researchFailureMessage({ reason: detail.reason, error_code: detail.error_code }) : '';
  const displayCategory = detail.display?.kind && ({ quote: 'data', series: 'data', table: 'data', news: 'search',
    document: 'search', computation: 'compute', chart: 'chart', control: 'search' } as const)[detail.display.kind];
  const category = row.kind === 'agent' ? 'agent' : displayCategory || (/render_chart|chart/.test(row.name) ? 'chart'
    : /analy|compute|python/.test(row.name) ? 'compute' : /fetch_url|read_|filing|financial_statement|sec_company/.test(row.name) ? 'search'
      : /^get_|^fetch_/.test(row.name) ? 'data' : 'search');
  const Icon = category === 'agent' ? Users : category === 'chart' ? ChartNoAxesCombined
    : category === 'compute' ? Calculator : category === 'data' ? TrendingUp : Search;
  const color = category === 'data' ? 'var(--t-amber)' : category === 'compute' ? 'var(--t-violet)'
    : category === 'chart' ? 'var(--t-teal)' : 'rgb(var(--t-accent))';
  return <details className="tool-activity">
    <summary className="tool-activity-row">
      <Icon size={15} style={{ color }} />
      <span className="tool-activity-name">{row.label}</span>
      <span className={styles.activityContext}>
        <span className="tool-activity-target num">{row.target}</span>
        <span className="tool-activity-summary" title={row.summary}>{row.status === 'running' ? '…' : row.summary}</span>
      </span>
      <span className="num text-xs text-t-text3">{row.duration !== undefined ? `${(row.duration / 1000).toFixed(1)}s` : ''}</span>
      {row.status === 'running' ? <Loader2 size={13} className="animate-spin text-t-text3" />
        : row.status === 'done' ? <Check size={13} className="text-t-success" />
          : row.status === 'partial' ? <CircleAlert size={13} className="text-fin-warning" />
            : row.status === 'error' ? <CircleAlert size={13} className="text-t-error" /> : <Square size={11} className="text-t-text3" />}
    </summary>
    <div className="tool-activity-details space-y-3">
      {row.summary && row.summary !== detail.task && row.summary !== failure && row.summary !== detail.reason && <p>{row.summary}</p>}
      {detail.task && <div><p className="mb-1 font-medium">研究任务</p><DetailValue value={detail.task} /></div>}
      {failure && <div className="text-fin-danger"><p className="mb-1 font-medium">失败原因</p><p>{failure}</p>
        {detail.reason && detail.reason !== failure && <p className="mt-1 whitespace-pre-wrap break-words">{detail.reason}</p>}
        {detail.error_code && <p className="mt-1 text-xs text-t-text3">错误代码：{detail.error_code}</p>}</div>}
      {detail.recovery_action && <div><p className="mb-1 font-medium">建议</p><p>{detail.recovery_action}</p></div>}
      {(hasDetail(detail.inputs) || hasDetail(detail.output_preview) || Boolean(detail.display?.key_facts?.length)) && <div className={styles.toolPreview}>
        {hasDetail(detail.inputs) && <div><p className="mb-1 font-medium">参数</p><DetailValue value={detail.inputs} /></div>}
        {detail.display?.key_facts?.length ? <div><p className="mb-1 font-medium">结果</p><dl className={styles.detailPairs}>
          {detail.display.key_facts.map((fact, index) => <div className={styles.detailPair} key={`${fact.label}:${index}`}>
            <dt>{fact.label}</dt><dd><DetailValue value={fact.value} /></dd>
          </div>)}</dl></div> : hasDetail(detail.output_preview) && <div><p className="mb-1 font-medium">结果</p><DetailValue value={detail.output_preview} /></div>}
      </div>}
      {detail.sources !== undefined && <div><p className="mb-1 font-medium">来源</p><SourceDetails value={detail.sources} /></div>}
      {(['source_refs', 'data_refs', 'evidence_refs'] as const).some((key) => hasDetail(detail[key])) &&
        <details className={styles.referenceDetails}><summary>引用标识</summary>
          {(['source_refs', 'data_refs', 'evidence_refs'] as const).filter((key) => hasDetail(detail[key])).map((key) =>
            <div key={key}><p className="mb-1 font-medium">{fieldLabels[key]}</p><DetailValue value={detail[key]} /></div>)}
        </details>}
      {detail.limitations !== undefined && <div><p className="mb-1 font-medium">数据限制</p><DetailValue value={detail.limitations} /></div>}
      {!hasRecordedDetails && row.kind === 'tool' && <p className="text-t-text3">{row.status === 'running' ? zh.chat.waitingResult : zh.chat.noSavedDetails}</p>}
      {!hasRecordedDetails && !row.summary && row.kind === 'work' && <p className="text-t-text3">{
        row.id === 'model_capability' && row.status === 'running' ? zh.chat.modelCheckDetails
          : row.status === 'running' ? zh.chat.waitingOperation : zh.chat.operationEndedWithoutDetails}</p>}
      {row.status === 'error' && !failure && <p className="text-t-text3">{zh.chat.missingFailureReason}</p>}
      {row.id === 'model_capability' && row.status === 'error' && <ModelPickerButton label={zh.chat.changeModel} />}
    </div>{children}
  </details>;
}

export function ActivityRows({ rows }: { rows: Activity[] }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const pending = rows.find((row) => row.id === 'model_capability' && row.status === 'running' && !isActivityVisible(row));
    if (!pending || !Number.isFinite(Date.parse(pending.timestamp))) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, Date.parse(pending.timestamp) + 2000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [rows]);
  const visible = rows.filter((row) => isActivityVisible(row, Math.max(now, Date.now())));
  return <div className="activity-rows">
    {visible.filter((row) => row.kind === 'agent' || !visible.some((agent) => agent.kind === 'agent' && agent.agent && agent.agent === row.agent)).map((row, index) => {
      const children = row.kind === 'agent' ? visible.filter((child) => child.kind !== 'agent' && child.agent && child.agent === row.agent) : [];
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
  const terminal = [...thinking].reverse().find((step) => ['done', 'cancelled', 'error'].includes(step.stage));
  const live = isLoading && !terminal && !['completed', 'failed', 'cancelled', 'interrupted', 'persistence_failed'].includes(runStatus || '');
  const rows = useMemo(() => buildTurnActivities(thinking, live), [thinking, live]);
  const [localOpen, setOpen] = useState(false);
  const open = expanded ?? localOpen;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);
  const stopped = runStatus === 'cancelled' || terminal?.stage === 'cancelled';
  const failed = Boolean(error) || terminal?.stage === 'error' || ['failed', 'interrupted', 'persistence_failed'].includes(runStatus || '');
  const partial = !failed && (runStatus === 'partial' || terminal?.result?.status === 'partial');
  const end = terminal ? Date.parse(terminal.timestamp) : now;
  const elapsed = startedAt && Number.isFinite(end) && (live || terminal) ? Math.max(0, Math.round((end - startedAt) / 1000)) : undefined;
  if (!rows.length && !live && !stopped && !failed && !partial && !hasProgress) return null;
  const count = rows.filter((row) => row.kind === 'tool').length;
  const current = [...rows].reverse().find((row) => row.status === 'running');
  const visibleCurrent = current && isActivityVisible(current, now) ? current : undefined;
  const caption = live ? (visibleCurrent ? visibleCurrent.label.startsWith('正在') ? visibleCurrent.label : zh.chat.currentActivity(visibleCurrent.label) : zh.chat.processingQuestion)
    : stopped ? zh.chat.stoppedLabel : runStatus === 'persistence_failed' ? zh.chat.savingFailed : failed ? zh.chat.incomplete : partial ? zh.chat.analysisPartial : elapsed === undefined ? zh.chat.completed : zh.chat.processed;
  return <section className="turn-activity" aria-label={zh.chat.researchProcess}>
    {/* 播报只含活动与终态，计时和正文流更新不改变这个区域。 */}
    <span role="status" aria-live="polite" aria-atomic="true" className="sr-only" data-testid="research-status">{caption}</span>
    <button type="button" className="turn-activity-toggle" onClick={() => { setOpen(!open); onExpandedChange?.(!open); }} aria-expanded={open}>
      {live ? <Loader2 size={14} className="animate-spin" /> : open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      <span>{caption}{elapsed !== undefined ? zh.chat.durationSeconds(elapsed) : ''}{count ? zh.chat.toolCallCount(count) : ''}</span>
    </button>
    {open && !summaryOnly && <div>
      {terminal?.message && (failed || partial) && <p className="px-2 py-2 text-sm text-t-text2">{terminal.message}</p>}
      <div className={styles.process}><ActivityRows rows={rows} /></div>
      {!rows.length && <p className="px-2 py-2 text-sm text-t-text3">{zh.chat.noProcessRecords}</p>}
    </div>}
    {!open && rows.some((row) => row.status === 'error' || row.status === 'partial') && <p className="mt-1 text-xs text-t-error">
      {zh.chat.sourcesUnavailable}
    </p>}
  </section>;
}
