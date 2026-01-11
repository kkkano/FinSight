import React, { useEffect, useMemo, useState } from 'react';
import type { ReportIR, ReportSection, ReportContent, Citation, Sentiment } from '../types/index';
import { ChevronDown, ChevronUp, ExternalLink, BarChart2, TrendingUp, AlertTriangle, Maximize2, X } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

const DEFAULT_USER_ID = 'default_user';

interface ReportViewProps {
  report: ReportIR;
}

const SentimentBadge: React.FC<{ sentiment: Sentiment; confidence: number }> = ({ sentiment, confidence }) => {
  const colors = {
    bullish: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200',
    bearish: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-200',
    neutral: 'bg-slate-100 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200',
  };

  const confidencePercent = Math.round(confidence * 100);

  return (
    <div className="flex items-center space-x-2">
      <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${colors[sentiment]}`}>
        {sentiment}
      </span>
      <span className="text-[11px] text-gray-500 dark:text-gray-400">{confidencePercent}% confidence</span>
    </div>
  );
};

const RecommendationBadge: React.FC<{ recommendation: string }> = ({ recommendation }) => {
  const normalized = recommendation.trim().toUpperCase();
  const styles: Record<string, string> = {
    BUY: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200',
    HOLD: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200',
    SELL: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-200',
  };
  const className = styles[normalized] ?? 'bg-slate-100 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200';

  return (
    <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide ${className}`}>
      {normalized}
    </span>
  );
};

const ConfidenceMeter: React.FC<{ score: number }> = ({ score }) => {
  const percent = Math.min(100, Math.max(0, Math.round(score * 100)));
  const level = percent >= 80 ? '高' : percent >= 60 ? '中' : '低';
  const levelColor = percent >= 80 ? 'text-emerald-600 dark:text-emerald-400' : percent >= 60 ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400';

  return (
    <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/80 dark:bg-slate-900/60 p-4">
      <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-2">
        <span className="font-semibold uppercase tracking-wider">AI Confidence</span>
        <span className="text-slate-700 dark:text-slate-200 font-semibold">{percent}%</span>
      </div>
      <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-blue-500 to-indigo-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-2 text-[10px] text-slate-400 dark:text-slate-500">
        <span className={`font-medium ${levelColor}`}>{level}置信度</span>
        <span className="mx-1">·</span>
        <span>综合 Price/News/Technical 等多源 Agent 分析结果</span>
      </div>
    </div>
  );
};

const normalizeAnchor = (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, '-');

const formatTable = (table: { headers?: string[]; rows?: string[][] }) => {
  if (!table) return '';
  const headers = table.headers || [];
  const rows = table.rows || [];
  const lines: string[] = [];
  if (headers.length > 0) {
    lines.push(headers.join(' | '));
  }
  rows.forEach((row) => {
    lines.push(row.join(' | '));
  });
  return lines.join('\n');
};

const extractDomain = (url: string) => {
  try {
    return new URL(url).hostname.replace('www.', '');
  } catch (error) {
    return url;
  }
};

