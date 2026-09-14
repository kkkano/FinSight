import { describe, expect, it } from 'vitest';

import { getPredictionIdFromSearch } from './chatChartIntent';

describe('prediction deep-link contract', () => {
  it('只读取 analysis 参数中的 prediction id', () => {
    expect(getPredictionIdFromSearch('?analysis=pred-123&entry=999999&data=%5B999999%5D')).toBe('pred-123');
  });

  it('拒绝缺失或过长的 id', () => {
    expect(getPredictionIdFromSearch('?entry=100')).toBeNull();
    expect(getPredictionIdFromSearch(`?analysis=${'x'.repeat(161)}`)).toBeNull();
  });
});
