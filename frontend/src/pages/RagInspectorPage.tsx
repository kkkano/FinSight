import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { apiClient } from '../api/client';
import { buildRagObservabilitySummary } from './ragInspectorStatus';

type RagStatusResponse = {
  status?: string;
  data?: {
    backend_requested?: string;
    backend_actual?: string;
    doc_count?: number;
    vector_dim?: number;
    observability?: {
      enabled?: boolean;
      backend?: string;
      recent_run_count_24h?: number;
      recent_fallback_count_24h?: number;
      recent_empty_hits_rate_24h?: number;
      last_run_at?: string | null;
      last_fallback_at?: string | null;
    };
  };
};

type RagRun = Record<string, any>;
type RagRunListResponse = { status?: string; data?: { items?: RagRun[]; next_cursor?: string | null } };

type RagRunBundle = {
  summary: RagRun | null;
  events: Array<Record<string, any>>;
  documents: Array<Record<string, any>>;
  chunks: Array<Record<string, any>>;
  hits: Array<Record<string, any>>;
};

type DbBrowserTableName = 'rag_query_runs' | 'rag_source_docs' | 'rag_chunks' | 'rag_documents_v2';

type DbBrowserPayload = {
  table: DbBrowserTableName;
  columns: string[];
  items: Array<Record<string, any>>;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

const DB_BROWSER_TABLES: DbBrowserTableName[] = ['rag_query_runs', 'rag_source_docs', 'rag_chunks', 'rag_documents_v2'];

const DB_BROWSER_COLUMN_PRIORITY: Record<DbBrowserTableName, string[]> = {
  rag_query_runs: ['id', 'started_at', 'status', 'collection', 'route_name', 'backend_actual', 'query_text'],
  rag_source_docs: ['id', 'run_id', 'collection', 'source_type', 'title', 'url', 'content_preview'],
  rag_chunks: ['id', 'run_id', 'source_doc_id', 'collection', 'chunk_index', 'doc_type', 'chunk_strategy', 'chunk_text'],
  rag_documents_v2: ['id', 'collection', 'scope', 'source_id', 'title', 'url', 'source', 'content'],
};

const DB_BROWSER_DETAIL_FIELDS: Record<DbBrowserTableName, string[]> = {
  rag_query_runs: ['query_text', 'query_text_redacted'],
  rag_source_docs: ['content_preview', 'content_raw'],
  rag_chunks: ['chunk_text'],
  rag_documents_v2: ['content'],
};

const EMPTY_DB_BROWSER_PAYLOAD: DbBrowserPayload = {
  table: 'rag_query_runs',
  columns: [],
  items: [],
  total: 0,
  limit: 25,
  offset: 0,
  has_more: false,
};

const formatDateTime = (value?: string | null): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
};

