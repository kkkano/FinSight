import { describe, expect, it, vi } from 'vitest';

import type { AgentProfileView } from '../types/agents';
import { buildExpertCommandDescriptors, runExpertCommand } from './commandPaletteExperts';

const profiles: AgentProfileView[] = [
  ['price_agent', '行情分析师', '行情', 'P'],
  ['news_agent', '新闻分析师', '新闻', 'N'],
  ['fundamental_agent', '基本面分析师', '基本面', 'F'],
  ['technical_agent', '技术面分析师', '技术面', 'T'],
  ['macro_agent', '宏观分析师', '宏观', 'M'],
  ['risk_agent', '风险分析师', '风险', 'R'],
  ['deep_search_agent', '深度研究员', '深搜', 'D'],
].map(([name, displayName, shortName, glyph]) => ({
  name,
  display_name: displayName,
  short_zh: shortName,
  description: displayName,
  glyph,
  color_token: 't-info',
  mandate: `${shortName}职责`,
  insert_text: `@${name} `,
}));

describe('CommandPalette expert commands', () => {
  it('为 API 中七位专家生成统一召唤命令', () => {
    const commands = buildExpertCommandDescriptors(profiles);
    expect(commands).toHaveLength(7);
    expect(commands.map((item) => item.label)).toContain('问技术面分析师…');
    expect(commands.find((item) => item.id === 'ask-technical_agent')?.insertText)
      .toBe('@technical_agent ');
  });

  it('执行命令会预填 mention、进入 /chat 并关闭面板', () => {
    const command = buildExpertCommandDescriptors(profiles)[3];
    const setDraft = vi.fn();
    const navigate = vi.fn();
    const close = vi.fn();
    runExpertCommand(command, { setDraft, navigate, close });
    expect(setDraft).toHaveBeenCalledWith('@technical_agent ');
    expect(navigate).toHaveBeenCalledWith('/chat');
    expect(close).toHaveBeenCalledOnce();
  });
});
