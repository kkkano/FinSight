/**
 * 证据质量诊断抽屉组件
 *
 * 展示报告质量缺口、Verifier 核查结果和引用片段，
 * 支持按焦点关键词过滤定位相关证据。
 */

import { useEffect, useMemo, useState } from 'react';

import type { VerifierClaim, CitationSnippet } from '../../utils/reportParsing';
import {
  normalizeCitationSnippet,
  tokenizeFocusHint,
  snippetMatchesFocus,
  formatPublishedDate,
  resolveFocusHintFromRequirement,
} from '../../utils/reportParsing';

// ==================== Props 接口 ====================

export interface WorkbenchQualityDrawerProps {
  open: boolean;
  onClose: () => void;
  qualityMissing: string[];
  verifierClaims: VerifierClaim[];
  citations: Record<string, unknown>[];
  initialFocusHint?: string | null;
}

// ==================== 组件 ====================

export function WorkbenchQualityDrawer({
  open,
  onClose,
  qualityMissing,
  verifierClaims,
  citations,
  initialFocusHint,
}: WorkbenchQualityDrawerProps) {
  const [focusHint, setFocusHint] = useState<string | null>(initialFocusHint ?? null);

  useEffect(() => {
    if (!open) return;
    setFocusHint(initialFocusHint ?? null);
  }, [open, initialFocusHint]);

  const snippets = useMemo(
    () => (citations || []).map((citation, idx) => normalizeCitationSnippet(citation, idx)),
    [citations],
  );
  const focusTokens = useMemo(() => tokenizeFocusHint(focusHint), [focusHint]);
  const focusedSnippets = useMemo(
    () => snippets.filter((item) => snippetMatchesFocus(item, focusTokens)),
    [snippets, focusTokens],
  );
  const snippetsToDisplay = useMemo(() => {
    if (focusTokens.length === 0) return snippets.slice(0, 10);
    return (focusedSnippets.length > 0 ? focusedSnippets : snippets).slice(0, 10);
  }, [focusTokens, focusedSnippets, snippets]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/45" role="dialog" aria-modal="true">
      <div className="w-full max-w-lg h-full bg-fin-card border-l border-fin-border shadow-2xl overflow-y-auto" data-testid="workbench-quality-drawer">
        <div className="sticky top-0 z-10 px-4 py-3 border-b border-fin-border bg-fin-card/95 backdrop-blur">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-fin-text">证据质量诊断</h3>
              <p className="text-2xs text-fin-muted mt-0.5">不走"问这条"链路，直接定位证据片段。</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-fin-muted hover:text-fin-text transition-colors"
            >
              关闭
            </button>
          </div>
        </div>

        <div className="p-4 space-y-4">
          {qualityMissing.length > 0 && (
            <section className="rounded-lg border border-fin-warning/40 bg-fin-warning/10 p-3">
              <div className="text-xs font-semibold text-fin-warning">质量门槛缺口</div>
              <div className="mt-2 space-y-2">
                {qualityMissing.map((item, idx) => (
                  <div key={`${idx}-${item}`} className="text-xs text-fin-text/85">
                    <div className="flex items-start gap-2">
                      <span className="text-fin-warning mt-0.5">•</span>
                      <span className="flex-1">{item}</span>
                      <button
                        type="button"
                        className="shrink-0 px-2 py-0.5 rounded border border-fin-border text-fin-primary hover:bg-fin-primary/10 transition-colors"
                        onClick={() => setFocusHint(resolveFocusHintFromRequirement(item))}
                      >
                        定位片段
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {verifierClaims.length > 0 && (
            <section className="rounded-lg border border-fin-danger/40 bg-fin-danger/10 p-3">
              <div className="text-xs font-semibold text-fin-danger">Verifier 核查缺口</div>
              <div className="mt-2 space-y-2">
                {verifierClaims.map((item, idx) => (
                  <div key={`${idx}-${item.claim}`} className="rounded border border-fin-danger/30 bg-fin-card/70 p-2 text-xs">
                    <div className="text-fin-text font-medium">{item.claim}</div>
                    <div className="mt-1 text-fin-text/75">{item.reason}</div>
                    <button
                      type="button"
                      className="mt-2 px-2 py-0.5 rounded border border-fin-border text-fin-primary hover:bg-fin-primary/10 transition-colors"
                      onClick={() => setFocusHint(item.claim)}
                    >
                      定位片段
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="rounded-lg border border-fin-border bg-fin-card/70" data-testid="workbench-quality-snippets">
            <div className="px-3 py-2 border-b border-fin-border/60 flex items-center justify-between">
              <span className="text-xs font-medium text-fin-text">引用片段</span>
              {focusTokens.length > 0 && (
                <span className="text-2xs text-fin-warning">
                  {focusedSnippets.length > 0
                    ? `已定位 ${focusedSnippets.length} 条相关证据`
                    : '未找到完全匹配，已展示最近证据'}
                </span>
              )}
            </div>
            <div className="divide-y divide-fin-border/60">
              {snippetsToDisplay.length === 0 && (
                <div className="px-3 py-4 text-xs text-fin-muted">暂无可展示引用片段。</div>
              )}
              {snippetsToDisplay.map((item: CitationSnippet) => {
                const focused = focusTokens.length > 0 && snippetMatchesFocus(item, focusTokens);
                return (
                  <div
                    key={item.id}
                    className={`px-3 py-2 ${focused ? 'bg-fin-warning/10' : ''}`}
                    data-testid="workbench-quality-snippet-item"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs text-fin-text truncate">{item.title}</div>
                      <span className="text-2xs text-fin-muted shrink-0">{formatPublishedDate(item.publishedDate)}</span>
                    </div>
                    <div className="mt-1 text-2xs text-fin-muted leading-relaxed">{item.snippet}</div>
                    <div className="mt-1 flex items-center justify-between gap-2">
                      <span className="text-2xs text-fin-muted truncate">{item.source}</span>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-2xs text-fin-primary hover:underline shrink-0"
                        >
                          查看原文
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
      <button type="button" aria-label="close" className="flex-1 cursor-default" onClick={onClose} />
    </div>
  );
}