const buildSourceSummary = (citations: Citation[]) => {
  const counts = new Map<string, number>();
  citations.forEach((citation) => {
    const domain = extractDomain(citation.url);
    counts.set(domain, (counts.get(domain) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([domain, count]) => ({ domain, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);
};

const pickSectionByKeywords = (sections: ReportSection[], keywords: string[]) =>
  sections.find((section) => keywords.some((kw) => section.title.toLowerCase().includes(kw)));

const extractTextItems = (contents: ReportContent[], limit: number = 4) => {
  const items: string[] = [];
  contents.forEach((content) => {
    if (items.length >= limit) return;
    if (content.type === 'text') {
      const raw = String(content.content || '');
      raw
        .split(/\n|•|·|-\s+/)
        .map((item) => item.trim())
        .filter(Boolean)
        .forEach((item) => {
          if (items.length < limit) items.push(item);
        });
    }
  });
  return items;
};

const extractCatalystItems = (sections: ReportSection[]) => {
  const section = pickSectionByKeywords(sections, ['catalyst', '催化', '驱动', '动因']);
  if (!section) return [];
  return extractTextItems(section.contents, 4);
};

const extractMetrics = (sections: ReportSection[]) => {
  const metrics: { label: string; value: string }[] = [];
  for (const section of sections) {
    for (const content of section.contents) {
      if (content.type === 'table') {
        const headers = content.content.headers || [];
        const rows = content.content.rows || [];
        if (rows.length > 0) {
          headers.slice(0, 4).forEach((header: string, idx: number) => {
            const value = rows[0][idx];
            if (header && value && metrics.length < 4) {
              metrics.push({ label: header, value });
            }
          });
        }
      }
    }
  }
  if (metrics.length > 0) return metrics;

  for (const section of sections) {
    for (const content of section.contents) {
      if (content.type === 'text') {
        const raw = String(content.content || '');
        const matches = raw.matchAll(/([A-Za-z\u4e00-\u9fff]{2,8})[:：]\s*([0-9][^，。\n]{0,12})/g);
        for (const match of matches) {
          if (metrics.length >= 4) break;
          metrics.push({ label: match[1], value: match[2] });
        }
      }
    }
  }
  return metrics;
};

const buildReportMessages = (report: ReportIR) => {
  const lines: string[] = [];
  const title = `${report.title} (${report.ticker})`;
  lines.push(title);
  lines.push(`Summary: ${report.summary}`);
  if (report.recommendation) {
    lines.push(`Recommendation: ${report.recommendation}`);
  }
  if (report.risks && report.risks.length > 0) {
    lines.push(`Risks: ${report.risks.join('; ')}`);
  }

  report.sections.forEach((section) => {
    lines.push('');
    lines.push(`${section.order}. ${section.title}`);
    section.contents.forEach((content) => {
      if (content.type === 'text') {
        lines.push(String(content.content));
      } else if (content.type === 'table') {
        lines.push(formatTable(content.content));
      } else if (content.type === 'chart') {
        lines.push('[Chart]');
      } else if (content.type === 'image') {
        lines.push('[Image]');
      }
      if (content.citation_refs && content.citation_refs.length > 0) {
        lines.push(`Sources: ${content.citation_refs.join(', ')}`);
      }
    });
  });

  if (report.citations && report.citations.length > 0) {
    lines.push('');
    lines.push('References:');
    report.citations.forEach((citation) => {
      lines.push(`${citation.source_id}. ${citation.title} - ${citation.url}`);
    });
  }

  return [
    {
      role: 'assistant',
      content: lines.join('\n'),
      timestamp: report.generated_at || new Date().toISOString(),
    },
  ];
};

const safeJsonParse = (value: string) => {
  try {
    return JSON.parse(value);
  } catch (error) {
    return null;
  }
};

const normalizeChartPayload = (payload: any) => {
  if (!payload) return null;
  if (typeof payload === 'string') {
    const parsed = safeJsonParse(payload);
    return parsed || null;
  }
  return payload;
};

const buildChartOption = (content: ReportContent) => {
  const payload = normalizeChartPayload(content.content);
  if (!payload) return null;

  if (payload.option && typeof payload.option === 'object') {
    return payload.option;
  }

  if (payload.series || payload.xAxis || payload.yAxis) {
    return payload;
  }

  const chartType = (content.metadata?.chart_type || payload.chart_type || payload.type || 'line').toString();
  const labels = payload.labels || payload.categories || payload.x || [];
  const values = payload.values || payload.data || payload.y || [];

  if (Array.isArray(payload.datasets)) {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: labels },
      yAxis: { type: 'value' },
      series: payload.datasets.map((dataset: { label?: string; data?: number[] }) => ({
        type: chartType === 'bar' ? 'bar' : 'line',
        data: dataset.data || [],
        name: dataset.label || 'Series',
        smooth: chartType !== 'bar',
      })),
    };
  }

  if (chartType === 'pie' && Array.isArray(labels) && Array.isArray(values)) {
    return {
      tooltip: { trigger: 'item' },
      series: [
        {
          type: 'pie',
          radius: ['35%', '70%'],
          data: labels.map((label: string, index: number) => ({
            name: label,
            value: values[index] ?? 0,
          })),
        },
      ],
    };
  }

  if (Array.isArray(labels) && Array.isArray(values)) {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: labels },
      yAxis: { type: 'value' },
      series: [
        {
          type: chartType === 'bar' ? 'bar' : 'line',
          data: values,
          smooth: chartType !== 'bar',
        },
      ],
    };
  }

  if (Array.isArray(payload)) {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: payload.map((_: any, index: number) => index + 1) },
      yAxis: { type: 'value' },
      series: [
        {
          type: chartType === 'bar' ? 'bar' : 'line',
          data: payload,
          smooth: chartType !== 'bar',
        },
      ],
    };
  }

  return null;
};

