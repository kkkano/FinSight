import type { StateCreator } from 'zustand';
import type { AppState } from './stateTypes';
import type { PendingChatHandoffContext } from '../types/chatHandoff';
import { sessionBelongsToIdentity } from './sessionIdentity';

export type ComposerSlice = Pick<AppState, "draft" | "draftBySession" | "pendingChatHandoffContextBySession" | "setDraft" | "setPendingChatHandoffContext" | "takePendingChatHandoffContext">;

export const createComposerSlice: StateCreator<AppState, [], [], ComposerSlice> = (set) => ({
draft: '',

draftBySession: {},

pendingChatHandoffContextBySession: {},

setDraft: (text) =>
    set((state) => ({
      draft: text,
      draftBySession: {
        ...state.draftBySession,
        [state.sessionId]: text,
      },
    })),

setPendingChatHandoffContext: (sessionId, value) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (
        !normalized
        || value.sessionId !== normalized
        || !sessionBelongsToIdentity(normalized, state.authIdentity)
      ) return {};
      return {
        pendingChatHandoffContextBySession: {
          ...state.pendingChatHandoffContextBySession,
          [normalized]: value,
        },
      };
    }),

takePendingChatHandoffContext: (sessionId) => {
    const normalized = String(sessionId || '').trim();
    if (!normalized) return undefined;
    let taken: PendingChatHandoffContext | undefined;
    set((state) => {
      if (!sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const candidate = state.pendingChatHandoffContextBySession[normalized];
      if (!candidate || candidate.sessionId !== normalized) return {};
      taken = candidate;
      const next = { ...state.pendingChatHandoffContextBySession };
      delete next[normalized];
      return { pendingChatHandoffContextBySession: next };
    });
    return taken;
  }
});
