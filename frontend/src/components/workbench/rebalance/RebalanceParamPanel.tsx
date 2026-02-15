/**
 * RebalanceParamPanel — Parameter configuration panel for generating
 * rebalance suggestions.
 *
 * Includes risk tier radio, AI enhancement toggle, collapsible advanced
 * constraints, and a generate button with loading state.
 */
import { useState, useCallback } from 'react';
import { ChevronDown, ChevronRight, Loader2, Sparkles, Settings2 } from 'lucide-react';

import { Button } from '../../ui/Button.tsx';
import { Card } from '../../ui/Card.tsx';
import type { RiskTier, RebalanceConstraints, GenerateRebalanceParams } from '../../../types/dashboard.ts';

interface RebalanceParamPanelProps {
  loading: boolean;
  onGenerate: (params: GenerateRebalanceParams) => void;
  sessionId: string;
  portfolio: { ticker: string; shares: number; avgCost?: number }[];
}

const RISK_TIERS: { value: RiskTier; label: string; desc: string }[] = [
  { value: 'conservative', label: '保守型', desc: '低波动，注重资本保全' },
  { value: 'moderate', label: '稳健型', desc: '均衡收益与风险' },
  { value: 'aggressive', label: '进取型', desc: '追求高回报，容忍高波动' },
];

const DEFAULT_CONSTRAINTS: RebalanceConstraints = {
  max_single_position_pct: 25,
  max_turnover_pct: 30,
  sector_concentration_limit: 40,
  min_action_delta_pct: 2,
};

export function RebalanceParamPanel({ loading, onGenerate, sessionId, portfolio }: RebalanceParamPanelProps) {
  const [riskTier, setRiskTier] = useState<RiskTier>('moderate');
  const [useLLM, setUseLLM] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [constraints, setConstraints] = useState<RebalanceConstraints>(DEFAULT_CONSTRAINTS);

  const updateConstraint = useCallback(
    <K extends keyof RebalanceConstraints>(key: K, value: number) => {
      setConstraints((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleGenerate = useCallback(() => {
    const params: GenerateRebalanceParams = {
      session_id: sessionId,
      portfolio,
      risk_tier: riskTier,
      constraints,
      use_llm_enhancement: useLLM,
    };
    onGenerate(params);
  }, [sessionId, portfolio, riskTier, constraints, useLLM, onGenerate]);

  const isDisabled = loading || portfolio.length === 0;

  return (
    <Card id="rebalance-param-panel" className="p-4 space-y-4">
      <div className="flex items-center gap-2 text-fin-text font-semibold text-sm">
        <Settings2 size={16} className="text-fin-primary" />
        调仓参数配置
      </div>

      {/* Risk tier radio group */}
      <div className="space-y-2">
        <span className="text-xs text-fin-muted font-medium">风险偏好</span>
        <div className="grid grid-cols-3 gap-2">
          {RISK_TIERS.map((tier) => (
            <button
              key={tier.value}
              type="button"
              onClick={() => setRiskTier(tier.value)}
              className={`
                text-left px-3 py-2 rounded-lg border text-xs transition-colors
                ${riskTier === tier.value
                  ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
                  : 'border-fin-border bg-fin-card text-fin-text-secondary hover:bg-fin-hover'}
              `.trim()}
            >
              <div className="font-medium">{tier.label}</div>
              <div className="text-2xs text-fin-muted mt-0.5">{tier.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* AI enhancement toggle */}
      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={useLLM}
          onChange={(e) => setUseLLM(e.target.checked)}
          className="accent-fin-primary w-3.5 h-3.5"
        />
        <Sparkles size={14} className="text-fin-primary" />
        <span className="text-xs text-fin-text">AI 增强分析</span>
        <span className="text-2xs text-fin-muted">(使用 LLM 优化建议)</span>
      </label>

      {/* Advanced constraints — collapsible */}
      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced((prev) => !prev)}
          className="flex items-center gap-1.5 text-xs text-fin-text-secondary hover:text-fin-text transition-colors"
        >
          {showAdvanced ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          高级约束
        </button>

        {showAdvanced && (
          <div className="mt-2 space-y-2 pl-5">
            <ConstraintInput
              label="单一持仓上限 (%)"
              value={constraints.max_single_position_pct}
              onChange={(v) => updateConstraint('max_single_position_pct', v)}
            />
            <ConstraintInput
              label="最大换手率 (%)"
              value={constraints.max_turnover_pct}
              onChange={(v) => updateConstraint('max_turnover_pct', v)}
            />
            <ConstraintInput
              label="行业集中度上限 (%)"
              value={constraints.sector_concentration_limit}
              onChange={(v) => updateConstraint('sector_concentration_limit', v)}
            />
            <ConstraintInput
              label="最小操作幅度 (%)"
              value={constraints.min_action_delta_pct}
              onChange={(v) => updateConstraint('min_action_delta_pct', v)}
            />
          </div>
        )}
      </div>

      {/* Generate button */}
      <Button
        variant="primary"
        size="md"
        onClick={handleGenerate}
        disabled={isDisabled}
        className="w-full"
      >
        {loading ? (
          <>
            <Loader2 size={14} className="animate-spin" />
            生成中...
          </>
        ) : (
          '生成调仓建议'
        )}
      </Button>

      {portfolio.length === 0 && (
        <p className="text-2xs text-fin-warning text-center">
          请先添加持仓后再生成建议
        </p>
      )}
    </Card>
  );
}

/* ---- Constraint input field ---- */

interface ConstraintInputProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
}

function ConstraintInput({ label, value, onChange }: ConstraintInputProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-2xs text-fin-muted whitespace-nowrap">{label}</span>
      <input
        type="number"
        min={0}
        max={100}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-16 px-2 py-1 text-xs text-fin-text bg-fin-bg-secondary border border-fin-border rounded-md text-right focus:outline-none focus:ring-1 focus:ring-fin-primary"
      />
    </div>
  );
}
