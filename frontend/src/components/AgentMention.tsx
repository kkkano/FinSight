import { useEffect, useRef } from 'react';
import type { AgentItem } from '../hooks/useAgentMention';

interface AgentMentionProps {
  agents: AgentItem[];
  selectedIndex: number;
  onSelect: (agent: AgentItem) => void;
}

/**
 * AgentMention — 对话框 @agent 手动选择下拉（镜像 SkillAutocomplete 样式）。
 * 显示同源 Agent 档案与战绩，选中后由 useAgentMention 就地替换触发片段。
 */
export function AgentMention({
  agents,
  selectedIndex,
  onSelect,
}: AgentMentionProps) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-agent-index="${selectedIndex}"]`,
    );
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  if (agents.length === 0) return null;

  return (
    <div
      ref={listRef}
      id="agent-mention-listbox"
      role="listbox"
      aria-label="Agent 列表"
      className="absolute bottom-full left-0 right-0 mb-1 z-50 rounded-lg shadow-xl border overflow-hidden"
      style={{
        backgroundColor: 'var(--fin-card, #1a1a2e)',
        borderColor: 'var(--fin-border, #2a2a4a)',
      }}
    >
      <div
        className="px-3 py-1.5 text-[10px] uppercase tracking-wide border-b"
        style={{
          color: 'var(--fin-text-secondary, #888)',
          borderColor: 'var(--fin-border, #2a2a4a)',
        }}
      >
        手动指定 Agent（@ 手动 · 不输则自动编排）
      </div>
      {agents.slice(0, 7).map((agent, index) => (
        <div
          key={agent.name}
          data-agent-index={index}
          role="option"
          aria-selected={index === selectedIndex}
          className={`px-3 py-2.5 cursor-pointer transition-colors ${
            index === selectedIndex ? 'bg-blue-500/10' : 'hover:bg-white/5'
          }`}
          onClick={() => onSelect(agent)}
        >
          <div className="flex items-center gap-2">
            <span
              className="inline-flex h-6 min-w-6 items-center justify-center rounded border border-current/30 px-1 font-mono text-2xs"
              style={{ color: `var(--${agent.color_token})` }}
            >
              {agent.glyph}
            </span>
            <span
              className="min-w-0 flex-1 truncate font-medium text-sm"
              style={{ color: 'var(--fin-text, #e0e0e0)' }}
            >
              {agent.display_name}
              <span className="ml-1 font-normal text-fin-muted">— {agent.mandate}</span>
            </span>
            {agent.track_record?.sample_state === 'sufficient'
              && typeof agent.track_record.hit_rate === 'number' && (
                <span className="num ml-auto shrink-0 text-2xs text-t-accent">
                  命中率 {(agent.track_record.hit_rate * 100).toFixed(0)}%
                </span>
              )}
          </div>
        </div>
      ))}
    </div>
  );
}
