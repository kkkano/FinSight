import { describe, expect, it } from 'vitest';
import { filterResearchSkills, hasUnselectedSkillCommand, removeSkillCommand, skillCommandAt } from './skillCommands';

const catalogue = [
  { id: 'growth-quality', name: '成长质量', description: '分析盈利与成长', category: 'fundamental' },
  { id: 'ma-trend', name: '均线趋势', description: '分析均线趋势', category: 'technical' },
];

describe('research skill commands', () => {
  it('finds and removes only the active slash command while preserving the research question', () => {
    const value = '分析 AAPL /成长';
    const command = skillCommandAt(value);
    expect(command?.query).toBe('成长');
    expect(removeSkillCommand(value, command)).toBe('分析 AAPL ');
    expect(removeSkillCommand('/growth-quality 看看 AAPL', skillCommandAt('/growth-quality 看看 AAPL', 4))).toBe('看看 AAPL');
  });
  it('matches Chinese names and English slugs against the actual supplied catalogue', () => {
    expect(filterResearchSkills(catalogue, '成长')).toEqual([catalogue[0]]);
    expect(filterResearchSkills(catalogue, 'MA-')).toEqual([catalogue[1]]);
    expect(filterResearchSkills([], '')).toEqual([]);
    expect(filterResearchSkills(catalogue, 'unknown')).toEqual([]);
  });
  it('does not treat URLs or dates as slash commands, but blocks an unresolved standalone slash', () => {
    for (const value of ['看看 https://example.com/report', '分析 2026/11/07 的价格', '解释企业价值 / EBITDA']) {
      expect(skillCommandAt(value)).toBeNull();
      expect(hasUnselectedSkillCommand(value)).toBe(false);
    }
    expect(hasUnselectedSkillCommand('/growth-quality 看看 AAPL')).toBe(true);
    expect(hasUnselectedSkillCommand('/')).toBe(true);
    expect(hasUnselectedSkillCommand('/ 成长质量')).toBe(true);
  });
});
