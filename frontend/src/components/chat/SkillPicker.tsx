import { useEffect, useState } from 'react';
import { Check, Loader2, X } from 'lucide-react';
import { apiClient } from '../../api/client';
import type { ResearchSkill } from '../../types/runtime';
import { filterResearchSkills, MAX_SELECTED_SKILLS, skillCommandAt } from '../../utils/skillCommands';
import type { SkillCommand } from '../../utils/skillCommands';

export function useSkillPicker(sessionId: string, ownerId?: string, disabled = false) {
  const [catalogue, setCatalogue] = useState<ResearchSkill[] | null>(null);
  const [selected, setSelected] = useState<ResearchSkill[]>([]);
  const [command, setCommand] = useState<SkillCommand | null>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const rows = filterResearchSkills(catalogue || [], command?.query || '');

  useEffect(() => {
    setSelected([]);
    setOpen(false);
    setCommand(null);
    setCatalogue(null);
    setError('');
  }, [sessionId, ownerId]);

  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  useEffect(() => {
    if (!open || catalogue !== null || disabled) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    void apiClient.getResearchSkills(controller.signal).then((skills) => {
      if (controller.signal.aborted) return;
      setCatalogue(skills);
      setLoading(false);
    }).catch(() => {
      if (controller.signal.aborted) return;
      setError('技能列表暂时无法加载，请重试。');
      setLoading(false);
    });
    return () => controller.abort();
  }, [open, catalogue, retry, sessionId, ownerId, disabled]);

  const updateCommand = (value: string, caret = value.length) => {
    const next = disabled ? null : skillCommandAt(value, caret);
    setCommand(next);
    setOpen(Boolean(next));
    setActiveIndex(0);
  };
  const select = (skill: ResearchSkill): boolean => {
    if (selected.some((item) => item.id === skill.id) || selected.length >= MAX_SELECTED_SKILLS) return false;
    setSelected((previous) => [...previous, skill]);
    setOpen(false);
    setCommand(null);
    return true;
  };
  return { selected, rows, command, open, activeIndex, loading, error,
    updateCommand, select, close: () => setOpen(false), retry: () => setRetry((value) => value + 1),
    remove: (id: string) => setSelected((previous) => previous.filter((skill) => skill.id !== id)),
    clear: () => { setSelected([]); setOpen(false); setCommand(null); },
    move: (direction: number) => setActiveIndex((index) => rows.length ? (index + direction + rows.length) % rows.length : 0),
  };
}

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
