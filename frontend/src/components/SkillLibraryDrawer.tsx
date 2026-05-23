import React, { useState, useEffect, useRef } from 'react';
import { X, BookOpen, Search } from 'lucide-react';
import type { SkillItem } from '../hooks/useSkillAutocomplete';
import { apiClient } from '../api/client';

interface SkillLibraryDrawerProps {
  open: boolean;
  onClose: () => void;
  onSelectSkill: (insertText: string) => void;
}

interface SkillListResponse {
  success: boolean;
  count: number;
  items: SkillItem[];
}

const RISK_COLORS: Record<string, string> = {
  low: 'bg-green-500/20 text-green-400',
  medium: 'bg-yellow-500/20 text-yellow-400',
  high: 'bg-red-500/20 text-red-400',
};

export function SkillLibraryDrawer({
  open,
  onClose,
  onSelectSkill,
}: SkillLibraryDrawerProps) {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    (apiClient as any).listSkills?.()
      .then((res: SkillListResponse) => {
        if (res?.success && Array.isArray(res.items)) setSkills(res.items);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
    setTimeout(() => searchRef.current?.focus(), 100);
  }, [open]);

  if (!open) return null;

  const q = search.trim().toLowerCase();
  const filtered = q
    ? skills.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q),
      )
    : skills;

  const handleUse = (skill: SkillItem) => {
    onSelectSkill(skill.insert_text);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="flex-1 cursor-default bg-black/40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div
        className="w-full max-w-lg flex flex-col shadow-2xl"
        style={{ backgroundColor: 'var(--fin-card, #1a1a2e)' }}
      >
        {/* Header */}
        <div
          className="sticky top-0 z-10 flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--fin-border, #2a2a4a)' }}
        >
          <div className="flex items-center gap-2">
            <BookOpen size={18} style={{ color: 'var(--fin-primary, #6366f1)' }} />
            <h2 className="text-lg font-semibold" style={{ color: 'var(--fin-text, #e0e0e0)' }}>
              技能库
            </h2>
            <span className="text-xs px-1.5 py-0.5 rounded bg-white/10" style={{ color: 'var(--fin-text-secondary, #888)' }}>
              {skills.length} 个技能
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
          >
            <X size={18} style={{ color: 'var(--fin-text-secondary, #888)' }} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b" style={{ borderColor: 'var(--fin-border, #2a2a4a)' }}>
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--fin-text-secondary, #888)' }}
            />
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索技能..."
              className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border bg-transparent outline-none focus:ring-1"
              style={{
                borderColor: 'var(--fin-border, #2a2a4a)',
                color: 'var(--fin-text, #e0e0e0)',
              }}
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {loading && (
            <p className="text-sm text-center py-8" style={{ color: 'var(--fin-text-secondary, #888)' }}>
              加载中...
            </p>
          )}
          {!loading && filtered.length === 0 && (
            <p className="text-sm text-center py-8" style={{ color: 'var(--fin-text-secondary, #888)' }}>
              {q ? `没有找到匹配 "${q}" 的技能` : '暂无可用技能'}
            </p>
          )}
          {filtered.map((skill) => (
            <div
              key={skill.name}
              className="rounded-lg border p-4 transition-colors hover:bg-white/5"
              style={{ borderColor: 'var(--fin-border, #2a2a4a)' }}
            >
              {/* Title + Risk */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <h3 className="font-medium text-sm" style={{ color: 'var(--fin-text, #e0e0e0)' }}>
                    {skill.name}
                  </h3>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                      RISK_COLORS[skill.risk_level] || RISK_COLORS.low
                    }`}
                  >
                    {skill.risk_level}
                  </span>
                </div>
                <button
                  onClick={() => handleUse(skill)}
                  className="text-xs px-3 py-1 rounded-md font-medium transition-colors"
                  style={{
                    backgroundColor: 'var(--fin-primary, #6366f1)',
                    color: '#fff',
                  }}
                >
                  使用
                </button>
              </div>

              {/* Description */}
              <p className="text-xs mb-3" style={{ color: 'var(--fin-text-secondary, #888)' }}>
                {skill.description}
              </p>

              {/* Tags */}
              <div className="flex flex-wrap gap-1.5">
                {skill.preferred_agents.map((agent) => (
                  <span
                    key={agent}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400"
                  >
                    {agent.replace('_agent', '')}
                  </span>
                ))}
                {skill.preferred_tools.slice(0, 3).map((tool) => (
                  <span
                    key={tool}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-white/5"
                    style={{ color: 'var(--fin-text-secondary, #888)' }}
                  >
                    {tool.replace('get_', '').replace('run_', '')}
                  </span>
                ))}
              </div>

              {/* Facets */}
              {Object.keys(skill.required_facets).length > 0 && (
                <div className="mt-2 text-[10px]" style={{ color: 'var(--fin-text-secondary, #666)' }}>
                  触发条件: {Object.entries(skill.required_facets).map(([k, v]) => `${k}=${String(v)}`).join(', ')}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
