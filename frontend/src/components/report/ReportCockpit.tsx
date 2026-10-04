import React, { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertTriangle, ChevronDown, ChevronUp, Diamond } from 'lucide-react';
import type { ReportIR, Sentiment, CoreViewpoint, Citation } from '../../types/index';
import type { BadgeInfo } from './ReportUtils';
import { normalizeMarkdown } from '../../utils/markdown';
import { SynthesisReportBlock } from './ReportCharts';
import { getReportPresentation } from './ReportPresentation';
import { QualityBadge } from './QualityBadge';

/**
 * ReportCockpit — 方案A「紧凑指挥台」布局。
 *
 * 治「笨重」：摘要横向化（stat 带一行看全）+ agent 横卡 + 左报告右侧栏，
 * 少边框多留白，全部使用 fin-* 设计 token（亮暗同构）。
 * 数据全部来自现有 ReportIR 字段，不依赖后端改动。
 */

/* ---------- helpers ---------- */

const SENTIMENT_TONE: Record<Exclude<Sentiment, 'unknown'>, string> = {
  bullish: 'text-fin-success',
  bearish: 'text-fin-danger',
  neutral: 'text-fin-text-secondary',
};

const RATING_TONE: Record<string, string> = {
  BUY: 'text-fin-success',
  HOLD: 'text-fin-primary',
  SELL: 'text-fin-danger',
};

const AGENT_CN: Record<string, string> = {
  price_agent: '价格分析',
  technical_agent: '技术分析',
  fundamental_agent: '基本面',
  news_agent: '新闻研报',
  macro_agent: '宏观',
  risk_agent: '风险',
  sentiment_agent: '情绪',
  deep_search_agent: '深度搜索',
};

const agentLabel = (key: string): string =>
  AGENT_CN[key] || key.replace(/_agent$/i, '').replace(/_/g, ' ');

/** 派生 agent 视觉状态（成功/降级/未跑/失败 → 颜色 + 文字） */
const agentVisual = (status: NonNullable<ReportIR['agent_status']>[string]) => {
  if (status?.status === 'success') return { tone: 'text-fin-success', label: '已完成' };
  if (status?.status === 'fallback') return { tone: 'text-fin-primary', label: '已降级' };
  if (status?.status === 'not_run') return { tone: 'text-fin-muted', label: '未执行' };
  return { tone: 'text-fin-danger', label: '失败' };
};

const VIEWPOINT_TONE: Record<string, string> = {
  price_agent: 'var(--fin-success)',
  technical_agent: 'rgb(var(--fin-primary))',
  fundamental_agent: 'var(--fin-predict)',
  news_agent: 'var(--fin-warning)',
  macro_agent: 'var(--fin-predict)',
  deep_search_agent: 'var(--fin-danger)',
};
const viewpointTone = (key: string): string => VIEWPOINT_TONE[key] || 'rgb(var(--fin-primary))';

/* ---------- core viewpoint (fin-* 内联) ---------- */

const ViewpointRow: React.FC<{ vp: CoreViewpoint }> = ({ vp }) => {
  const [open, setOpen] = useState(false);
  const tone = viewpointTone(vp.agent_name);
  const hasDetail = Boolean(vp.detail && vp.detail.trim().length > vp.headline.length + 30);
  return (
    <div className="rounded-xl bg-fin-bg-secondary px-4 py-3" style={{ borderLeft: `3px solid ${tone}` }}>
      {/* 头部：观点标签与来源数量。 */}
      <div className="flex items-center justify-between gap-3 mb-1.5">
        <span className="text-xs font-bold tracking-wide" style={{ color: tone }}>
          {vp.title}
        </span>
        <span className="shrink-0 text-[10.5px] text-fin-muted tabular-nums">
          {vp.evidence_count > 0 && `${vp.evidence_count} 条来源`}
        </span>
      </div>

      {/* headline 结论 */}
      <p className="text-[13px] text-fin-text leading-relaxed">{vp.headline}</p>

      {/* detail —— markdown 渲染（折叠） */}
      {hasDetail && open && (
        <div className="mt-2.5 pt-2.5 border-t border-fin-border">
          <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed text-fin-text-secondary prose-headings:text-fin-text prose-headings:text-[13px] prose-headings:font-semibold prose-headings:mt-2 prose-headings:mb-1 prose-strong:text-fin-text prose-p:my-1.5 prose-li:my-0.5 prose-ol:my-1 prose-ul:my-1 prose-a:text-fin-primary">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                /* 移动端：markdown 表格加横向滚动容器，避免窄屏溢出 */
                table: ({ children }) => (
                  <div className="overflow-x-auto scrollbar-hide">
                    <table>{children}</table>
                  </div>
                ),
              }}
            >
              {normalizeMarkdown(vp.detail)}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* 底部：展开按钮 + 数据源 tags */}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {hasDetail && (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="flex items-center gap-0.5 text-[10.5px] font-medium text-fin-muted hover:text-fin-primary transition-colors"
          >
            {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            {open ? '收起详情' : '展开详情'}
          </button>
        )}
        {(vp.data_sources || []).slice(0, 4).map((src) => (
          <span
            key={src}
            className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-fin-primary/10 text-fin-primary"
          >
            {src}
          </span>
        ))}
      </div>
    </div>
  );
};

