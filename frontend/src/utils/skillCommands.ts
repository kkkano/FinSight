import type { ResearchSkill } from '../types/runtime';

export const MAX_SELECTED_SKILLS = 3;

export interface SkillCommand {
  start: number;
  end: number;
  query: string;
}

/** 仅匹配独立的 /命令，不把网址和日期中的斜线视为技能入口。 */
export function skillCommandAt(value: string, caret = value.length): SkillCommand | null {
  const match = /(?:^|\s)\/([^\s/]*)$/u.exec(value.slice(0, caret));
  if (!match) return null;
  const start = value.slice(0, caret).lastIndexOf('/');
  const remainder = /^[^\s/]*/u.exec(value.slice(caret))?.[0] || '';
  return { start, end: caret + remainder.length, query: match[1] };
}

export const hasUnselectedSkillCommand = (value: string): boolean => /^\s*\//u.test(value)
  || /(?:^|\s)\/(?:[^\s/]+|$)/u.test(value.trimEnd());

export function removeSkillCommand(value: string, command: SkillCommand | null): string {
  return command ? (value.slice(0, command.start) + value.slice(command.end)).trimStart() : value;
}

export function filterResearchSkills(skills: ResearchSkill[], query: string): ResearchSkill[] {
  const search = query.trim().toLocaleLowerCase();
  return skills.filter((skill) => !search || `${skill.id} ${skill.name} ${skill.description}`.toLocaleLowerCase().includes(search));
}
