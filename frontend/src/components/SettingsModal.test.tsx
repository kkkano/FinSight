import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { SettingsModal } from './SettingsModal';

describe('SettingsModal', () => {
  it('separates settings into basic, advanced, and diagnostics layers', () => {
    const text = renderToStaticMarkup(
      <SettingsModal isOpen onClose={() => undefined} />,
    ).replace(/\s+/g, ' ');

    expect(text).toContain('基础设置');
    expect(text).toContain('高级设置');
    expect(text).toContain('运行诊断');
  });
});
