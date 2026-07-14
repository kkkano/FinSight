import type { SelectionItem } from './dashboard';

export type ChatHandoffSourceView = 'dashboard' | 'workbench' | 'command_palette';

export interface ChatHandoff {
  draft: string;
  activeSymbol?: string;
  selections?: SelectionItem[];
  sourceView: ChatHandoffSourceView;
  sourceTab?: string;
}

export interface PendingChatHandoffContext {
  sessionId: string;
  sourceView: ChatHandoffSourceView;
  sourceTab?: string;
}