const SectionRenderer: React.FC<{
  section: ReportSection;
  isOpen: boolean;
  isActive: boolean;
  anchorPrefix: string;
  onToggle: () => void;
  citationMap: Map<string, Citation>;
  onCitationJump: (ref: string) => void;
}> = ({ section, isOpen, isActive, anchorPrefix, onToggle, citationMap, onCitationJump }) => {
  const sectionId = `${anchorPrefix}-section-${section.order}`;

  return (
    <div
      id={sectionId}
      data-report-anchor={anchorPrefix}
      data-section-order={section.order}
      className={`border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden bg-white dark:bg-slate-900 shadow-sm transition-all ${isActive ? 'ring-1 ring-blue-200 dark:ring-blue-500/40' : ''
        }`}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50/80 dark:bg-slate-800/60 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white flex items-center gap-2">
          <span className="h-6 w-6 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 flex items-center justify-center text-xs font-bold">
            {section.order}
          </span>
          <span className="text-left">{section.title}</span>
        </h3>
        {isOpen ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
      </button>

      <div
        className={`grid transition-all duration-300 ease-out ${isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
          }`}
      >
        <div className="overflow-hidden">
          <div className="p-4 bg-white dark:bg-slate-900 space-y-4">
            {section.contents.map((content, idx) => {
              const chartTitle = content.metadata?.title || 'Untitled';
              const imageUrl = typeof content.content === 'string' ? content.content : content.content?.url;
              const imageAlt = content.metadata?.title || content.content?.alt || 'Report visual';
              const chartOption = content.type === 'chart' ? buildChartOption(content) : null;
              const citations = content.citation_refs || [];

              return (
                <div key={idx} className="text-sm text-slate-700 dark:text-slate-200">
                  {content.type === 'text' && (
                    <p className="leading-relaxed whitespace-pre-wrap">{content.content}</p>
                  )}

                  {content.type === 'chart' && (
                    <div className="bg-slate-50 dark:bg-slate-800 p-3 rounded-lg border border-slate-200 dark:border-slate-700">
                      {chartOption ? (
                        <ReactECharts
                          option={chartOption}
                          style={{ height: 260, width: '100%' }}
                          notMerge
                          lazyUpdate
                        />
                      ) : (
                        <div className="h-[260px] flex items-center justify-center text-slate-400 flex-col">
                          <BarChart2 size={32} className="mb-2 opacity-60" />
                          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                            Chart: {chartTitle}
                          </span>
                          <span className="text-[11px] text-slate-400 mt-1">Missing chart option data.</span>
                        </div>
                      )}
                    </div>
                  )}

                  {content.type === 'table' && (
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                        <thead className="bg-slate-50 dark:bg-slate-800">
                          <tr>
                            {content.content.headers?.map((h: string, i: number) => (
                              <th key={i} className="px-3 py-2 text-left text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="bg-white dark:bg-slate-900 divide-y divide-slate-200 dark:divide-slate-700">
                          {content.content.rows?.map((row: string[], rI: number) => (
                            <tr key={rI}>
                              {row.map((cell, cI) => (
                                <td key={cI} className="px-3 py-2 whitespace-nowrap text-xs text-slate-600 dark:text-slate-300">{cell}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {content.type === 'image' && imageUrl && (
                    <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
                      <img src={imageUrl} alt={imageAlt} className="w-full h-auto" />
                    </div>
                  )}

                  {citations.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {citations.map((ref) => {
                        const citation = citationMap.get(ref);
                        return (
                          <button
                            key={ref}
                            type="button"
                            onClick={() => onCitationJump(ref)}
                            className="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900 text-[11px] text-slate-500 dark:text-slate-300 hover:border-blue-400 hover:text-blue-600 transition"
                            title={citation?.title || ref}
                          >
                            {citation?.source_id || ref}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

const InsightCard: React.FC<{
  title: string;
  items: string[];
  tone?: 'neutral' | 'risk' | 'catalyst';
  icon?: React.ReactNode;
}> = ({ title, items, tone = 'neutral', icon }) => {
  const toneClass =
    tone === 'risk'
      ? 'border-rose-200/70 bg-rose-50/70 dark:border-rose-800/60 dark:bg-rose-900/20'
      : tone === 'catalyst'
        ? 'border-emerald-200/70 bg-emerald-50/70 dark:border-emerald-800/60 dark:bg-emerald-900/20'
        : 'border-slate-200/80 bg-white/80 dark:border-slate-700/60 dark:bg-slate-900/60';

  return (
    <div className={`rounded-xl border ${toneClass} p-4 space-y-2`}>
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300">
        {icon}
        {title}
      </div>
      {items.length > 0 ? (
        <ul className="text-xs text-slate-700 dark:text-slate-200 space-y-1 list-disc list-inside">
          {items.map((item, idx) => (
            <li key={idx}>{item}</li>
          ))}
        </ul>
      ) : (
        <div className="text-xs text-slate-400">暂无结构化信息</div>
      )}
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-lg border border-slate-200/80 dark:border-slate-700/60 bg-white/80 dark:bg-slate-900/60 p-3">
    <div className="text-[11px] text-slate-500 dark:text-slate-400 uppercase tracking-wider">{label}</div>
    <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 mt-1">{value}</div>
  </div>
);

const EvidencePool: React.FC<{
  citations: Citation[];
  sourceSummary: { domain: string; count: number }[];
  anchorPrefix: string;
  activeCitation: string | null;
  onSelect: (ref: string) => void;
  onJump: (ref: string) => void;
}> = ({ citations, sourceSummary, anchorPrefix, activeCitation, onSelect, onJump }) => {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/80 dark:bg-slate-900/60 p-4 space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300">
        证据池
      </div>
      {sourceSummary.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {sourceSummary.map((item) => (
            <span
              key={item.domain}
              className="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 text-[10px] text-slate-500 dark:text-slate-300"
            >
              {item.domain} · {item.count}
            </span>
          ))}
        </div>
      )}
      <div className="space-y-2">
        {citations.map((cit) => {
          const citationId = `${anchorPrefix}-citation-${cit.source_id}`;
          const isActive = activeCitation === cit.source_id;
          return (
            <div
              key={cit.source_id}
              id={citationId}
              className={`rounded-lg border ${isActive ? 'border-blue-200 bg-blue-50/40 dark:bg-blue-900/20' : 'border-transparent'}`}
            >
              <button
                type="button"
                onClick={() => {
                  onSelect(cit.source_id);
                  onJump(cit.source_id);
                }}
                className="w-full text-left flex items-start gap-2 p-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors text-xs"
              >
                <ExternalLink size={12} className="mt-0.5 text-slate-400 flex-shrink-0" />
                <div>
                  <div className="font-medium text-blue-600 dark:text-blue-400">
                    {cit.title}
                  </div>
                  <div className="text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">
                    {cit.snippet}
                  </div>
                  {cit.published_date && (
                    <div className="text-slate-400 text-[10px] mt-1">{cit.published_date}</div>
                  )}
                </div>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export const ReportView: React.FC<ReportViewProps> = ({ report }) => {
  const { subscriptionEmail } = useStore();
  const [expandedSections, setExpandedSections] = useState<Record<number, boolean>>(
    report.sections.reduce((acc, sec) => ({ ...acc, [sec.order]: true }), {})
  );
  const [activeSection, setActiveSection] = useState<number | null>(null);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [watchlisted, setWatchlisted] = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [actionState, setActionState] = useState({ exporting: false, watchlist: false, subscribe: false });
  const [actionMessage, setActionMessage] = useState<{ tone: 'success' | 'error' | 'info'; text: string } | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const anchorPrefix = useMemo(() => normalizeAnchor(report.report_id || report.ticker || 'report'), [report.report_id, report.ticker]);
  const formattedDate = useMemo(() => {
    const date = new Date(report.generated_at);
    return Number.isNaN(date.getTime()) ? report.generated_at : date.toLocaleDateString();
  }, [report.generated_at]);

  const citationMap = useMemo(() => {
    return new Map(report.citations.map((citation) => [citation.source_id, citation]));
  }, [report.citations]);

  const catalystItems = useMemo(() => extractCatalystItems(report.sections), [report.sections]);
  const metricItems = useMemo(() => extractMetrics(report.sections), [report.sections]);
  const sourceSummary = useMemo(() => buildSourceSummary(report.citations), [report.citations]);

  useEffect(() => {
    let mounted = true;

    setWatchlisted(false);
    setSubscribed(false);
    setActiveSection(null);
    setActiveCitation(null);

    apiClient
      .getUserProfile(DEFAULT_USER_ID)
      .then((response) => {
        if (!mounted || !response?.success) return;
        const list = response.profile?.watchlist || [];
        if (Array.isArray(list) && list.includes(report.ticker)) {
          setWatchlisted(true);
        }
      })
      .catch(() => undefined);

    if (subscriptionEmail) {
      apiClient
        .listSubscriptions(subscriptionEmail)
        .then((response) => {
          if (!mounted || !response?.success) return;
          const list = response.subscriptions || [];
          const ticker = report.ticker?.toUpperCase();
          if (ticker && Array.isArray(list)) {
            const matched = list.some((sub: { ticker?: string }) => sub.ticker?.toUpperCase() === ticker);
            setSubscribed(matched);
          }
        })
        .catch(() => undefined);
    }

    return () => {
      mounted = false;
    };
  }, [report.ticker, report.report_id, subscriptionEmail]);

  useEffect(() => {
    const root = document.getElementById('chat-scroll-container');
    const sectionNodes = Array.from(
      document.querySelectorAll(`[data-report-anchor="${anchorPrefix}"]`)
    ) as HTMLElement[];

    if (sectionNodes.length === 0) return;

    const ratios = new Map<Element, number>();

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          ratios.set(entry.target, entry.isIntersecting ? entry.intersectionRatio : 0);
        });

        let bestOrder: number | null = null;
        let bestRatio = 0;

        ratios.forEach((ratio, element) => {
          if (ratio <= bestRatio) return;
          const order = Number((element as HTMLElement).dataset.sectionOrder);
          if (Number.isNaN(order)) return;
          bestOrder = order;
          bestRatio = ratio;
        });

        if (bestOrder !== null) {
          setActiveSection((prev) => (prev === bestOrder ? prev : bestOrder));
        }
      },
      {
        root,
        rootMargin: '-20% 0px -65% 0px',
        threshold: [0, 0.25, 0.5, 0.75, 1],
      }
    );

    sectionNodes.forEach((node) => {
      ratios.set(node, 0);
      observer.observe(node);
    });

    return () => observer.disconnect();
  }, [anchorPrefix]);

  const pushStatus = (tone: 'success' | 'error' | 'info', text: string) => {
    setActionMessage({ tone, text });
    setTimeout(() => setActionMessage(null), 2500);
  };

  const handleJumpToSection = (order: number) => {
    setActiveSection(order);
    setExpandedSections((prev) => ({ ...prev, [order]: true }));
    const target = document.getElementById(`${anchorPrefix}-section-${order}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleJumpToCitation = (ref: string) => {
    setActiveCitation(ref);
    const target = document.getElementById(`${anchorPrefix}-citation-${ref}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleExportPdf = async () => {
    if (actionState.exporting) return;
    setActionState((prev) => ({ ...prev, exporting: true }));
    try {
      const messages = buildReportMessages(report);
      const blob = await apiClient.exportPDF(messages, [], `${report.ticker} Report`);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report_${report.ticker}_${formattedDate}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
      pushStatus('success', 'PDF exported');
    } catch (error) {
      pushStatus('error', 'PDF export failed');
    } finally {
      setActionState((prev) => ({ ...prev, exporting: false }));
    }
  };

  const handleWatchlist = async () => {
    if (actionState.watchlist) return;
    setActionState((prev) => ({ ...prev, watchlist: true }));
    try {
      const payload = { user_id: DEFAULT_USER_ID, ticker: report.ticker };
      if (watchlisted) {
        await apiClient.removeWatchlist(payload);
        setWatchlisted(false);
        pushStatus('info', 'Removed from watchlist');
      } else {
        await apiClient.addWatchlist(payload);
        setWatchlisted(true);
        pushStatus('success', 'Saved to watchlist');
      }
    } catch (error) {
      pushStatus('error', 'Watchlist update failed');
    } finally {
      setActionState((prev) => ({ ...prev, watchlist: false }));
    }
  };

  const handleSubscribe = async () => {
    if (actionState.subscribe) return;
    const email = subscriptionEmail.trim();
    if (!email) {
      pushStatus('info', '请在设置中填写订阅邮箱');
      return;
    }
    if (subscribed) {
      pushStatus('info', 'Already subscribed');
      return;
    }
    setActionState((prev) => ({ ...prev, subscribe: true }));
    try {
      await apiClient.subscribe({
        email,
        ticker: report.ticker,
        alert_types: ['price_change', 'news'],
      });
      setSubscribed(true);
      pushStatus('success', 'Alerts subscribed');
    } catch (error) {
      pushStatus('error', 'Subscription failed');
    } finally {
      setActionState((prev) => ({ ...prev, subscribe: false }));
    }
  };

  const toggleSection = (order: number) => {
    setActiveSection(order);
    setExpandedSections((prev) => ({ ...prev, [order]: !prev[order] }));
  };

  const messageToneClass = actionMessage?.tone === 'success'
    ? 'text-emerald-600 dark:text-emerald-300'
    : actionMessage?.tone === 'error'
      ? 'text-rose-600 dark:text-rose-300'
      : 'text-slate-500 dark:text-slate-300';

  // 全屏模式渲染
  if (isFullscreen) {
    return (
      <div className="fixed inset-0 z-50 bg-white dark:bg-slate-900 overflow-auto">
        <button
          onClick={() => setIsFullscreen(false)}
          className="fixed top-4 right-4 z-[60] p-2 bg-slate-200 dark:bg-slate-700 rounded-full hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
          title="退出全屏"
        >
          <X size={20} className="text-slate-700 dark:text-slate-200" />
        </button>
        <div className="p-8 max-w-5xl mx-auto">
          {/* 复用主内容 */}
          <div className="space-y-6">
            <div className="border-b border-slate-200/80 dark:border-slate-700/70 pb-6">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mb-2">
                <span className="px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-200 font-semibold uppercase tracking-wide">
                  Deep Research
                </span>
                <span className="font-mono bg-slate-200/80 dark:bg-slate-700 px-2 py-0.5 rounded text-[11px]">{report.ticker}</span>
                <span>{formattedDate}</span>
              </div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">{report.title}</h1>
              <div className="flex flex-wrap items-center gap-2">
                <SentimentBadge sentiment={report.sentiment} confidence={report.confidence_score} />
                {report.recommendation && <RecommendationBadge recommendation={report.recommendation} />}
              </div>
              <div className="mt-4 p-4 bg-slate-50 dark:bg-slate-800 rounded-lg">
                <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed">
                  <span className="font-semibold">Core view:</span> {report.summary}
                </p>
              </div>
            </div>

            {/* 章节内容 */}
            <div className="space-y-4">
              {report.sections.map((section) => (
                <SectionRenderer
                  key={section.order}
                  section={section}
                  isOpen={!!expandedSections[section.order]}
                  isActive={activeSection === section.order}
                  anchorPrefix={anchorPrefix}
                  onToggle={() => toggleSection(section.order)}
                  citationMap={citationMap}
                  onCitationJump={handleJumpToCitation}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white/90 dark:bg-fin-panel/90 rounded-2xl shadow-[0_10px_30px_-18px_rgba(15,23,42,0.45)] border border-slate-200/80 dark:border-slate-700/70 overflow-hidden max-w-4xl mx-auto my-4 relative">
      {/* 全屏按钮 */}
      <button
        onClick={() => setIsFullscreen(true)}
        className="absolute bottom-4 right-4 z-10 p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors shadow-sm border border-slate-200 dark:border-slate-700"
        title="全屏查看报告"
      >
        <Maximize2 size={16} className="text-slate-600 dark:text-slate-300" />
      </button>

      <div className="p-6 border-b border-slate-200/80 dark:border-slate-700/70 bg-gradient-to-r from-blue-50 via-white to-indigo-50 dark:from-slate-900 dark:via-slate-900 dark:to-slate-900">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span className="px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-200 font-semibold uppercase tracking-wide">
                Deep Research
              </span>
              <span className="font-mono bg-slate-200/80 dark:bg-slate-700 px-2 py-0.5 rounded text-[11px]">{report.ticker}</span>
              <span className="text-slate-300 dark:text-slate-600">·</span>
              <span>{formattedDate}</span>
            </div>
            <div>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white">{report.title}</h2>
              {report.company_name && (
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{report.company_name}</p>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <SentimentBadge sentiment={report.sentiment} confidence={report.confidence_score} />
              {report.recommendation && <RecommendationBadge recommendation={report.recommendation} />}
            </div>
          </div>
          <div className="h-12 w-12 rounded-2xl bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
            <TrendingUp className="text-blue-600 dark:text-blue-300" size={22} />
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-[1.3fr_0.7fr]">
          <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/70 dark:bg-slate-900/60 p-4">
            <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed">
              <span className="font-semibold text-slate-900 dark:text-white">Core view:</span> {report.summary}
            </p>
          </div>
          <ConfidenceMeter score={report.confidence_score} />
        </div>

        {report.sections.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2 lg:hidden">
            {report.sections.map((section) => (
              <button
                key={section.order}
                type="button"
                onClick={() => handleJumpToSection(section.order)}
                className={`px-3 py-1 rounded-full border text-[11px] transition ${activeSection === section.order
                  ? 'border-blue-400 text-blue-600 bg-blue-50/70 dark:border-blue-500/60 dark:text-blue-200'
                  : 'border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-300 hover:border-blue-400 hover:text-blue-600'
                  }`}
              >
                {section.order}. {section.title}
              </button>
            ))}
          </div>
        )}

        {actionMessage && (
          <div className={`mt-3 text-[11px] ${messageToneClass}`}>{actionMessage.text}</div>
        )}
      </div>

      <div className="p-6 bg-slate-50/60 dark:bg-slate-900/50">
        <div className="flex flex-col lg:flex-row gap-6">
          <aside className="hidden lg:block w-48 shrink-0">
            <div className="sticky top-6 space-y-3">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300">
                章节目录
              </div>
              <div className="space-y-2">
                {report.sections.map((section) => (
                  <button
                    key={section.order}
                    type="button"
                    onClick={() => handleJumpToSection(section.order)}
                    className={`w-full text-left px-3 py-2 rounded-lg border text-[11px] transition ${activeSection === section.order
                      ? 'border-blue-400 text-blue-600 bg-blue-50/70 dark:border-blue-500/60 dark:text-blue-200'
                      : 'border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-300 hover:border-blue-400 hover:text-blue-600'
                      }`}
                  >
                    <span className="font-semibold">{section.order}.</span> {section.title}
                  </button>
                ))}
              </div>
            </div>
          </aside>

          <div className="flex-1 min-w-0 space-y-5">
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-3">
              <InsightCard
                title="风险"
                tone="risk"
                icon={<AlertTriangle size={12} className="text-rose-500" />}
                items={report.risks || []}
              />
              <InsightCard
                title="催化剂"
                tone="catalyst"
                icon={<TrendingUp size={12} className="text-emerald-500" />}
                items={catalystItems}
              />
              <div className="rounded-xl border border-slate-200/80 dark:border-slate-700/60 bg-white/80 dark:bg-slate-900/60 p-4 space-y-3">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-300">
                  <BarChart2 size={12} />
                  核心指标
                </div>
                {metricItems.length > 0 ? (
                  <div className="grid grid-cols-2 gap-2">
                    {metricItems.map((metric) => (
                      <MetricCard key={`${metric.label}-${metric.value}`} label={metric.label} value={metric.value} />
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-slate-400">暂无结构化指标</div>
                )}
              </div>
            </div>

            <div className="space-y-4">
              {report.sections.map((section) => (
                <SectionRenderer
                  key={section.order}
                  section={section}
                  isOpen={!!expandedSections[section.order]}
                  isActive={activeSection === section.order}
                  anchorPrefix={anchorPrefix}
                  onToggle={() => toggleSection(section.order)}
                  citationMap={citationMap}
                  onCitationJump={handleJumpToCitation}
                />
              ))}
            </div>
          </div>

          <aside className="hidden lg:block w-56 shrink-0">
            <div className="sticky top-6 space-y-3">
              <EvidencePool
                citations={report.citations}
                sourceSummary={sourceSummary}
                anchorPrefix={anchorPrefix}
                activeCitation={activeCitation}
                onSelect={setActiveCitation}
                onJump={handleJumpToCitation}
              />
            </div>
          </aside>
        </div>

        <div className="mt-6 lg:hidden">
          <EvidencePool
            citations={report.citations}
            sourceSummary={sourceSummary}
            anchorPrefix={anchorPrefix}
            activeCitation={activeCitation}
            onSelect={setActiveCitation}
            onJump={handleJumpToCitation}
          />
        </div>
      </div>

      <div className="px-6 py-4 bg-slate-50 dark:bg-slate-900/80 border-t border-slate-200/80 dark:border-slate-700/70 flex flex-wrap items-center justify-between gap-3 text-[11px] text-slate-500 dark:text-slate-400">
        <span>Generated by FinSight AI ? Deep Research Engine</span>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleExportPdf}
            disabled={actionState.exporting}
            className="px-3 py-1 rounded-full border border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900 text-slate-600 dark:text-slate-300 text-[11px] hover:border-blue-400 hover:text-blue-600 transition disabled:opacity-60"
          >
            {actionState.exporting ? 'Exporting...' : 'Export PDF'}
          </button>
          <button
            type="button"
            onClick={handleWatchlist}
            disabled={actionState.watchlist}
            className="px-3 py-1 rounded-full border border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900 text-slate-600 dark:text-slate-300 text-[11px] hover:border-blue-400 hover:text-blue-600 transition disabled:opacity-60"
          >
            {watchlisted ? 'Remove Watchlist' : 'Save to Watchlist'}
          </button>
          <button
            type="button"
            onClick={handleSubscribe}
            disabled={actionState.subscribe}
            className="px-3 py-1 rounded-full border border-blue-200 dark:border-blue-700/60 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-200 text-[11px] hover:opacity-90 transition disabled:opacity-60"
          >
            {subscribed ? 'Subscribed' : 'Subscribe Alerts'}
          </button>
          <span className="text-[10px] text-slate-400">ID: {report.report_id}</span>
        </div>
      </div>
    </div>
  );
};
