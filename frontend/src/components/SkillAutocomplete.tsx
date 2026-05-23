import React, { useEffect, useRef } from 'react';
import type { SkillItem } from '../hooks/useSkillAutocomplete';

interface SkillAutocompleteProps {
  skills: SkillItem[];
  selectedIndex: number;
  onSelect: (skill: SkillItem) => void;
  onOpenLibrary: () => void;
}

const RISK_COLORS: Record<string, string> = {
  low: 'bg-green-500/20 text-green-400',
  medium: 'bg-yellow-500/20 text-yellow-400',
  high: 'bg-red-500/20 text-red-400',
};

export function SkillAutocomplete({
  skills,
  selectedIndex,
  onSelect,
  onOpenLibrary,
}: SkillAutocompleteProps) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-skill-index="${selectedIndex}"]`,
    );
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  if (skills.length === 0) return null;

  return (
    <div
      ref={listRef}
      id="skill-autocomplete-listbox"
      role="listbox"
      aria-label="技能列表"
      className="absolute bottom-full left-0 right-0 mb-1 z-50 rounded-lg shadow-xl border overflow-hidden"
      style={{
        backgroundColor: 'var(--fin-card, #1a1a2e)',
        borderColor: 'var(--fin-border, #2a2a4a)',
      }}
    >
      {skills.slice(0, 5).map((skill, index) => (
        <div
          key={skill.name}
          data-skill-index={index}
          role="option"
          aria-selected={index === selectedIndex}
          className={`px-3 py-2.5 cursor-pointer transition-colors ${
            index === selectedIndex
              ? 'bg-blue-500/10'
              : 'hover:bg-white/5'
          }`}
          onClick={() => onSelect(skill)}
          onMouseEnter={() => {}}
        >
          <div className="flex items-center gap-2 mb-0.5">
            <span className="font-medium text-sm" style={{ color: 'var(--fin-text, #e0e0e0)' }}>
              {skill.name}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                RISK_COLORS[skill.risk_level] || RISK_COLORS.low
              }`}
            >
              {skill.risk_level}
            </span>
          </div>
          <p
            className="text-xs truncate"
            style={{ color: 'var(--fin-text-secondary, #888)' }}
          >
            {skill.description}
          </p>
          {skill.preferred_agents.length > 0 && (
            <div className="flex gap-1 mt-1 flex-wrap">
              {skill.preferred_agents.slice(0, 3).map((agent) => (
                <span
                  key={agent}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-white/5"
                  style={{ color: 'var(--fin-text-secondary, #888)' }}
                >
                  {agent.replace('_agent', '')}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
      <div
        className="px-3 py-2 text-xs cursor-pointer border-t transition-colors hover:bg-white/5"
        style={{
          color: 'var(--fin-primary, #6366f1)',
          borderColor: 'var(--fin-border, #2a2a4a)',
        }}
        onClick={onOpenLibrary}
      >
        查看全部技能 →
      </div>
    </div>
  );
}
