import { useEffect, useRef } from 'react';
import type { AgentItem } from '../hooks/useAgentMention';

interface AgentMentionProps {
  agents: AgentItem[];
  selectedIndex: number;
  onSelect: (agent: AgentItem) => void;
}

/**
 * AgentMention — 对话框 @agent 手动选择下拉（镜像 SkillAutocomplete 样式）。
 * 显示 agent 中文名 + 描述，选中后由 useAgentMention 就地替换触发片段。
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
          <div className="flex items-center gap-2 mb-0.5">
            <span
              className="font-medium text-sm"
              style={{ color: 'var(--fin-text, #e0e0e0)' }}
            >
              {agent.display_name}
            </span>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 font-mono"
              style={{ color: 'var(--fin-text-secondary, #888)' }}
            >
              @{agent.name.replace('_agent', '')}
            </span>
          </div>
          <p
            className="text-xs truncate"
            style={{ color: 'var(--fin-text-secondary, #888)' }}
          >
            {agent.description}
          </p>
        </div>
      ))}
    </div>
  );
}
