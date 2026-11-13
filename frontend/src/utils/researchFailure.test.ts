import { describe, expect, it } from 'vitest';
import { researchFailure, researchFailureMessage } from './researchFailure';
import { zh } from '../locales/zh';

describe('structured user-facing failure presentation', () => {
  it('maps codes and keeps raw provider text only in diagnostics', () => {
    const failure = researchFailure({ error_code: 'model_http_403', reason: 'Forbidden: provider balance', message: 'Traceback vendor failure' });
    expect(failure.message).toBe('模型服务拒绝了请求。');
    expect(failure.action).toBe('请检查模型权限和额度。');
    expect(failure.retryable).toBe(false);
    expect(failure.diagnostic).toContain('Forbidden: provider balance');
    expect(researchFailureMessage({ error_code: 'model_timeout', reason: 'get_stock_price failed' })).not.toContain('get_stock_price');
  });
  it('does not infer a code from unknown error prose', () => {
    expect(researchFailure({ message: 'quota authentication timeout expired' }).code).toBe('unknown');
    expect(researchFailureMessage({ reason: 'RuntimeError internal stack' }, '数据暂时无法读取。')).toBe('数据暂时无法读取。 请稍后重试。');
  });
  it('reads structured HTTP errors and supplies an action and retry policy for every entry', () => {
    expect(researchFailure({ response: { status: 401, data: { detail: 'Unauthorized' } } }).code).toBe('auth_required');
    expect(researchFailure({ response: { status: 500, data: { detail: { error_code: 'store_unavailable' } } } }).code).toBe('store_unavailable');
    expect(researchFailure({code:'ERR_BAD_RESPONSE',response:{status:503,data:{detail:{code:'store_unavailable'}}}}).code).toBe('store_unavailable');
    for (const [code, entry] of Object.entries(zh.errors)) {
      const failure = researchFailure({ error_code: code });
      expect(failure.message).toBe(entry.message);
      expect(typeof failure.action).toBe('string');
      expect(typeof failure.retryable).toBe('boolean');
    }
  });
});
