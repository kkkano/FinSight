/**
 * InterruptCard — UI for human-in-the-loop graph interrupts.
 *
 * When the LangGraph pipeline is interrupted (e.g. confirmation_gate),
 * this card displays the interrupt prompt and options, then sends the
 * user's response via the resume API.
 */
import { useState } from 'react';
import { CheckCircle, XCircle, Settings } from 'lucide-react';

interface InterruptData {
  thread_id: string;
  prompt?: string;
  options?: string[];
  plan_summary?: string;
  required_agents?: string[];
}

interface InterruptCardProps {
  data: InterruptData;
  onResume: (threadId: string, resumeValue: string) => void;
  onCancel: () => void;
}

export function InterruptCard({ data, onResume, onCancel }: InterruptCardProps) {
  const [customInput, setCustomInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const options = data.options ?? ['确认执行', '调整参数', '取消'];

  const handleOptionClick = async (option: string) => {
    if (option === '取消') {
      onCancel();
      return;
    }
    setSubmitting(true);
    onResume(data.thread_id, option);
  };

  const handleCustomSubmit = () => {
    if (!customInput.trim()) return;
    setSubmitting(true);
    onResume(data.thread_id, customInput.trim());
  };

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
          <Settings size={16} className="text-amber-500" />
        </div>
        <h3 className="text-sm font-semibold text-fin-text">
          {data.prompt ?? '执行确认'}
        </h3>
      </div>

      {/* Plan summary */}
      {data.plan_summary && (
        <div className="text-xs text-fin-text-secondary bg-fin-bg rounded-lg p-3">
          <p className="font-medium text-fin-text mb-1">执行计划</p>
          <p>{data.plan_summary}</p>
        </div>
      )}

      {/* Required agents */}
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

      {/* Option buttons */}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const isCancel = option === '取消';
          const isConfirm = option === '确认执行';
          return (
            <button
              key={option}
              type="button"
              disabled={submitting}
              onClick={() => handleOptionClick(option)}
              className={`px-4 py-2 text-xs font-medium rounded-lg border transition-colors disabled:opacity-50 ${
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
            </button>
          );
        })}
      </div>

      {/* Custom input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCustomSubmit()}
          placeholder="或输入自定义指令..."
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
