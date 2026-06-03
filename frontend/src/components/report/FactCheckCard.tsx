import React from 'react';
import { ChevronDown, ShieldAlert, ShieldCheck } from 'lucide-react';

/**
 * P2-1 护城河前置：幻觉洗涤（事实核查）结果可见化。
 *
 * 后端二次 LLM 验证器会逐条核查报告中的「事实性断言」，把缺少证据支撑的
 * 声明替换为「[不可信声明]」占位符。本组件把这一原本黑盒的过程展示给用户，
 * 强化 FinSight「可解释性」护城河——即使零问题也展示「全部通过」状态，
 * 让用户直观感受到系统在认真核查。
 */

export interface FactCheckClaim {
  claim: string;
  reason: string;
}

export interface FactCheck {
  verifier_claims: FactCheckClaim[];
  redaction_count: number;
  verified_at?: string;
  enabled?: boolean;
  checked?: boolean;
}

export interface FactCheckCardProps {
  factCheck?: FactCheck | null;
}

/** 默认展开的 claim 数量，其余收起在「展开全部」里。 */
const DEFAULT_VISIBLE_CLAIMS = 3;

/** 把 ISO 时间戳格式化为简短的本地展示文本，解析失败时原样降级。 */
const formatVerifiedAt = (value?: string): string => {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const FactCheckCard: React.FC<FactCheckCardProps> = ({ factCheck }) => {
  if (!factCheck) return null;

  const claims = Array.isArray(factCheck.verifier_claims) ? factCheck.verifier_claims : [];
  const redactionCount =
    typeof factCheck.redaction_count === 'number' && Number.isFinite(factCheck.redaction_count)
      ? factCheck.redaction_count
      : claims.length;
  const hasRedactions = redactionCount > 0;
  const verifiedAt = formatVerifiedAt(factCheck.verified_at);

  const visibleClaims = claims.slice(0, DEFAULT_VISIBLE_CLAIMS);
  const hiddenClaims = claims.slice(DEFAULT_VISIBLE_CLAIMS);

  return (
    <details className="group rounded-xl border border-fin-border bg-fin-card overflow-hidden" open>
      <summary className="px-4 py-3 cursor-pointer hover:bg-fin-hover transition-colors flex items-center gap-2">
        <ChevronDown size={16} className="text-fin-muted group-open:rotate-180 transition-transform" />
        {hasRedactions ? (
          <ShieldAlert size={15} className="text-amber-500" />
        ) : (
          <ShieldCheck size={15} className="text-emerald-500" />
        )}
        <span className="text-sm font-semibold text-fin-text">事实核查</span>
        <span className="ml-auto text-2xs text-fin-muted">
          {hasRedactions ? `${redactionCount} 条待复核` : '全部通过'}
        </span>
      </summary>

      <div className="px-4 pb-4">
        {!hasRedactions ? (
          // 零问题：绿色信任框，展示「全部通过」以体现核查行为
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs leading-relaxed text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-900/20 dark:text-emerald-200">
            <div className="flex items-start gap-2">
              <ShieldCheck size={15} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-medium">本报告所有关键声明均通过事实核查，未发现不可信内容</div>
                {verifiedAt && (
                  <div className="mt-1 text-2xs text-emerald-600 dark:text-emerald-300/80">
                    核查时间：{verifiedAt}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          // 有过滤：黄色警示框 + claim 列表
          <div className="space-y-3">
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-relaxed text-amber-700 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-200">
              <div className="flex items-start gap-2">
                <ShieldAlert size={15} className="mt-0.5 shrink-0" />
                <div>
                  <div className="font-medium">
                    本报告有 {redactionCount} 条声明未通过验证，已被替换为「[不可信声明]」
                  </div>
                  {verifiedAt && (
                    <div className="mt-1 text-2xs text-amber-600 dark:text-amber-300/80">
                      核查时间：{verifiedAt}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {claims.length > 0 && (
              <div className="space-y-2">
                {visibleClaims.map((item, index) => (
                  <div
                    key={`fact-check-claim-${index}`}
                    className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2"
                  >
                    <div className="text-xs leading-relaxed text-fin-text line-through decoration-amber-400/70">
                      {item.claim}
                    </div>
                    {item.reason && (
                      <div className="mt-1 text-2xs leading-relaxed text-fin-muted">
                        过滤原因：{item.reason}
                      </div>
                    )}
                  </div>
                ))}

                {hiddenClaims.length > 0 && (
                  <details className="group/inner rounded-lg border border-dashed border-fin-border bg-fin-bg-secondary">
                    <summary className="px-3 py-2 cursor-pointer text-2xs text-fin-muted hover:text-fin-text transition-colors flex items-center gap-1.5">
                      <ChevronDown
                        size={13}
                        className="group-open/inner:rotate-180 transition-transform"
                      />
                      展开其余 {hiddenClaims.length} 条
                    </summary>
                    <div className="px-3 pb-3 space-y-2">
                      {hiddenClaims.map((item, index) => (
                        <div
                          key={`fact-check-claim-hidden-${index}`}
                          className="rounded-lg border border-fin-border bg-fin-bg px-3 py-2"
                        >
                          <div className="text-xs leading-relaxed text-fin-text line-through decoration-amber-400/70">
                            {item.claim}
                          </div>
                          {item.reason && (
                            <div className="mt-1 text-2xs leading-relaxed text-fin-muted">
                              过滤原因：{item.reason}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </details>
  );
};
