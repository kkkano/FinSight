import { create } from 'zustand';

interface CitationFocus {
  sessionId: string;
  runId?: string;
  sourceId: string;
  changedAt: number;
}

export const useCitationNavigation = create<{
  focus: CitationFocus | null;
  select: (focus: Omit<CitationFocus, 'changedAt'>) => void;
}>((set) => ({ focus: null, select: (focus) => set({ focus: { ...focus, changedAt: Date.now() } }) }));
