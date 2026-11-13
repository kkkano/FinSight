import { create } from 'zustand';
import type { AppState } from './stateTypes';
import { createConversationServices } from './conversationPersistence';
import { createChatSessionSlice, getInitialTraceRawEnabled, getInitialTraceViewMode, getInitialTraceRawShowRawJson } from './chatSession';
import { createConversationsSlice } from './conversations';
import { createComposerSlice } from './composer';
import { createThemeSlice, getInitialTheme, getInitialColorConvention, getInitialLayout, applyThemeClass, applyColorConventionClass } from './theme';
import { createAuthSlice } from './auth';
import { getInitialEntryMode, getInitialSessionId, buildAnonymousSessionId } from './sessionIdentity';
import { flushPersist } from './persistScheduler';

export type { ColorConvention, EntryMode, AuthIdentity, ConversationSummary } from './stateTypes';
export { normalizePersistedEntryMode, buildAnonymousSessionId, buildUserSessionId, deriveUserIdFromSessionId, sessionBelongsToIdentity } from './sessionIdentity';
export { applyColorConventionClass } from './theme';

const initialTheme = getInitialTheme();
const initialColorConvention = getInitialColorConvention();
const initialLayout = getInitialLayout();
const initialEntryMode = getInitialEntryMode();
const initialSessionId = getInitialSessionId() || buildAnonymousSessionId();
const initialTraceRawEnabled = getInitialTraceRawEnabled();
const initialTraceViewMode = getInitialTraceViewMode();
const initialTraceRawShowRawJson = getInitialTraceRawShowRawJson();
applyThemeClass(initialTheme);
applyColorConventionClass(initialColorConvention);

/** 按域组合；持久化、恢复与账号切换实现留在各自slice及服务闭包。 */
export const useStore = create<AppState>((set, get, api) => {
  const services = createConversationServices(set, get);
  return {
    ...createChatSessionSlice(services, { initialSessionId, initialTraceRawEnabled, initialTraceViewMode, initialTraceRawShowRawJson })(set, get, api),
    ...createConversationsSlice(services, initialSessionId)(set, get, api),
    ...createComposerSlice(set, get, api),
    ...createThemeSlice({ initialTheme, initialColorConvention, initialLayout })(set, get, api),
    ...createAuthSlice(services, initialEntryMode)(set, get, api),
  };
});

// FE-01：页面卸载前把所有 pending 的去抖写盘落定，避免丢最后 ≤500ms 的流式内容
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => flushPersist());
}
