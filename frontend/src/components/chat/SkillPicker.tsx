import { Check, Loader2, X } from 'lucide-react';
import type { ResearchSkill } from '../../types/runtime';
import { MAX_SELECTED_SKILLS } from '../../utils/skillCommands';

export function SelectedSkills({ skills, onRemove }: { skills: ResearchSkill[]; onRemove: (id: string) => void }) {
  if (!skills.length) return null;
  return <div className="mx-auto mb-2 flex max-w-[760px] flex-wrap gap-2" aria-label="已选技能">
    {skills.map((skill) => <span key={skill.id} className="inline-flex items-center gap-1.5 rounded-full border border-t-accent/30 bg-t-accent/5 px-3 py-1 text-xs text-t-accent">
      {skill.name}<button type="button" aria-label={`移除技能 ${skill.name}`} onClick={() => onRemove(skill.id)} className="rounded p-1 hover:bg-t-hover"><X size={12} /></button>
    </span>)}
  </div>;
}

interface SkillPickerProps {
  rows: ResearchSkill[];
  selected: ResearchSkill[];
  activeIndex: number;
  loading: boolean;
  error: string;
  onSelect: (skill: ResearchSkill) => void;
  onRemove: (id: string) => void;
  onClose: () => void;
  onRetry: () => void;
}

export function SkillPicker({ rows, selected, activeIndex, loading, error, onSelect, onRemove, onClose, onRetry }: SkillPickerProps) {
  return <div className="absolute bottom-full left-0 right-0 z-30 mb-2 rounded-xl border border-t-border bg-t-surface p-2 shadow-xl" data-testid="skill-picker">
    <div className="mb-1 flex items-center justify-between px-2 py-1 text-xs text-t-text3">
      <span>选择技能 · 最多 {MAX_SELECTED_SKILLS} 个</span>
      <button type="button" onClick={onClose} aria-label="关闭技能菜单" className="p-1"><X size={14} /></button>
    </div>
    <SelectedSkills skills={selected} onRemove={onRemove} />
    {loading ? <p role="status" className="flex items-center gap-2 px-2 py-4 text-sm text-t-text2"><Loader2 size={14} className="animate-spin" />正在加载技能…</p>
      : error ? <div className="px-2 py-3"><p role="alert" className="text-sm text-fin-danger">{error}</p><button type="button" className="mt-2 text-sm text-t-accent" onClick={onRetry}>重新加载</button></div>
        : <div id="chat-skill-listbox" role="listbox" aria-label="研究技能" className="max-h-64 overflow-y-auto">
          {rows.map((skill, index) => {
            const chosen = selected.some((item) => item.id === skill.id);
            const unavailable = chosen || selected.length >= MAX_SELECTED_SKILLS;
            return <button id={`chat-skill-option-${index}`} key={skill.id} type="button" role="option" aria-selected={index === activeIndex}
              aria-disabled={unavailable} onMouseDown={(event) => event.preventDefault()}
              onClick={() => { if (!unavailable) onSelect(skill); }}
              className={`flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left ${index === activeIndex ? 'bg-t-hover' : 'hover:bg-t-hover'} ${unavailable ? 'opacity-50' : ''}`}>
              <span className="min-w-0 flex-1"><span className="text-sm font-medium text-t-text">{skill.name}</span>
                <span className="ml-2 text-xs text-t-text3">/{skill.id}</span>
                <span className="mt-1 block break-words text-xs leading-5 text-t-text3">{skill.description}</span></span>
              {chosen && <Check size={15} className="mt-1 shrink-0 text-t-accent" />}
            </button>;
          })}
          {!rows.length && <p className="px-3 py-4 text-sm text-t-text3">没有匹配的研究技能。</p>}
        </div>}
    <p className="mt-1 border-t border-t-border px-2 pt-2 text-[11px] text-t-text3">↑ ↓ 选择 · Enter 添加 · Esc 关闭；选好后输入研究问题。</p>
  </div>;
}
