import type { SelectionItem } from './dashboard';

export type ChatHandoffSourceView = 'dashboard' | 'command_palette';

export interface DashboardResearchContext {
  selectedMetric?: { id: string; label?: string; value: number | string | boolean | null; unit?: string | null };
  timeRange?: { start?: string | null; end?: string | null; period?: string | null };
  dataRefs?: string[];
}

export interface ChatHandoff extends DashboardResearchContext {
  draft: string;
  activeSymbol?: string;
  selections?: SelectionItem[];
  sourceView: ChatHandoffSourceView;
  sourceTab?: string;
}

export interface PendingChatHandoffContext extends DashboardResearchContext {
  sessionId: string;
  sourceView: ChatHandoffSourceView;
  sourceTab?: string;
}
