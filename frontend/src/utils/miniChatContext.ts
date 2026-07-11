import type { ChatContext } from '../api/contracts';
import type { SelectionItem } from '../types/dashboard';

interface MiniChatContextInput {
  contextEnabled: boolean;
  currentSymbol: string | null;
  activeSelections: SelectionItem[];
  subscriptionEmail?: string;
}

/** MiniChat 的临时上下文单一构造入口，确保当前 Dashboard symbol 真正进入请求。 */
export function buildMiniChatContext({
  contextEnabled,
  currentSymbol,
  activeSelections,
  subscriptionEmail,
}: MiniChatContextInput): ChatContext | undefined {
  const context: ChatContext = {};
  if (contextEnabled && currentSymbol) {
    context.active_symbol = currentSymbol;
    context.view = 'dashboard';
  }
  if (activeSelections.length === 1) context.selection = activeSelections[0];
  if (activeSelections.length > 1) context.selections = activeSelections;
  if (subscriptionEmail) context.user_email = subscriptionEmail;
  return Object.keys(context).length > 0 ? context : undefined;
}
