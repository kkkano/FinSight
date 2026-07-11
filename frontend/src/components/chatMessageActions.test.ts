import { describe, expect, it, vi } from 'vitest';

import {
  MESSAGE_ACTION_LABELS,
  canRetryMessage,
  copyTextWithFeedback,
  messageActionContainerClass,
} from './chatMessageActions';

describe('chat message actions', () => {
  it('reads the current loading state when retry is clicked', () => {
    let loading = true;
    const getState = () => ({ isChatLoading: loading });

    expect(canRetryMessage(getState)).toBe(false);
    loading = false;
    expect(canRetryMessage(getState)).toBe(true);
  });

  it('reports clipboard rejection through the failure callback', async () => {
    const onCopied = vi.fn();
    const onFailure = vi.fn();

    const copied = await copyTextWithFeedback(
      'answer',
      vi.fn().mockRejectedValue(new Error('permission denied')),
      onCopied,
      onFailure,
    );

    expect(copied).toBe(false);
    expect(onCopied).not.toHaveBeenCalled();
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it('reports successful clipboard writes', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const onCopied = vi.fn();
    const onFailure = vi.fn();

    expect(await copyTextWithFeedback('answer', writeText, onCopied, onFailure)).toBe(true);
    expect(writeText).toHaveBeenCalledWith('answer');
    expect(onCopied).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it('keeps flat actions discoverable by touch and keyboard with accessible names', () => {
    const className = messageActionContainerClass(true);
    expect(className).toContain('focus-within:opacity-100');
    expect(className).toContain('max-lg:opacity-100');
    expect(className).toContain('[@media(hover:none)]:opacity-100');
    expect(className).toContain('[@media(pointer:coarse)]:opacity-100');
    expect(MESSAGE_ACTION_LABELS).toEqual({
      retry: '重试回答',
      export: '导出回答',
      delete: '删除回答',
    });
  });
});