/* ---------- props ---------- */

export interface ReportCockpitProps {
  report: ReportIR;
  formattedDate: string;
  evidenceBadges: { quality: BadgeInfo; freshness: BadgeInfo };
  metricItems: { label: string; value: string }[];
}

export const ReportCockpit: React.FC<ReportCockpitProps> = ({
  report,
  formattedDate,
  evidenceBadges,
  metricItems,
}) => {
  const [synthExpanded, setSynthExpanded] = useState(false);

  const presentation = getReportPresentation(report);
  const sentiment = presentation.sentiment;
  const rating = sentiment ? (report.recommendation || '').trim().toUpperCase() : '';
  const agentEntries = useMemo(
    () => Object.entries(report.agent_status || {}),
    [report.agent_status],
  );
  const successCount = useMemo(
    () => agentEntries.filter(([, s]) => s?.status === 'success' || s?.status === 'fallback').length,
    [agentEntries],
  );
  const viewpoints = report.core_viewpoints || [];
  const risks = report.risks || [];
  const citations: Citation[] = report.citations || [];
  const synthesis = (report as any).synthesis_report || '';

  /* stat 带：均为确定存在的字段 */
  const stats = [
    { kind: 'text' as const, k: '回答状态', value: presentation.answerLabel },
    { kind: 'rating' as const, k: '投资评级', value: rating || '—' },
    { kind: 'text' as const, k: '引用来源', value: evidenceBadges.quality.label },
    { kind: 'text' as const, k: '分析执行', value: `${successCount}/${agentEntries.length || '—'}` },
  ];

  return (
    <div className="flex flex-col gap-5">
      {/* ===== Header 条 ===== */}
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3 pb-4 border-b border-fin-border">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h2 className="text-[28px] font-extrabold tracking-tight text-fin-text leading-none">{report.ticker}</h2>
            {rating && (
              <span className={`px-3 py-1 rounded-full text-sm font-bold bg-fin-primary/10 ${RATING_TONE[rating] || 'text-fin-primary'}`}>
                {rating}
              </span>
            )}
          </div>
          <div className="mt-1.5 text-[11.5px] text-fin-muted">
            DEEP RESEARCH · 数据时效 {formattedDate}
            {report.company_name ? ` · ${report.company_name}` : ' · 深度研究报告'}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 ml-auto">
          <span className={`text-[11.5px] font-semibold ${sentiment ? SENTIMENT_TONE[sentiment] : 'text-fin-muted'}`}>{presentation.judgmentLabel}</span>
          <span className="px-2.5 py-1 rounded-md text-[11px] font-medium bg-fin-primary/10 text-fin-primary border border-fin-primary/25">
            {evidenceBadges.quality.label}
          </span>
          <span className="px-2.5 py-1 rounded-md text-[11px] font-medium bg-fin-bg-secondary text-fin-text-secondary border border-fin-border">
            {evidenceBadges.freshness.label}
          </span>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-sm leading-relaxed text-fin-text">总体结论：{presentation.summary}</p>
        <QualityBadge quality={presentation.quality} />
      </div>

      {/* ===== 横向 stat 带 ===== */}
      <div className="grid grid-cols-2 sm:grid-cols-4 rounded-2xl border border-fin-border bg-fin-card overflow-hidden">
        {stats.map((s, i) => (
          <div key={s.k} className={`flex items-center gap-3 px-4 py-3.5 ${i < stats.length - 1 ? 'sm:border-r border-fin-border' : ''} ${i % 2 === 0 ? 'border-r sm:border-r' : ''} border-fin-border`}>
            <div className="min-w-0">
              <div className="text-[11px] text-fin-muted font-medium">{s.k}</div>
              <div
                className={`mt-0.5 font-extrabold tabular-nums truncate ${
                  s.kind === 'rating'
                    ? `text-xl ${RATING_TONE[s.value as string] || 'text-fin-text'}`
                    : 'text-lg text-fin-text'
                }`}
                style={{ fontFamily: 'var(--font-mono, ui-monospace, monospace)' }}
              >
                {s.value}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ===== agent 横卡 ===== */}
      {agentEntries.length > 0 && (
        <details className="rounded-xl border border-fin-border p-3">
          <summary className="cursor-pointer text-xs font-medium text-fin-muted">执行详情 · {successCount}/{agentEntries.length} 已完成</summary>
          <div className="mt-3 grid grid-cols-2 gap-2.5">
          {agentEntries.map(([key, status]) => {
            const v = agentVisual(status);
            const eq = status?.evidence_quality?.overall_score;
            const dur = typeof status?.duration_ms === 'number' ? status.duration_ms : null;
            return (
              <div key={key} className="rounded-xl border border-fin-border bg-fin-card px-3 py-2.5">
                <div className="flex items-center justify-between text-xs font-bold mb-1.5">
                  <span className={v.tone}>{agentLabel(key)}</span>
                  <span className={`tabular-nums ${v.tone}`} style={{ fontFamily: 'var(--font-mono, monospace)' }}>
                    {v.label}
                  </span>
                </div>
                <div className="mt-1.5 flex items-center justify-between text-[10px] text-fin-muted tabular-nums">
                  <span>内部证据评分 {typeof eq === 'number' ? eq.toFixed(2) : '未评分'}</span>
                  <span>{dur !== null ? (dur >= 1000 ? `${(dur / 1000).toFixed(1)}s` : `${dur}ms`) : '—'}</span>
                </div>
              </div>
            );
          })}
          </div>
        </details>
      )}

      {/* ===== 综合研究报告（全宽主体，避免被侧栏挤成窄长条） ===== */}
      {synthesis && (
        <SynthesisReportBlock
          synthesisReport={synthesis}
          isExpanded={synthExpanded}
          onToggle={() => setSynthExpanded((p) => !p)}
          onExpand={() => setSynthExpanded(true)}
          onCollapse={() => setSynthExpanded(false)}
        />
      )}

      {/* ===== 核心观点（全宽，detail 长文宽敞展开） ===== */}
      {viewpoints.length > 0 && (
        <div className="space-y-2.5">
          <div className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-fin-muted">核心观点</div>
          {viewpoints.map((vp) => (
            <ViewpointRow key={vp.agent_name} vp={vp} />
          ))}
        </div>
      )}

      {/* ===== 风险 · 指标 · 证据（底部 3 列横排） ===== */}
      <div className="grid md:grid-cols-3 gap-4 items-start">
          <div className="rounded-2xl border border-fin-border bg-fin-card p-4">
            <div className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.1em] text-fin-muted mb-3">
              <AlertTriangle size={12} className="text-fin-danger" />
              风险提示
            </div>
            <ul className="space-y-0">
              {risks.length > 0 ? (
                risks.map((r, i) => (
                  <li
                    key={i}
                    className="flex gap-2 text-xs text-fin-text-secondary leading-relaxed py-2 border-b border-fin-border last:border-0"
                  >
                    <span className="text-fin-danger shrink-0">▸</span>
                    <span>{r}</span>
                  </li>
                ))
              ) : (
                <li className="text-xs text-fin-muted">暂无</li>
              )}
            </ul>
          </div>

          <div className="rounded-2xl border border-fin-border bg-fin-card p-4">
            <div className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-fin-muted mb-3">核心指标</div>
            <div className="space-y-2.5">
              {metricItems.length > 0 ? (
                metricItems.map((m) => (
                  <div key={`${m.label}-${m.value}`} className="flex items-baseline justify-between text-[12.5px]">
                    <span className="text-fin-muted">{m.label}</span>
                    <span className="font-bold text-fin-text tabular-nums" style={{ fontFamily: 'var(--font-mono, monospace)' }}>
                      {m.value}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-xs text-fin-muted">暂无</div>
              )}
            </div>
          </div>

          {citations.length > 0 && (
            <div className="rounded-2xl border border-fin-border bg-fin-card p-4">
              <div className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-fin-muted mb-3">
                证据池 · {citations.length}
              </div>
              <div className="space-y-2.5">
                {citations.slice(0, 6).map((c) => (
                    <div key={c.source_id} className="flex items-center gap-2 text-[11.5px]">
                      <Diamond size={9} className="text-fin-muted shrink-0" />
                      <span className="flex-1 truncate text-fin-text-secondary" title={c.title}>
                        {c.title}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}
      </div>
    </div>
  );
};
