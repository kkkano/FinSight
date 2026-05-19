import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { RecoverableErrorFallback } from './ErrorBoundary';

describe('RecoverableErrorFallback', () => {
  it('renders recovery actions for application failures', () => {
    const html = renderToStaticMarkup(
      <RecoverableErrorFallback
        error={new Error('network unavailable')}
        onRetry={() => undefined}
        onReload={() => undefined}
        onHome={() => undefined}
      />,
    );

    expect(html).toContain('加载失败');
    expect(html).toContain('重试');
    expect(html).toContain('返回欢迎页');
    expect(html).toContain('network unavailable');
  });
});
