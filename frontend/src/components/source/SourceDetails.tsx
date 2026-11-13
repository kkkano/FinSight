import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import type { EvidenceItem } from '../../types';
import { sourceTitleDisplayName } from '../../utils/sourceDisplayName';
import { publicSourceText, sourceDetailRows } from "./SourceDetails.utils";

/** 无文章地址的数据来源也能展开查看已保存的出处、时点和计算口径。 */
export function SourceDetails({ source, index, className, focused = false }: {
  source: EvidenceItem; index: number; className?: string; focused?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => { if (focused) setExpanded(true); }, [focused]);
  const title = sourceTitleDisplayName(source.title, source.source_name || source.source);
  const snippet = source.snippet?.trim();
  const prose = snippet && !/^[{[]/.test(snippet) ? publicSourceText(snippet) : null;
  return <div>
    <button type="button" className={`${className || ''} w-full text-left`} aria-label={`查看来源 ${index + 1} 详情`}
      aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
      <span className="num text-t-accent">{index + 1}</span><span>{title}</span>
      {expanded ? <ChevronDown size={13} className="ml-auto shrink-0" /> : <ChevronRight size={13} className="ml-auto shrink-0" />}
    </button>
    {expanded && <div className="my-1 rounded-lg border border-t-border bg-t-bg p-3 text-xs leading-6 text-t-text2" data-testid="source-details">
      <dl>{sourceDetailRows(source).map((row) => <div className="flex gap-3" key={row.label}>
        <dt className="shrink-0 text-t-text3">{row.label}</dt><dd className="min-w-0 break-words">{row.value}</dd>
      </div>)}</dl>
      {prose && <p className="mt-2 whitespace-pre-wrap break-words">{prose}</p>}
      {source.limitations?.map((limitation, position) => <p className="mt-1 break-words text-t-text3" key={position}>{publicSourceText(limitation)}</p>)}
      {source.url ? <a href={source.url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-t-accent">
        打开原始资料 <ExternalLink size={12} />
      </a> : <p className="mt-2 text-t-text3">这份数据没有单独的原文链接。</p>}
    </div>}
  </div>;
}
