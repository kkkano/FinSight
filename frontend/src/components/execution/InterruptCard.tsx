/**
 * InterruptCard - UI for human-in-the-loop graph interrupts.
 *
 * 目标：
 * 1) 解释为什么需要用户选择
 * 2) 明确每个选项会产生什么效果
 * 3) 为“调整参数”提供一键模板，降低使用门槛
 */
import { useMemo, useState } from 'react';
import { CheckCircle, Info, Settings, XCircle } from 'lucide-react';

interface InterruptData {
  thread_id: string;
  prompt?: string;
  options?: string[];
  plan_summary?: string;
  required_agents?: string[];
  gate_reason_code?: string;
  gate_reason?: string;
  option_effects?: Record<string, string>;
  option_intents?: Record<string, string>;
  output_mode?: string;
  confirmation_mode?: string;
}

interface InterruptCardProps {
  data: InterruptData;
  onResume: (threadId: string, resumeValue: string) => void;
  onCancel: () => void;
}

interface AdjustmentTemplate {
  id: string;
  title: string;
  description: string;
  instruction: string;
}

const FALLBACK_OPTION_EFFECTS: Record<string, string> = {
  confirm_execute: '按当前计划继续执行，并开始生成结果。',
  adjust_parameters: '先补充你的修改要求，再继续执行（例如范围、数据源、输出重点）。',
  cancel_execution: '终止本次任务，不再继续执行。',
  custom: '按该选项继续流程。',
};

const ADJUSTMENT_TEMPLATES: AdjustmentTemplate[] = [
  {
    id: 'focus_fundamental',
    title: '聚焦基本面',
    description: '去掉技术面，重点看财报、估值与经营质量',
    instruction: '只保留基本面分析，去掉技术面；重点解释财报、估值、现金流和盈利质量。',
  },
  {
    id: 'last_two_quarters',
    title: '缩小时间范围',
    description: '只看最近两个季度，减少历史噪声',
    instruction: '把时间范围限制在最近两个季度，优先最新财报和业绩会信息。',
  },
  {
    id: 'conclusion_first',
    title: '先结论后证据',
    description: '先给结论，再列证据链与反证',
    instruction: '输出结构改为先给投资结论，再列关键证据、反证和不确定性。',
  },
  {
    id: 'risk_conservative',
    title: '风险优先',
    description: '用保守口径，突出风险与回撤场景',
    instruction: '采用保守分析口径，优先展开风险项、回撤场景和触发条件。',
  },
  {
    id: 'peer_valuation',
    title: '加强同业对比',
    description: '增加可比公司与估值区间对照',
    instruction: '增加同业可比分析，给出估值区间、相对高低位和关键差异原因。',
  },
  {
    id: 'short_output',
    title: '压缩输出',
    description: '控制篇幅，给可执行短结论',
    instruction: '压缩为短报告：3条结论、3条证据、3条风险，语言简洁直接。',
  },
];

function normalizeIntentFromText(option: string): 'confirm_execute' | 'adjust_parameters' | 'cancel_execution' | 'custom' {
  const raw = option.trim().toLowerCase();
  if (!raw) return 'custom';
  if (raw.includes('cancel') || raw.includes('abort') || raw.includes('取消') || raw.includes('终止')) {
    return 'cancel_execution';
  }
  if (raw.includes('adjust') || raw.includes('param') || raw.includes('调整') || raw.includes('参数')) {
    return 'adjust_parameters';
  }
  if (raw.includes('confirm') || raw.includes('continue') || raw.includes('确认') || raw.includes('继续')) {
    return 'confirm_execute';
  }
  return 'custom';
}

