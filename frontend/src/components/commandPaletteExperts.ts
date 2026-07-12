import type { AgentProfileView } from '../types/agents';

export interface ExpertCommandDescriptor {
  id: string;
  label: string;
  keywords: string[];
  insertText: string;
}

export function buildExpertCommandDescriptors(
  profiles: AgentProfileView[],
): ExpertCommandDescriptor[] {
  return profiles.map((profile) => ({
    id: `ask-${profile.name}`,
    label: `问${profile.display_name}…`,
    keywords: ['agent', 'expert', '专家', profile.name, profile.short_zh, profile.mandate],
    insertText: profile.insert_text,
  }));
}

export function runExpertCommand(
  command: ExpertCommandDescriptor,
  actions: {
    setDraft: (text: string) => void;
    navigate: (path: string) => void;
    close: () => void;
  },
): void {
  actions.setDraft(command.insertText);
  actions.navigate('/chat');
  actions.close();
}
