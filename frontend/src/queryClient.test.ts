import { describe, expect, it } from 'vitest';

import { queryClient } from './queryClient';

describe('queryClient defaults', () => {
  it('统一使用 30 秒数据新鲜期且不自动重试', () => {
    const defaults = queryClient.getDefaultOptions();
    expect(defaults.queries?.staleTime).toBe(30_000);
    expect(defaults.queries?.retry).toBe(false);
    expect(defaults.mutations?.retry).toBe(false);
  });
});