export function InterruptCard({ data, onResume, onCancel }: InterruptCardProps) {
  const [customInput, setCustomInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [showAdjustTemplates, setShowAdjustTemplates] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

  const options = useMemo(
    () => data.options ?? ['确认执行', '调整参数', '取消'],
    [data.options],
  );
  const reasonText = data.gate_reason || '当前任务触发执行前确认，这不是报错。';

  const optionRows = useMemo(() => {
    return options.map((option, index) => {
      const explicitIntent = data.option_intents?.[option];
      const positionalIntent = index === 0
        ? 'confirm_execute'
        : index === 1
          ? 'adjust_parameters'
          : index === 2
            ? 'cancel_execution'
            : 'custom';

      const inferredIntent = normalizeIntentFromText(option);
      const intent = (
        explicitIntent === 'confirm_execute'
        || explicitIntent === 'adjust_parameters'
        || explicitIntent === 'cancel_execution'
        || explicitIntent === 'custom'
      )
        ? explicitIntent
        : inferredIntent !== 'custom'
          ? inferredIntent
          : positionalIntent;

      const effect = data.option_effects?.[option] || FALLBACK_OPTION_EFFECTS[intent] || FALLBACK_OPTION_EFFECTS.custom;
      return { option, intent, effect };
    });
  }, [data.option_effects, data.option_intents, options]);

  const handleOptionClick = (option: string, intent: string) => {
    if (intent === 'cancel_execution') {
      onCancel();
      return;
    }
    if (intent === 'adjust_parameters') {
      setShowAdjustTemplates((prev) => !prev);
      return;
    }
    setSubmitting(true);
    onResume(data.thread_id, option);
  };

  const handleApplyTemplate = (template: AdjustmentTemplate) => {
    if (submitting) return;
    setSubmitting(true);
    setSelectedTemplateId(template.id);
    onResume(data.thread_id, `调整参数：${template.instruction}`);
  };

  const handleCustomSubmit = () => {
    if (!customInput.trim()) return;
    setSubmitting(true);
    onResume(data.thread_id, customInput.trim());
  };

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
          <Settings size={16} className="text-amber-500" />
        </div>
        <h3 className="text-sm font-semibold text-fin-text">
          {data.prompt ?? '执行计划确认'}
        </h3>
      </div>

      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        <div className="flex items-center gap-1.5 font-medium">
          <Info size={12} />
          为什么现在需要你选择
        </div>
        <div className="mt-1 leading-relaxed">{reasonText}</div>
        {(data.output_mode || data.confirmation_mode) && (
          <div className="mt-1 text-2xs text-amber-100/80">
            mode: {data.output_mode || '--'} | confirmation: {data.confirmation_mode || '--'}
          </div>
        )}
      </div>

      {data.plan_summary && (
        <div className="text-xs text-fin-text-secondary bg-fin-bg rounded-lg p-3">
          <p className="font-medium text-fin-text mb-1">执行计划</p>
          <p>{data.plan_summary}</p>
        </div>
      )}

      {data.required_agents && data.required_agents.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.required_agents.map((agent) => (
            <span
              key={agent}
              className="px-2 py-0.5 text-xs rounded-full bg-fin-bg border border-fin-border text-fin-text-secondary"
            >
              {agent}
            </span>
          ))}
        </div>
      )}

      <div className="space-y-2">
        {optionRows.map(({ option, intent, effect }) => {
          const isCancel = intent === 'cancel_execution';
          const isConfirm = intent === 'confirm_execute';
          const isAdjust = intent === 'adjust_parameters';

          return (
            <div key={option} className="space-y-1">
              <button
                type="button"
                disabled={submitting}
                onClick={() => handleOptionClick(option, intent)}
                className={`w-full text-left px-4 py-2 text-xs font-medium rounded-lg border transition-colors disabled:opacity-50 ${
                  isConfirm
                    ? 'bg-green-600/20 border-green-600/40 text-green-400 hover:bg-green-600/30'
                    : isCancel
                      ? 'bg-red-600/20 border-red-600/40 text-red-400 hover:bg-red-600/30'
                      : 'bg-fin-bg border-fin-border text-fin-text hover:bg-fin-hover'
                }`}
              >
                {isConfirm && <CheckCircle size={12} className="inline mr-1" />}
                {isCancel && <XCircle size={12} className="inline mr-1" />}
                {option}
                {isAdjust && (
                  <span className="ml-2 text-2xs text-fin-muted">
                    {showAdjustTemplates ? '（已展开模板）' : '（点此展开模板）'}
                  </span>
                )}
              </button>
              <div className="px-1 text-2xs text-fin-muted">{effect}</div>
            </div>
          );
        })}
      </div>

      {showAdjustTemplates && (
        <div className="rounded-lg border border-fin-border bg-fin-bg/40 p-3 space-y-2">
          <div className="text-xs font-medium text-fin-text">
            快速模板（点一下就继续执行）
          </div>
          <div className="text-2xs text-fin-muted">
            如果你不确定怎么改，直接选一个最接近目标的模板。
          </div>
          <div className="grid grid-cols-1 gap-2">
            {ADJUSTMENT_TEMPLATES.map((template) => (
              <button
                key={template.id}
                type="button"
                disabled={submitting}
                onClick={() => handleApplyTemplate(template)}
                className={`w-full text-left rounded-lg border px-3 py-2 transition-colors disabled:opacity-50 ${
                  selectedTemplateId === template.id
                    ? 'border-fin-primary/60 bg-fin-primary/10'
                    : 'border-fin-border bg-fin-card hover:bg-fin-hover'
                }`}
              >
                <div className="text-xs font-medium text-fin-text">{template.title}</div>
                <div className="mt-0.5 text-2xs text-fin-muted">{template.description}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCustomSubmit()}
          placeholder="或输入自定义指令，例如：只保留财报与估值，不要技术面"
          disabled={submitting}
          className="flex-1 px-3 py-1.5 text-xs bg-fin-bg border border-fin-border rounded-lg text-fin-text placeholder:text-fin-muted focus:outline-none focus:border-fin-primary disabled:opacity-50"
        />
        <button
          type="button"
          onClick={handleCustomSubmit}
          disabled={submitting || !customInput.trim()}
          className="px-3 py-1.5 text-xs font-medium rounded-lg bg-fin-bg border border-fin-border text-fin-text hover:bg-fin-hover disabled:opacity-50"
        >
          发送
        </button>
      </div>
    </div>
  );
}
