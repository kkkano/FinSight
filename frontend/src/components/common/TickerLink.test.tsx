import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { describe, expect, it } from 'vitest';

import { extractTickers } from '../../utils/ticker';
import { createTickerLinkPlugin, tickerFromDashboardHref } from '../../utils/tickerMarkdown';
import { TickerLink } from './TickerLink';

function renderMessage(content: string): string {
  const plugin = createTickerLinkPlugin(extractTickers(content));
  return renderToStaticMarkup(
    <MemoryRouter>
      <ReactMarkdown
        remarkPlugins={[plugin]}
        components={{
          a: ({ href, children }) => {
            const ticker = tickerFromDashboardHref(href);
            return ticker ? <TickerLink ticker={ticker}>{children}</TickerLink> : <a href={href}>{children}</a>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </MemoryRouter>,
  );
}

describe('TickerLink in AI markdown', () => {
  it('renders confirmed AAPL as a dashboard link while CEO stays plain text', () => {
    const html = renderMessage('AAPL 的 CEO 表示业务稳定。');

    expect(html).toContain('href="/dashboard/AAPL"');
    expect(html).toContain('>AAPL</a>');
    expect(html).toContain('CEO');
    expect(html).not.toContain('/dashboard/CEO');
  });

  it('does not rewrite tickers inside existing links or inline code', () => {
    const html = renderMessage('[AAPL](https://example.com) 与 `AAPL`');

    expect(html).toContain('href="https://example.com"');
    expect(html).toContain('<code>AAPL</code>');
    expect(html).not.toContain('/dashboard/AAPL');
  });
});
