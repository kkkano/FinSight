import { useEffect, useState } from 'react';
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
