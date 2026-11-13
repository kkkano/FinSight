import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Maximize2, Table2, X } from 'lucide-react';
import type { ECharts } from 'echarts';
import EChart from '../charts/EChart';
import type { ResearchArtifact } from '../../types/runtime';
import { useStore } from '../../store/useStore';
import type { EvidenceItem } from '../../types';
import { chartSources, formatChartTimestamp } from '../../utils/chartSources';
import styles from './ChatDesign.module.css';
import { artifactTheme, artifactColumnLabel, artifactValueLabel, artifactMethodRows, buildArtifactChart, buildArtifactPanels } from "./ResearchArtifactView.utils";

function exportRows(artifact: ResearchArtifact) {
  const rows = Array.isArray(artifact.data?.rows) ? artifact.data.rows.filter((row) => row && typeof row === 'object') : [];
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const cell = (value: unknown) => {
    let text = value === null || value === undefined ? '' : String(value);
    if (typeof value === 'string' && /^[=+@-]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  };
  const data = [columns.map(cell).join(','), ...rows.map((row) => columns.map((key) => cell(row[key])).join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + data], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = artifact.artifact_id + '.csv'; anchor.click();
  URL.revokeObjectURL(url);
}

export function ResearchArtifactView({ artifact, sources = [] }: { artifact: ResearchArtifact; sources?: EvidenceItem[] }) {
  const dark = useStore((state) => state.theme === 'dark');
  const convention = useStore((state) => state.colorConvention);
  const [showData, setShowData] = useState(artifact.kind === 'table');
  const [expanded, setExpanded] = useState(false);
  const instance = useRef<ECharts | null>(null);
  const figure = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!expanded) return;
    const previous = document.activeElement as HTMLElement | null;
    const controls = () => Array.from(figure.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], [tabindex="0"]') ?? []);
    controls()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setExpanded(false); }
      if (event.key !== 'Tab') return;
      const items = controls(); const first = items[0]; const last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, [expanded]);
  const option = useMemo(() => buildArtifactChart(artifact, dark, convention), [artifact, dark, convention]);
  const panels = useMemo(() => buildArtifactPanels(artifact, dark, convention), [artifact, dark, convention]);
  const rows = Array.isArray(artifact.data?.rows) ? artifact.data.rows.filter((row) => row && typeof row === 'object') : [];
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 12);
  const usedSources = chartSources(artifact.source_refs, sources);
  const sourceNames = [...new Set(usedSources.map((source) => source.name))].join('、');
  const timestamps = [...new Set(usedSources.flatMap((source) => source.timestamps))];
  const asOf = timestamps.join('、') || formatChartTimestamp(typeof artifact.method?.as_of === 'string' ? artifact.method.as_of : undefined);
  const code = typeof artifact.method?.code === 'string' ? artifact.method.code : '';
  const methodRows = artifactMethodRows(artifact.method);
  const windows = (artifact.spec?.annotations ?? []).filter((item) => item.start !== undefined && item.end !== undefined);
  return <figure ref={figure} role={expanded ? 'dialog' : undefined} aria-modal={expanded || undefined} className={`research-artifact ${styles.artifact} ${expanded ? `${styles.artifactExpanded} research-artifact-expanded` : ''}`} aria-label={artifact.title}>
    <div className="research-artifact-header flex items-center flex-wrap">
      <figcaption className={`min-w-0 flex-1 ${styles.artifactTitle}`}>{artifact.title}
        {(sourceNames || asOf) && <p className={styles.artifactSubtitle}>{[sourceNames, asOf].filter(Boolean).join(' · ')}</p>}</figcaption>
      <button type="button" onClick={() => setShowData(!showData)} className={`artifact-action ${styles.composerAction}`} aria-pressed={showData} title="查看数据"><Table2 size={15} /><span>数据</span></button>
      <button type="button" onClick={() => {
        if (showData || !instance.current) exportRows(artifact);
        else { const a = document.createElement('a'); a.href = instance.current.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: artifactTheme(dark, convention).background }); a.download = artifact.artifact_id + '.png'; a.click(); }
      }} disabled={!rows.length} className={`artifact-action ${styles.composerAction}`} title={panels.length && !showData ? '下载主图' : '下载图表或数据'}><Download size={15} /><span>{panels.length && !showData ? '下载主图' : '下载'}</span></button>
      <button type="button" className={`artifact-action ${styles.composerAction}`} aria-label={expanded ? '收起图表' : '放大图表'} onClick={() => setExpanded(!expanded)}>
        {expanded ? <X size={15} /> : <Maximize2 size={15} />}
      </button>
    </div>
    {showData ? <div className="max-h-[420px] overflow-auto p-3"><table className="w-full text-xs">
      <thead><tr>{columns.map((key) => <th className="border-b border-t-border px-3 py-2 text-left font-medium" key={key}>{artifactColumnLabel(artifact, key)}</th>)}</tr></thead>
      <tbody>{rows.slice(0, 200).map((row, i) => <tr key={i}>{columns.map((key) => <td key={key} className="border-b border-t-divider px-3 py-2 num">{artifactValueLabel(key, row[key])}</td>)}</tr>)}</tbody>
    </table>{rows.length > 200 && <p className="pt-3 text-t-text3">显示前200行；下载包含完整数据。</p>}</div>
      : option ? <><EChart option={option} onChartReady={(chart) => { instance.current = chart; }} style={{ height: expanded ? '55vh' : 'clamp(220px,32vw,292px)' }} />
          {windows.length > 0 && <details className="border-t border-t-divider px-4 py-2 text-xs text-t-text3">
            <summary className="cursor-pointer">{windows.length} 个区间 · 编号对应主图</summary>
            <ol className="mt-2 grid gap-2 sm:grid-cols-2">{windows.map((window, index) => <li key={index}>
              <span className="font-medium text-t-text">区间{index + 1}</span> · {window.label}<br />{String(window.start)} → {String(window.end)}
            </li>)}</ol>
          </details>}
          {panels.length > 0 && <><p className="px-4 pb-1 pt-2 text-xs text-t-text3">各区间独立纵轴，展示各自的实际价格。</p><div className={styles.artifactPanels} aria-label="历史区间对照">
            {panels.map((panel, index) => <section key={panel.title + ':' + index} className="min-w-0 overflow-hidden rounded-lg border border-t-border px-2 pt-2" aria-label={panel.title}>
              <h4 className="px-1 text-xs font-medium text-t-text">{panel.title}</h4>
              {panel.baselineIncluded && <p className="px-1 text-[11px] text-t-text3">含前一期基准{typeof panel.periods === 'number' ? ` · ${panel.periods} 个下跌周期` : ''}</p>}
              <EChart option={panel.option} style={{ height: 110 }} />
            </section>)}
          </div></>}
          {(artifact.data?.panels?.length ?? 0) > 6 && <p className="px-4 pb-3 text-xs text-t-text3">展示前6个区间，其余区间可查看完整数据。</p>}
        </>
        : <p className="p-5 text-sm text-t-text3">暂无可绘图的数据。</p>}
    <div className="border-t border-t-divider px-4 py-2 text-xs leading-5 text-t-text3">
      {artifact.spec?.scale === 'log' && <span className="mr-3">对数坐标</span>}
      {typeof artifact.method?.frequency === 'string' && <span className="mr-3">{artifactValueLabel('frequency', artifact.method.frequency)}</span>}
      {(artifact.limitations ?? []).map((item) => <p key={item}>{item}</p>)}
      {usedSources.length > 0 && <span>{usedSources.length} 个数据来源</span>}
      {!usedSources.length && (artifact.source_refs?.length ?? 0) > 0 && <span>数据来源未注明</span>}
      <details className="mt-2"><summary className="cursor-pointer">查看代码和数据</summary>
        {methodRows.length > 0 && <table className={`${styles.detailTable} mt-2`}><tbody>{methodRows.map((row) => <tr key={row.label}>
          <th>{row.label}</th><td>{row.value}</td></tr>)}</tbody></table>}
        {code && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-t-bg p-3 font-mono text-xs">{code}</pre>}
        {typeof artifact.method?.description === 'string' && <p>{artifact.method.description}</p>}
        <button type="button" className="mt-2 text-t-accent" onClick={() => setShowData(true)}>查看数据（{rows.length} 行）</button>
        {!code && <p className="mt-1">没有附上计算代码。</p>}
      </details>
    </div>
  </figure>;
}
