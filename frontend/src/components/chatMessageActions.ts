type ChatLoadingState = { isChatLoading: boolean };

export const MESSAGE_ACTION_LABELS = {
  retry: '重试回答',
  export: '导出回答',
  delete: '删除回答',
} as const;

export function canRetryMessage(getState: () => ChatLoadingState): boolean {
  return !getState().isChatLoading;
}

export async function copyTextWithFeedback(
  content: string,
  writeText: (text: string) => Promise<void>,
  onCopied: () => void,
  onFailure: (error: unknown) => void,
): Promise<boolean> {
  try {
    await writeText(content);
    onCopied();
    return true;
  } catch (error) {
    onFailure(error);
    return false;
  }
}

export function messageActionContainerClass(inline: boolean = false): string {
  const base = 'flex items-center gap-1 text-fin-muted pointer-events-auto';
  if (!inline) return `${base} absolute bottom-0 right-2 translate-y-full`;
  return `${base} mt-4 opacity-0 group-hover/msg:opacity-100 focus-within:opacity-100 max-lg:opacity-100 [@media(hover:none)]:opacity-100 [@media(pointer:coarse)]:opacity-100 transition-opacity duration-200`;
}
