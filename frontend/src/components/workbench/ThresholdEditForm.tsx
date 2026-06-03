/**
 * ThresholdEditForm.tsx —— 监控阈值内联编辑表单
 *
 * 在监控目标行下方展开（非弹窗，保持轻量）。
 * 按 target 类型渲染对应字段组，数字输入 + 前端范围校验，
 * 保存调 PATCH（由父组件注入），成功后由父组件收起。
 */
import { useState } from 'react';

import type { MonitorTarget } from '../../types/monitor';
import {
  resolveThresholdFields,
  validateThresholdConfig,
} from './monitorThresholds';

interface ThresholdEditFormProps {
  target: MonitorTarget;
  saving: boolean;
  /** 保存：传出校验通过的 config（仅含本表单字段） */
  onSave: (config: Record<string, number>) => void;
  onCancel: () => void;
}

const inputClass =
  'w-20 px-2 py-1 text-xs text-right tabular-nums rounded-lg border border-fin-border bg-fin-bg text-fin-text placeholder:text-fin-muted focus:outline-none focus:border-fin-primary focus:ring-1 focus:ring-fin-primary/30';

export function ThresholdEditForm({ target, saving, onSave, onCancel }: ThresholdEditFormProps) {
  const fields = resolveThresholdFields(target);

  // 初始值：取 target.config 现有值，缺失则空字符串
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of fields) {
      const cur = target.config[f.key];
      init[f.key] = cur != null ? String(cur) : '';
    }
    return init;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleSubmit = () => {
    // 只收集填了值的字段（空字段视为不修改）
    const config: Record<string, number> = {};
    for (const f of fields) {
      const raw = values[f.key]?.trim();
      if (raw === undefined || raw === '') continue;
      const num = Number(raw);
      config[f.key] = num;
    }
    const result = validateThresholdConfig(config);
    if (!result.valid) {
      setErrors(result.errors);
      return;
    }
    setErrors({});
    onSave(config);
  };

  return (
    <div
      className="px-3 py-2.5 bg-fin-bg/40 space-y-2"
      data-testid={`threshold-edit-${target.id}`}
    >
      {fields.map((f) => (
        <div key={f.key} className="flex items-center justify-between gap-2">
          <span className="text-2xs text-fin-muted whitespace-nowrap">{f.label}</span>
          <div className="flex items-center gap-1">
            <input
              type="number"
              inputMode="decimal"
              min={f.min}
              max={f.max}
              step={f.step}
              value={values[f.key] ?? ''}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [f.key]: e.target.value }))
              }
              aria-label={f.label}
              className={inputClass}
            />
            {f.suffix && <span className="text-2xs text-fin-muted w-3">{f.suffix}</span>}
          </div>
        </div>
      ))}

      {Object.keys(errors).length > 0 && (
        <div className="text-2xs text-fin-danger space-y-0.5" data-testid={`threshold-errors-${target.id}`}>
          {Object.values(errors).map((msg, idx) => (
            <div key={idx}>{msg}</div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-0.5">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={saving}
          className="px-2.5 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-50 transition-colors"
        >
          保存
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-2.5 py-1 text-xs font-medium rounded-lg text-fin-muted hover:text-fin-text transition-colors"
        >
          取消
        </button>
      </div>
    </div>
  );
}

export default ThresholdEditForm;
