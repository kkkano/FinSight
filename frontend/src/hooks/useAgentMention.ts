import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { apiClient } from '../api/client';

export interface AgentItem {
  name: string;
  display_name: string;
  description: string;
  insert_text: string;
}

// 输入 "@" 触发 agent 选择（前面须是行首或空白，避免 email 等误触发）
const AGENT_TRIGGER_RE = /(^|\s)@(\S*)$/;

/**
 * useAgentMention — 对话「手动选 Agent」双模式的输入补全。
 *
 * 镜像 useSkillAutocomplete：输入 `@` 弹出 agent 清单，选中后把触发的
 * `@query` 片段就地替换为 `@{name} `（保留前文），发送时由 ChatInput 解析
 * 为 options.agents 传后端覆盖自动编排。不输 `@` 即自动模式。
 */
export function useAgentMention(
  inputText: string,
  onReplace: (newText: string) => void,
) {
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const fetchedRef = useRef(false);
  const prevInputRef = useRef(inputText);
  const insertingRef = useRef(false);

  const match = AGENT_TRIGGER_RE.exec(inputText);
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
      apiClient.listAgents()
        .then((res) => {
          if (res?.success && Array.isArray(res.items)) {
            setAgents(res.items as unknown as AgentItem[]);
          }
        })
        .catch(() => {
          fetchedRef.current = false;
        });
    }
  }, [isOpen]);

  const filteredAgents = useMemo(
    () =>
      query
        ? agents.filter(
            (a) =>
              a.name.toLowerCase().includes(query) ||
              a.display_name.toLowerCase().includes(query) ||
              a.description.toLowerCase().includes(query),
          )
        : agents,
    [agents, query],
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const selectAgent = useCallback(
    (agent: AgentItem) => {
      insertingRef.current = true;
      // 仅替换触发的 "@query" 片段，保留前面已输入的内容
      const newText = inputText.replace(
        AGENT_TRIGGER_RE,
        (_full, prefix: string) => `${prefix}${agent.insert_text}`,
      );
      onReplace(newText);
      setDismissed(true);
    },
    [inputText, onReplace],
  );

  const close = useCallback(() => {
    setDismissed(true);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!isOpen || filteredAgents.length === 0) return false;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % filteredAgents.length);
        return true;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(
          (i) => (i - 1 + filteredAgents.length) % filteredAgents.length,
        );
        return true;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        const selected = filteredAgents[selectedIndex];
        if (selected) selectAgent(selected);
        return true;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
        return true;
      }
      return false;
    },
    [isOpen, filteredAgents, selectedIndex, selectAgent, close],
  );

  return {
    isOpen,
    query,
    filteredAgents,
    selectedIndex,
    handleKeyDown,
    selectAgent,
    close,
  };
}

/**
 * 从输入文本解析所有 @agent 提及，返回去重后的 agent name 列表。
 * 宽松提取（@ 后接字母/下划线），合法性由后端 policy_gate 按
 * REPORT_AGENT_CANDIDATES 二次校验，非法名自动忽略。发送时调用。
 */
export function parseAgentMentions(inputText: string): string[] {
  const found: string[] = [];
  const seen = new Set<string>();
  for (const m of inputText.matchAll(/(?:^|\s)@([A-Za-z_]+)/g)) {
    const name = m[1];
    if (!seen.has(name)) {
      seen.add(name);
      found.push(name);
    }
  }
  return found;
}