const formatPercent = (value?: number | null): string => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(1)}%`;
};

const formatNumber = (value: unknown, digits = 4): string => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
};

const extractItems = (payload: unknown): Array<Record<string, any>> => {
  if (Array.isArray(payload)) return payload.filter(Boolean) as Array<Record<string, any>>;
  if (payload && typeof payload === 'object' && Array.isArray((payload as { items?: unknown[] }).items)) {
    return ((payload as { items?: unknown[] }).items ?? []).filter(Boolean) as Array<Record<string, any>>;
  }
  return [];
};

const jsonPreview = (value: unknown): string => {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const formatDbBrowserCell = (value: unknown, maxLength = 120): string => {
  if (value == null || value === '') return '?';
  const text = typeof value === 'string' ? value : jsonPreview(value);
  return text.length > maxLength ? `${text.slice(0, maxLength)}?` : text;
};

const getDbBrowserRowKey = (table: DbBrowserTableName, row: Record<string, any>, index: number): string => {
  const parts = [row.id, row.run_id, row.source_doc_id, row.source_id]
    .map((value) => String(value || '').trim())
    .filter(Boolean);
  return parts.length > 0 ? `${table}:${parts.join(':')}` : `${table}:row:${index}`;
};

const copyTextToClipboard = async (value: string): Promise<boolean> => {
  const nextValue = String(value || '').trim();
  if (!nextValue) return false;

  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(nextValue);
      return true;
    } catch {
    }
  }

  if (typeof document === 'undefined') return false;
  const textarea = document.createElement('textarea');
  textarea.value = nextValue;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  textarea.style.pointerEvents = 'none';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch {
    copied = false;
  }
  document.body.removeChild(textarea);
  return copied;
};

const SectionCard: React.FC<{ title: string; children: React.ReactNode; extra?: React.ReactNode }> = ({ title, children, extra }) => (
  <section className="rounded-2xl border border-fin-border bg-fin-card p-4 shadow-sm">
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold text-fin-text">{title}</h2>
      {extra}
    </div>
    {children}
  </section>
);

const ExpandableText: React.FC<{
  label: string;
  value?: string | null;
  previewLength?: number;
  mono?: boolean;
}> = ({ label, value, previewLength = 240, mono = false }) => {
  const text = String(value || '').trim();
  if (!text) return <div className="text-xs text-fin-muted">{label}：—</div>;
  const preview = text.length > previewLength ? `${text.slice(0, previewLength)}…` : text;
  return (
    <details className="rounded-lg border border-fin-border/70 bg-fin-card/40 px-3 py-2">
      <summary className="cursor-pointer list-none text-xs font-medium text-fin-text">
        {label}
      </summary>
      <div className="mt-2 text-xs text-fin-muted">{preview}</div>
      {text.length > previewLength ? (
        <pre className={[
          'mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-fin-bg px-3 py-2 text-xs text-fin-text',
          mono ? 'font-mono' : '',
        ].join(' ')}>
          {text}
        </pre>
      ) : null}
    </details>
  );
};

export const RagInspectorPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkedRunId = String(searchParams.get('run_id') || '').trim();
  const [status, setStatus] = useState<RagStatusResponse['data'] | null>(null);
  const [runs, setRuns] = useState<RagRun[]>([]);
  const [collections, setCollections] = useState<Array<Record<string, any>>>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>(() => deepLinkedRunId);
  const [bundle, setBundle] = useState<RagRunBundle>({ summary: null, events: [], documents: [], chunks: [], hits: [] });
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string>('');
  const [queryFilter, setQueryFilter] = useState('');
  const [fallbackOnly, setFallbackOnly] = useState(false);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const [dbBrowserTable, setDbBrowserTable] = useState<DbBrowserTableName>('rag_query_runs');
  const [dbBrowserPayload, setDbBrowserPayload] = useState<DbBrowserPayload>(EMPTY_DB_BROWSER_PAYLOAD);
  const [dbBrowserLoading, setDbBrowserLoading] = useState(false);
  const [dbBrowserError, setDbBrowserError] = useState('');
  const [dbBrowserQ, setDbBrowserQ] = useState('');
  const [dbBrowserCollection, setDbBrowserCollection] = useState('');
  const [dbBrowserRunId, setDbBrowserRunId] = useState('');
  const [dbBrowserSourceDocId, setDbBrowserSourceDocId] = useState('');
  const [dbBrowserLimit, setDbBrowserLimit] = useState(25);
  const [dbBrowserOffset, setDbBrowserOffset] = useState(0);
  const [selectedDbRowKey, setSelectedDbRowKey] = useState('');
  const detailSectionRef = useRef<HTMLDivElement | null>(null);

  const syncSelectedRunId = useCallback((runId: string) => {
    setSelectedRunId(String(runId || '').trim());
  }, []);

  const loadOverview = useCallback(async () => {
    setLoadingOverview(true);
    setError('');
    try {
      const [healthRes, statusRes, runsRes, collectionsRes] = await Promise.all([
        apiClient.healthCheck(),
        apiClient.diagnosticsRagStatus(),
        apiClient.diagnosticsRagRuns({ limit: 20, q: queryFilter, fallback_only: fallbackOnly }),
        apiClient.diagnosticsRagCollections({ limit: 20 }),
      ]);
      const healthComponents = ((healthRes as { components?: Record<string, any> })?.components ?? {}) as Record<string, any>;
      const ragComponent = (healthComponents.rag ?? {}) as Record<string, any>;
      const ragObservabilityComponent = (healthComponents.rag_observability ?? {}) as Record<string, any>;
      const statusPayload = ((statusRes as RagStatusResponse)?.data ?? {}) as Record<string, any>;
      const { summary: observabilitySummary } = buildRagObservabilitySummary(statusPayload, ragObservabilityComponent);
      const nextRuns = ((runsRes as RagRunListResponse)?.data?.items ?? []).filter(Boolean);
      setStatus({
        backend_requested: String(ragComponent.expected_backend || 'auto'),
        backend_actual: String(ragComponent.backend || 'unknown'),
        doc_count: Number(ragComponent.doc_count || 0),
        vector_dim: Number(ragComponent.vector_dim || 0),
        observability: observabilitySummary,
      });
      setRuns(nextRuns);
      setCollections(extractItems((collectionsRes as { data?: unknown })?.data));
      setSelectedRunId((current) => current || String(nextRuns[0]?.id || ''));
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : '加载 RAG 观测数据失败');
    } finally {
      setLoadingOverview(false);
    }
  }, [fallbackOnly, queryFilter]);

  const loadRunBundle = useCallback(async (runId: string) => {
    if (!runId) {
      setBundle({ summary: null, events: [], documents: [], chunks: [], hits: [] });
      return;
    }
    setLoadingDetail(true);
    setError('');
    try {
      const [summaryRes, eventsRes, docsRes, chunksRes, hitsRes] = await Promise.all([
        apiClient.diagnosticsRagRunDetail(runId),
        apiClient.diagnosticsRagRunEvents(runId),
        apiClient.diagnosticsRagRunDocuments(runId),
        apiClient.diagnosticsRagRunChunks(runId),
        apiClient.diagnosticsRagRunHits(runId),
      ]);
      setBundle({
        summary: summaryRes?.data ?? null,
        events: extractItems(eventsRes?.data),
        documents: extractItems(docsRes?.data),
        chunks: extractItems(chunksRes?.data),
        hits: extractItems(hitsRes?.data),
      });
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : '加载查询详情失败');
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const loadDbBrowser = useCallback(async (next?: Partial<{ table: DbBrowserTableName; limit: number; offset: number; q: string; collection: string; run_id: string; source_doc_id: string }>) => {
    const nextTable = next?.table ?? dbBrowserTable;
    const nextLimit = next?.limit ?? dbBrowserLimit;
    const nextOffset = next?.offset ?? dbBrowserOffset;
    const nextQ = next?.q ?? dbBrowserQ;
    const nextCollection = next?.collection ?? dbBrowserCollection;
    const nextRunId = next?.run_id ?? dbBrowserRunId;
    const nextSourceDocId = next?.source_doc_id ?? dbBrowserSourceDocId;

    setDbBrowserLoading(true);
    setDbBrowserError('');
    try {
      const response = await apiClient.diagnosticsRagDbBrowser(nextTable, {
        limit: nextLimit,
        offset: nextOffset,
        q: nextQ,
        collection: nextCollection,
        run_id: nextRunId,
        source_doc_id: nextSourceDocId,
      });
      const payload = (response?.data ?? {}) as Record<string, any>;
      const items = extractItems(payload);
      const columns = Array.isArray(payload.columns) ? payload.columns.map((value) => String(value)) : [];
      setDbBrowserPayload({
        table: nextTable,
        columns,
        items,
        total: Number(payload.total ?? items.length),
        limit: Number(payload.limit ?? nextLimit),
        offset: Number(payload.offset ?? nextOffset),
        has_more: Boolean(payload.has_more),
      });
      setSelectedDbRowKey((current) => {
        if (current && items.some((item, index) => getDbBrowserRowKey(nextTable, item, index) === current)) {
          return current;
        }
        return items.length > 0 ? getDbBrowserRowKey(nextTable, items[0], 0) : '';
      });
    } catch (fetchError) {
      setDbBrowserError(fetchError instanceof Error ? fetchError.message : 'failed to load db browser');
      setDbBrowserPayload((current) => ({ ...current, table: nextTable, items: [], total: 0, has_more: false }));
      setSelectedDbRowKey('');
    } finally {
      setDbBrowserLoading(false);
    }
  }, [dbBrowserCollection, dbBrowserLimit, dbBrowserOffset, dbBrowserQ, dbBrowserRunId, dbBrowserSourceDocId, dbBrowserTable]);

  const handleCollectionSelect = useCallback((collection: Record<string, any>) => {
    const runId = String(collection.synthetic_backfill_run_id || '').trim();
    if (!runId) {
      return;
    }
    syncSelectedRunId(runId);
    if (runId === String(selectedRunId || '')) {
      void loadRunBundle(runId);
    }
    requestAnimationFrame(() => {
      detailSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, [loadRunBundle, selectedRunId, syncSelectedRunId]);

  useEffect(() => {
    if (!deepLinkedRunId || deepLinkedRunId === String(selectedRunId || '').trim()) {
      return;
    }
    setSelectedRunId(deepLinkedRunId);
  }, [deepLinkedRunId, selectedRunId]);

  useEffect(() => {
    const currentRunId = String(searchParams.get('run_id') || '').trim();
    const nextRunId = String(selectedRunId || '').trim();
    if (currentRunId === nextRunId) {
      return;
    }
    const nextSearchParams = new URLSearchParams(searchParams);
    if (nextRunId) {
      nextSearchParams.set('run_id', nextRunId);
    } else {
      nextSearchParams.delete('run_id');
    }
    setSearchParams(nextSearchParams, { replace: true });
  }, [searchParams, selectedRunId, setSearchParams]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    void loadDbBrowser({ table: 'rag_query_runs', limit: 25, offset: 0, q: '', collection: '', run_id: '', source_doc_id: '' });
  }, []);

  useEffect(() => {
    if (!selectedRunId && runs[0]?.id) {
      setSelectedRunId(String(runs[0].id));
      return;
    }
    if (selectedRunId) {
      void loadRunBundle(selectedRunId);
    }
  }, [loadRunBundle, runs, selectedRunId]);

  const selectedRun = useMemo(
    () => runs.find((item) => String(item.id) === String(selectedRunId)) ?? bundle.summary,
    [bundle.summary, runs, selectedRunId],
  );

  const selectedCollectionName = useMemo(
    () => String(selectedRun?.collection || '').trim(),
    [selectedRun],
  );

  const dbBrowserVisibleColumns = useMemo(() => {
    const currentColumns = dbBrowserPayload.columns.filter(Boolean);
    const preferred = DB_BROWSER_COLUMN_PRIORITY[dbBrowserTable] ?? [];
    const ordered = [
      ...preferred.filter((column) => currentColumns.includes(column)),
      ...currentColumns.filter((column) => !preferred.includes(column)),
    ];
    return ordered.slice(0, 8);
  }, [dbBrowserPayload.columns, dbBrowserTable]);

  const selectedDbRow = useMemo(() => {
    const rows = dbBrowserPayload.items;
    return rows.find((item, index) => getDbBrowserRowKey(dbBrowserTable, item, index) === selectedDbRowKey) ?? rows[0] ?? null;
  }, [dbBrowserPayload.items, dbBrowserTable, selectedDbRowKey]);

  const dbBrowserRangeLabel = useMemo(() => {
    if (dbBrowserPayload.total <= 0 || dbBrowserPayload.items.length === 0) {
      return '0 / 0';
    }
    const start = dbBrowserPayload.offset + 1;
    const end = dbBrowserPayload.offset + dbBrowserPayload.items.length;
    return `${start}-${end} / ${dbBrowserPayload.total}`;
  }, [dbBrowserPayload.items.length, dbBrowserPayload.offset, dbBrowserPayload.total]);

  const handleDbBrowserApply = useCallback(() => {
    setDbBrowserOffset(0);
    void loadDbBrowser({ offset: 0 });
  }, [loadDbBrowser]);

  const handleDbBrowserRefresh = useCallback(() => {
    void loadDbBrowser();
  }, [loadDbBrowser]);

  const handleDbBrowserPrev = useCallback(() => {
    const nextOffset = Math.max(0, dbBrowserOffset - dbBrowserLimit);
    setDbBrowserOffset(nextOffset);
    void loadDbBrowser({ offset: nextOffset });
  }, [dbBrowserLimit, dbBrowserOffset, loadDbBrowser]);

  const handleDbBrowserNext = useCallback(() => {
    if (!dbBrowserPayload.has_more) {
      return;
    }
    const nextOffset = dbBrowserOffset + dbBrowserLimit;
    setDbBrowserOffset(nextOffset);
    void loadDbBrowser({ offset: nextOffset });
  }, [dbBrowserLimit, dbBrowserOffset, dbBrowserPayload.has_more, loadDbBrowser]);

  const handleDbBrowserTableSelect = useCallback((table: DbBrowserTableName) => {
    setDbBrowserTable(table);
    setDbBrowserOffset(0);
    setSelectedDbRowKey('');
    void loadDbBrowser({ table, offset: 0 });
  }, [loadDbBrowser]);

  const handleDbBrowserUseSelectedContext = useCallback(() => {
    const nextCollection = String(selectedCollectionName || '').trim();
    const nextRunId = String(selectedRunId || '').trim();
    setDbBrowserCollection(nextCollection);
    setDbBrowserRunId(nextRunId);
    setDbBrowserOffset(0);
    void loadDbBrowser({ collection: nextCollection, run_id: nextRunId, offset: 0 });
  }, [loadDbBrowser, selectedCollectionName, selectedRunId]);

  const currentDeepLink = useMemo(() => {
    if (typeof window === 'undefined') return '';
    const nextUrl = new URL(window.location.href);
    const nextRunId = String(selectedRunId || '').trim();
    if (nextRunId) {
      nextUrl.searchParams.set('run_id', nextRunId);
    } else {
      nextUrl.searchParams.delete('run_id');
    }
    return nextUrl.toString();
  }, [searchParams, selectedRunId]);

  const handleCopyDeepLink = useCallback(async () => {
    const copied = await copyTextToClipboard(currentDeepLink);
    setCopyState(copied ? 'copied' : 'error');
  }, [currentDeepLink]);

  useEffect(() => {
    if (copyState === 'idle' || typeof window === 'undefined') {
      return undefined;
    }
    const timer = window.setTimeout(() => setCopyState('idle'), 1800);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  return (
    <main id="main-content" className="h-screen overflow-y-auto bg-fin-bg px-4 py-6 md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-fin-text">RAG Inspector</h1>
            <p className="text-sm text-fin-muted">查看 DeepSearch 查询回放、切片策略、命中来源、命中 chunk 与原始文档全文</p>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/workbench" className="rounded-md border border-fin-border px-3 py-2 text-sm text-fin-text hover:bg-fin-bg-secondary">
              Back to Workbench
            </Link>
            <button
              type="button"
              onClick={() => void handleCopyDeepLink()}
              disabled={!selectedRunId}
              className={[
                'rounded-md border px-3 py-2 text-sm font-medium transition-colors',
                selectedRunId
                  ? 'border-fin-border text-fin-text hover:bg-fin-bg-secondary'
                  : 'cursor-not-allowed border-fin-border/60 text-fin-muted opacity-60',
              ].join(' ')}
            >
              {copyState === 'copied' ? 'copied' : copyState === 'error' ? 'copy failed' : 'copy deep link'}
            </button>
            <button
              type="button"
              onClick={() => void loadOverview()}
              className="rounded-md bg-fin-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              Refresh
            </button>
          </div>
        </header>

        {error ? (
          <div className="rounded-xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>
        ) : null}

        <section className="grid gap-4 md:grid-cols-4">
          <SectionCard title="RAG 后端">
            <div className="text-lg font-semibold text-fin-text">{status?.backend_actual || 'unknown'}</div>
            <div className="mt-1 text-xs text-fin-muted">期望：{status?.backend_requested || 'auto'}</div>
          </SectionCard>
          <SectionCard title="向量文档数">
            <div className="text-lg font-semibold text-fin-text">{status?.doc_count ?? 0}</div>
            <div className="mt-1 text-xs text-fin-muted">vector dim：{status?.vector_dim ?? 0}</div>
          </SectionCard>
          <SectionCard title="最近 24h 查询">
            <div className="text-lg font-semibold text-fin-text">{status?.observability?.recent_run_count_24h ?? 0}</div>
            <div className="mt-1 text-xs text-fin-muted">空召回率：{formatPercent(status?.observability?.recent_empty_hits_rate_24h)}</div>
          </SectionCard>
          <SectionCard title="最近 24h fallback">
            <div className="text-lg font-semibold text-fin-text">{status?.observability?.recent_fallback_count_24h ?? 0}</div>
            <div className="mt-1 text-xs text-fin-muted">最后一次：{formatDateTime(status?.observability?.last_fallback_at)}</div>
          </SectionCard>
        </section>

        <section className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
          <SectionCard
            title="最近查询回放"
            extra={loadingOverview ? <span className="text-xs text-fin-muted">加载中…</span> : null}
          >
            <div className="mb-3 flex items-center gap-2">
              <input
                value={queryFilter}
                onChange={(event) => setQueryFilter(event.target.value)}
                placeholder="按 query 搜索"
                className="min-w-0 flex-1 rounded-md border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text outline-none"
              />
              <label className="flex items-center gap-2 text-xs text-fin-muted">
                <input type="checkbox" checked={fallbackOnly} onChange={(event) => setFallbackOnly(event.target.checked)} />
                仅 fallback
              </label>
            </div>
            <div className="space-y-2">
              {runs.length === 0 ? (
                <div className="rounded-xl border border-dashed border-fin-border px-3 py-6 text-center text-sm text-fin-muted">暂无查询记录</div>
              ) : runs.map((run) => {
                const runId = String(run.id || '');
                const active = runId === String(selectedRunId);
                return (
                  <button
                    key={runId}
                    type="button"
                    onClick={() => syncSelectedRunId(runId)}
                    className={[
                      'w-full rounded-xl border px-3 py-3 text-left transition-colors',
                      active ? 'border-fin-primary bg-fin-primary/10' : 'border-fin-border bg-fin-bg hover:bg-fin-bg-secondary',
                    ].join(' ')}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="line-clamp-2 text-sm font-medium text-fin-text">{String(run.query_text_redacted || run.query_text || '未命名查询')}</div>
                      <span className="rounded-full bg-fin-bg-secondary px-2 py-0.5 text-[11px] text-fin-muted">{String(run.backend_actual || 'unknown')}</span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-fin-muted">
                      <span>状态：{String(run.status || 'unknown')}</span>
                      <span>命中：{Number(run.retrieval_hit_count || 0)}</span>
                      <span>文档：{Number(run.source_doc_count || 0)}</span>
                      <span>chunk：{Number(run.chunk_count || 0)}</span>
                      <span>耗时：{run.latency_ms != null ? `${Number(run.latency_ms).toFixed(0)} ms` : '—'}</span>
                    </div>
                    {run.fallback_reason ? (
                      <div className="mt-2 rounded-md bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">fallback：{String(run.fallback_reason)}</div>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </SectionCard>

          <div ref={detailSectionRef} className="space-y-6">
            <SectionCard title="查询总览" extra={loadingDetail ? <span className="text-xs text-fin-muted">加载中…</span> : null}>
              {selectedRun ? (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  <div><div className="text-xs text-fin-muted">Query</div><div className="mt-1 text-sm text-fin-text">{String(selectedRun.query_text_redacted || selectedRun.query_text || '—')}</div></div>
                  <div><div className="text-xs text-fin-muted">Collection</div><div className="mt-1 text-sm text-fin-text">{String(selectedRun.collection || '—')}</div></div>
                  <div><div className="text-xs text-fin-muted">Router</div><div className="mt-1 text-sm text-fin-text">{String(selectedRun.router_decision || '—')}</div></div>
                  <div><div className="text-xs text-fin-muted">Backend</div><div className="mt-1 text-sm text-fin-text">{String(selectedRun.backend_actual || '—')}</div></div>
                  <div><div className="text-xs text-fin-muted">开始时间</div><div className="mt-1 text-sm text-fin-text">{formatDateTime(selectedRun.started_at)}</div></div>
                  <div><div className="text-xs text-fin-muted">耗时</div><div className="mt-1 text-sm text-fin-text">{selectedRun.latency_ms != null ? `${Number(selectedRun.latency_ms).toFixed(0)} ms` : '—'}</div></div>
                </div>
              ) : <div className="text-sm text-fin-muted">选择左侧查询后查看详情</div>}
            </SectionCard>

            <SectionCard title="事件时间线（含 payload）">
              <div className="space-y-2">
                {bundle.events.length === 0 ? <div className="text-sm text-fin-muted">暂无事件</div> : bundle.events.map((event) => (
                  <div key={String(event.id)} className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-fin-text">{String(event.event_type || event.stage || 'event')}</div>
                      <div className="text-[11px] text-fin-muted">#{String(event.seq_no ?? '—')}</div>
                    </div>
                    <div className="mt-1 text-xs text-fin-muted">{String(event.stage || '—')} · {formatDateTime(event.created_at)}</div>
                    <ExpandableText label="payload_json" value={jsonPreview(event.payload_json)} previewLength={320} mono />
                  </div>
                ))}
              </div>
            </SectionCard>

            <SectionCard title="命中与重排">
              <div className="space-y-3">
                {bundle.hits.length === 0 ? (
                  <div className="text-sm text-fin-muted">暂无命中结果</div>
                ) : bundle.hits.map((hit) => (
                  <div key={String(hit.id)} className="rounded-lg border border-fin-border bg-fin-bg px-3 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-medium text-fin-text">
                        chunk #{String(hit.chunk_index ?? hit.chunk_id ?? '—')}
                      </div>
                      <div className="flex flex-wrap gap-2 text-[11px] text-fin-muted">
                        <span>dense：{formatNumber(hit.dense_score)}</span>
                        <span>sparse：{formatNumber(hit.sparse_score)}</span>
                        <span>rrf：{formatNumber(hit.rrf_score)}</span>
                        <span>rerank：{formatNumber(hit.rerank_score)}</span>
                      </div>
                    </div>
                    <div className="mt-1 text-[11px] text-fin-muted">
                      {String(hit.title || hit.source_id || 'unknown')} · {String(hit.collection || '—')}
                    </div>
                    {hit.url ? (
                      <a href={String(hit.url)} target="_blank" rel="noreferrer" className="mt-1 block text-xs text-fin-primary underline-offset-2 hover:underline">
                        {String(hit.url)}
                      </a>
                    ) : null}
                    <ExpandableText label="命中预览" value={String(hit.content_preview || hit.chunk_preview || '')} previewLength={260} />
                    <ExpandableText label="命中 metadata" value={jsonPreview(hit.metadata_json)} previewLength={260} mono />
                  </div>
                ))}
              </div>
            </SectionCard>

            <section className="grid gap-6 xl:grid-cols-2">
              <SectionCard title="原始文档（含原文）">
                <div className="space-y-3">
                  {bundle.documents.length === 0 ? <div className="text-sm text-fin-muted">暂无原始文档</div> : bundle.documents.map((doc) => (
                    <div key={String(doc.id)} className="rounded-lg border border-fin-border bg-fin-bg px-3 py-3">
                      <div className="text-sm font-medium text-fin-text">{String(doc.title || doc.source_id || 'untitled')}</div>
                      <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-fin-muted">
                        <span>{String(doc.source_type || 'unknown')}</span>
                        <span>创建：{formatDateTime(doc.created_at)}</span>
                        <span>长度：{String(doc.content_length ?? '—')}</span>
                      </div>
                      {doc.url ? (
                        <a href={String(doc.url)} target="_blank" rel="noreferrer" className="mt-1 block text-xs text-fin-primary underline-offset-2 hover:underline">
                          {String(doc.url)}
                        </a>
                      ) : null}
                      <ExpandableText label="摘要预览" value={String(doc.content_preview || '')} previewLength={240} />
                      <ExpandableText label="原文全文" value={String(doc.content_raw || '')} previewLength={360} />
                      <ExpandableText label="文档 metadata" value={jsonPreview(doc.metadata_json)} previewLength={260} mono />
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard title="切片明细（含完整 chunk）">
                <div className="space-y-3">
                  {bundle.chunks.length === 0 ? <div className="text-sm text-fin-muted">暂无切片明细</div> : bundle.chunks.map((chunk) => (
                    <div key={String(chunk.id)} className="rounded-lg border border-fin-border bg-fin-bg px-3 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium text-fin-text">chunk #{String(chunk.chunk_index ?? '0')}</div>
                        <div className="text-[11px] text-fin-muted">{String(chunk.doc_type || 'unknown')}</div>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-fin-muted">
                        <span>总段数：{String(chunk.total_chunks ?? '—')}</span>
                        <span>长度：{String(chunk.chunk_length ?? '—')}</span>
                        <span>策略：{String(chunk.chunk_strategy || '—')}</span>
                        <span>size：{String(chunk.chunk_size ?? '—')}</span>
                        <span>overlap：{String(chunk.chunk_overlap ?? '—')}</span>
                        <span>char：{String(chunk.char_start ?? '—')} - {String(chunk.char_end ?? '—')}</span>
                      </div>
                      <div className="mt-1 text-[11px] text-fin-muted">来源：{String(chunk.title || chunk.source_doc_id || '—')}</div>
                      <ExpandableText label="chunk 全文" value={String(chunk.chunk_text || '')} previewLength={360} />
                      <ExpandableText label="chunk metadata" value={jsonPreview(chunk.metadata_json)} previewLength={260} mono />
                    </div>
                  ))}
                </div>
              </SectionCard>
            </section>

            <SectionCard title="Collection 浏览">
              <div className="grid gap-2 md:grid-cols-2">
                {collections.length === 0 ? <div className="text-sm text-fin-muted">暂无 collection</div> : collections.map((collection) => {
                  const collectionName = String(collection.collection || 'unknown').trim();
                  const runCount = Number(collection.run_count ?? 0);
                  const documentCount = Number(collection.document_count ?? collection.row_count ?? 0);
                  const chunkCount = Number(collection.chunk_count ?? 0);
                  const latestRunAt = collection.latest_run_at ?? collection.last_run_at ?? null;
                  const latestDocumentAt = collection.latest_document_at ?? collection.last_created_at ?? null;
                  const syntheticBackfillRunId = String(collection.synthetic_backfill_run_id || '').trim();
                  const syntheticBackfillStartedAt = collection.synthetic_backfill_started_at ?? null;
                  const clickable = Boolean(syntheticBackfillRunId);
                  const active = Boolean(collectionName) && collectionName === selectedCollectionName;
                  const cardClassName = [
                    'w-full rounded-lg border px-3 py-3 text-left transition-colors',
                    active
                      ? 'border-fin-primary bg-fin-primary/10 ring-1 ring-fin-primary/40 shadow-sm'
                      : clickable
                        ? 'cursor-pointer border-fin-border bg-fin-bg hover:border-fin-primary hover:bg-fin-bg-secondary'
                        : 'border-fin-border bg-fin-bg',
                    clickable && active ? 'cursor-pointer' : '',
                  ].join(' ');
                  const cardBody = (
                    <>
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-sm font-medium text-fin-text">{collectionName || 'unknown'}</div>
                        {active ? (
                          <span className="rounded-full bg-fin-primary/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-fin-primary">
                            selected
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-[11px] text-fin-muted">run: {String(runCount)} | doc: {String(documentCount)} | chunk: {String(chunkCount)}</div>
                      <div className="mt-1 text-[11px] text-fin-muted">latest query: {formatDateTime(latestRunAt)}</div>
                      <div className="mt-1 text-[11px] text-fin-muted">latest doc: {formatDateTime(latestDocumentAt)}</div>
                      <div className={[                        'mt-1 text-[11px]',                        clickable ? 'text-fin-primary' : 'text-fin-muted',                      ].join(' ')}>
                        {clickable
                          ? `synthetic backfill: ${formatDateTime(syntheticBackfillStartedAt)} | click to inspect`
                          : 'no synthetic backfill run'}
                      </div>
                    </>
                  );
                  return clickable ? (
                    <button
                      key={collectionName}
                      type="button"
                      onClick={() => handleCollectionSelect(collection)}
                      className={cardClassName}
                      aria-pressed={active}
                    >
                      {cardBody}
                    </button>
                  ) : (
                    <div key={collectionName} className={cardClassName}>
                      {cardBody}
                    </div>
                  );
                })}
              </div>
            </SectionCard>

            <SectionCard
              title="PostgreSQL Readonly Browser"
              extra={<span className="text-xs text-fin-muted">{dbBrowserLoading ? 'loading...' : `${dbBrowserPayload.total} rows`}</span>}
            >
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {DB_BROWSER_TABLES.map((table) => {
                    const active = table === dbBrowserTable;
                    return (
                      <button
                        key={table}
                        type="button"
                        onClick={() => void handleDbBrowserTableSelect(table)}
                        className={[
                          'rounded-md border px-3 py-1.5 text-xs font-medium transition-colors',
                          active
                            ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                            : 'border-fin-border text-fin-text hover:bg-fin-bg-secondary',
                        ].join(' ')}
                        aria-pressed={active}
                      >
                        {table}
                      </button>
                    );
                  })}
                </div>

                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">
                  <input
                    value={dbBrowserQ}
                    onChange={(event) => setDbBrowserQ(event.target.value)}
                    placeholder="search q"
                    className="min-w-0 rounded-md border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text outline-none"
                  />
                  <input
                    value={dbBrowserCollection}
                    onChange={(event) => setDbBrowserCollection(event.target.value)}
                    placeholder="collection"
                    className="min-w-0 rounded-md border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text outline-none"
                  />
                  <input
                    value={dbBrowserRunId}
                    onChange={(event) => setDbBrowserRunId(event.target.value)}
                    placeholder="run_id"
                    className="min-w-0 rounded-md border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text outline-none"
                  />
                  <input
                    value={dbBrowserSourceDocId}
                    onChange={(event) => setDbBrowserSourceDocId(event.target.value)}
                    placeholder="source_doc_id"
                    className="min-w-0 rounded-md border border-fin-border bg-fin-bg px-3 py-2 text-sm text-fin-text outline-none"
                  />
                  <label className="flex items-center gap-2 rounded-md border border-fin-border bg-fin-bg px-3 py-2 text-xs text-fin-muted">
                    <span>limit</span>
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={dbBrowserLimit}
                      onChange={(event) => setDbBrowserLimit(Math.max(1, Math.min(200, Number(event.target.value) || 25)))}
                      className="w-20 bg-transparent text-sm text-fin-text outline-none"
                    />
                  </label>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleDbBrowserUseSelectedContext()}
                    className="rounded-md border border-fin-border px-3 py-2 text-xs font-medium text-fin-text hover:bg-fin-bg-secondary"
                  >
                    use selected run
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDbBrowserApply()}
                    className="rounded-md border border-fin-border px-3 py-2 text-xs font-medium text-fin-text hover:bg-fin-bg-secondary"
                  >
                    apply filters
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDbBrowserRefresh()}
                    className="rounded-md border border-fin-border px-3 py-2 text-xs font-medium text-fin-text hover:bg-fin-bg-secondary"
                  >
                    refresh table
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDbBrowserPrev()}
                    disabled={dbBrowserOffset <= 0}
                    className={[
                      'rounded-md border px-3 py-2 text-xs font-medium transition-colors',
                      dbBrowserOffset > 0
                        ? 'border-fin-border text-fin-text hover:bg-fin-bg-secondary'
                        : 'cursor-not-allowed border-fin-border/60 text-fin-muted opacity-60',
                    ].join(' ')}
                  >
                    prev
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDbBrowserNext()}
                    disabled={!dbBrowserPayload.has_more}
                    className={[
                      'rounded-md border px-3 py-2 text-xs font-medium transition-colors',
                      dbBrowserPayload.has_more
                        ? 'border-fin-border text-fin-text hover:bg-fin-bg-secondary'
                        : 'cursor-not-allowed border-fin-border/60 text-fin-muted opacity-60',
                    ].join(' ')}
                  >
                    next
                  </button>
                  <div className="text-xs text-fin-muted">showing {dbBrowserRangeLabel}</div>
                </div>

                {dbBrowserError ? (
                  <div className="rounded-xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">{dbBrowserError}</div>
                ) : null}

                <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
                  <div className="overflow-hidden rounded-xl border border-fin-border bg-fin-bg">
                    {dbBrowserVisibleColumns.length === 0 ? (
                      <div className="px-4 py-6 text-sm text-fin-muted">No readable columns</div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-fin-border text-xs">
                          <thead className="bg-fin-card/80">
                            <tr>
                              {dbBrowserVisibleColumns.map((column) => (
                                <th key={column} className="px-3 py-2 text-left font-medium uppercase tracking-wide text-fin-muted">
                                  {column}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-fin-border/80">
                            {dbBrowserPayload.items.length === 0 ? (
                              <tr>
                                <td colSpan={Math.max(1, dbBrowserVisibleColumns.length)} className="px-3 py-6 text-sm text-fin-muted">
                                  No rows
                                </td>
                              </tr>
                            ) : dbBrowserPayload.items.map((row, index) => {
                              const rowKey = getDbBrowserRowKey(dbBrowserTable, row, index);
                              const active = rowKey === selectedDbRowKey;
                              return (
                                <tr
                                  key={rowKey}
                                  onClick={() => setSelectedDbRowKey(rowKey)}
                                  className={[
                                    'cursor-pointer align-top transition-colors',
                                    active ? 'bg-fin-primary/10' : 'hover:bg-fin-bg-secondary/70',
                                  ].join(' ')}
                                >
                                  {dbBrowserVisibleColumns.map((column) => (
                                    <td key={`${rowKey}:${column}`} className="max-w-[280px] px-3 py-2 text-fin-text">
                                      <div className={column === 'id' || column.endsWith('_id') ? 'font-mono' : ''}>
                                        {formatDbBrowserCell(row[column])}
                                      </div>
                                    </td>
                                  ))}
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  <div className="rounded-xl border border-fin-border bg-fin-bg p-3">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-fin-text">Selected Row</div>
                        <div className="text-[11px] text-fin-muted">{dbBrowserTable}</div>
                      </div>
                      {selectedDbRow ? <div className="text-[11px] text-fin-muted">{String(selectedDbRow.id ?? 'no id')}</div> : null}
                    </div>

                    {selectedDbRow ? (
                      <div className="space-y-3">
                        {DB_BROWSER_DETAIL_FIELDS[dbBrowserTable].map((field) => {
                          const rawValue = selectedDbRow[field];
                          const textValue = rawValue == null ? '' : typeof rawValue === 'string' ? rawValue : jsonPreview(rawValue);
                          return textValue.trim() ? (
                            <ExpandableText key={field} label={field} value={textValue} previewLength={360} />
                          ) : null;
                        })}
                        {'metadata_json' in selectedDbRow ? (
                          <ExpandableText label="metadata_json" value={jsonPreview(selectedDbRow.metadata_json)} previewLength={320} mono />
                        ) : null}
                        {'metadata' in selectedDbRow ? (
                          <ExpandableText label="metadata" value={jsonPreview(selectedDbRow.metadata)} previewLength={320} mono />
                        ) : null}
                        <div>
                          <div className="mb-2 text-xs font-medium text-fin-text">JSON</div>
                          <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-fin-card/50 px-3 py-2 text-xs text-fin-text">
                            {jsonPreview(selectedDbRow)}
                          </pre>
                        </div>
                      </div>
                    ) : (
                      <div className="text-sm text-fin-muted">No row selected</div>
                    )}
                  </div>
                </div>
              </div>
            </SectionCard>

          </div>
        </section>
      </div>
    </main>
  );
};

export default RagInspectorPage;
