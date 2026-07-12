import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { SubscribeModal } from './SubscribeModal';

describe('SubscribeModal', () => {
  it('聚合邮件订阅与监控规则入口', () => {
    const html = renderToStaticMarkup(<SubscribeModal isOpen onClose={() => undefined} />);

    expect(html).toContain('邮件订阅');
    expect(html).toContain('监控规则');
    expect(html).toContain('subscriptions-open-monitor');
    expect(html).toContain('去配置');
  });
});
