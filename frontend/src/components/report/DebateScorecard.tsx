import React from 'react';
import { ChevronDown, HelpCircle, Scale } from 'lucide-react';

import type { DebateArtifact } from '../../types/index';

export interface DebateScorecardProps {
  debate?: DebateArtifact | null;
}

const formatScore = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A';
  const normalized = value > 1 ? value : value * 100;
  return String(Math.round(Math.max(0, Math.min(100, normalized))));
};

const stringList = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
};

export const DebateScorecard: React.FC<DebateScorecardProps> = ({ debate }) => {
  const disagreements = stringList(debate?.key_disagreements);
  const openQuestions = stringList(debate?.open_questions);

  return (
    <details className="group rounded-xl border border-fin-border bg-fin-card overflow-hidden" open>
      <summary className="px-4 py-3 cursor-pointer hover:bg-fin-hover transition-colors flex items-center gap-2">
        <ChevronDown size={16} className="text-fin-muted group-open:rotate-180 transition-transform" />
        <Scale size={15} className="text-fin-primary" />
        <span className="text-sm font-semibold text-fin-text">多空辩论</span>
        <span className="ml-auto text-2xs text-fin-muted">{debate?.status || 'missing'}</span>
      </summary>

      {!debate ? (
        <div className="px-4 pb-4">
          <div className="rounded-lg border border-dashed border-fin-border bg-fin-bg-secondary/60 px-3 py-3 text-xs text-fin-muted">
            暂无多空辩论结果
          </div>
        </div>
      ) : (
        <div className="px-4 pb-4 space-y-3">
          {debate.status === 'skipped' && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-200">
              辩论已跳过{debate.reason ? `：${debate.reason}` : ''}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 dark:border-emerald-900/60 dark:bg-emerald-900/20">
              <div className="text-2xs font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-200">Bull</div>
              <div className="mt-1 text-xl font-semibold tabular-nums text-emerald-700 dark:text-emerald-100">
                {formatScore(debate.bull_score)}
              </div>
            </div>
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 dark:border-rose-900/60 dark:bg-rose-900/20">
              <div className="text-2xs font-medium uppercase tracking-wide text-rose-700 dark:text-rose-200">Bear</div>
              <div className="mt-1 text-xl font-semibold tabular-nums text-rose-700 dark:text-rose-100">
                {formatScore(debate.bear_score)}
              </div>
            </div>
          </div>

          {typeof debate.judge_score === 'number' && (
            <div className="flex items-center justify-between rounded-lg border border-fin-border bg-fin-bg px-3 py-2 text-xs">
              <span className="text-fin-muted">Judge score</span>
              <span className="font-semibold tabular-nums text-fin-text">{formatScore(debate.judge_score)}</span>
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2">
              <div className="text-2xs font-semibold uppercase tracking-wide text-fin-muted">Key disagreements</div>
              {disagreements.length > 0 ? (
                <ul className="mt-2 space-y-1.5">
                  {disagreements.slice(0, 5).map((item) => (
                    <li key={item} className="text-xs leading-relaxed text-fin-text">
                      {item}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-2 text-xs text-fin-muted">暂无主要分歧</div>
              )}
            </div>

            <div className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2">
              <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-fin-muted">
                <HelpCircle size={12} />
                Open questions
              </div>
              {openQuestions.length > 0 ? (
                <ul className="mt-2 space-y-1.5">
                  {openQuestions.slice(0, 5).map((item) => (
                    <li key={item} className="text-xs leading-relaxed text-fin-text">
                      {item}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-2 text-xs text-fin-muted">暂无待确认问题</div>
              )}
            </div>
          </div>
        </div>
      )}
    </details>
  );
};
