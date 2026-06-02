import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { apiClient } from '../api/client';

export interface SkillItem {
  name: string;
  description: string;
  risk_level: string;
  required_facets: Record<string, unknown>;
  preferred_tools: string[];
  preferred_agents: string[];
  optional_python_operations: string[];
  budget: Record<string, unknown>;
  insert_text: string;
}

// 输入一个 "/" 即触发技能提示；兼容旧的 "/skill"（可选前缀），"/chan" 等直接过滤
const SKILL_TRIGGER_RE = /(^|\s)\/(?:skill\s*)?(\S*)$/;

export function useSkillAutocomplete(
  inputText: string,
  onInsert: (text: string) => void,
) {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const fetchedRef = useRef(false);
  const prevInputRef = useRef(inputText);
  const insertingRef = useRef(false);

  const match = SKILL_TRIGGER_RE.exec(inputText);
  const isOpen = match !== null && !dismissed;
  const query = match?.[2]?.toLowerCase() ?? '';

  useEffect(() => {
    if (prevInputRef.current !== inputText) {
      prevInputRef.current = inputText;
      if (insertingRef.current) {
        insertingRef.current = false;
      } else {
        setDismissed(false);
      }
    }
  }, [inputText]);

  useEffect(() => {
    if (isOpen && !fetchedRef.current) {
      fetchedRef.current = true;
      apiClient.listSkills()
        .then((res) => {
          if (res?.success && Array.isArray(res.items)) {
            setSkills(res.items as unknown as SkillItem[]);
          }
        })
        .catch(() => {
          fetchedRef.current = false;
        });
    }
  }, [isOpen]);

  const filteredSkills = useMemo(
    () =>
      query
        ? skills.filter(
            (s) =>
              s.name.toLowerCase().includes(query) ||
              s.description.toLowerCase().includes(query),
          )
        : skills,
    [skills, query],
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const selectSkill = useCallback(
    (skill: SkillItem) => {
      insertingRef.current = true;
      onInsert(skill.insert_text);
      setDismissed(true);
    },
    [onInsert],
  );

  const close = useCallback(() => {
    setDismissed(true);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!isOpen || filteredSkills.length === 0) return false;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % filteredSkills.length);
        return true;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(
          (i) => (i - 1 + filteredSkills.length) % filteredSkills.length,
        );
        return true;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        const selected = filteredSkills[selectedIndex];
        if (selected) selectSkill(selected);
        return true;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
        return true;
      }
      return false;
    },
    [isOpen, filteredSkills, selectedIndex, selectSkill, close],
  );

  return {
    isOpen,
    query,
    filteredSkills,
    selectedIndex,
    handleKeyDown,
    selectSkill,
    close,
  };
}
