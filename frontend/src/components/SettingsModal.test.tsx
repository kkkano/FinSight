import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { SettingsModal } from './SettingsModal';
import { ToastProvider } from './ui/Toast';

const renderModal = () =>
  renderToStaticMarkup(
    <ToastProvider>
      <SettingsModal isOpen onClose={() => undefined} />
    </ToastProvider>,
  ).replace(/\s+/g, ' ');

describe('SettingsModal', () => {
  it('separates settings into basic, advanced, and diagnostics layers', () => {
    const text = renderModal();

    expect(text).toContain('基础设置');
    expect(text).toContain('高级设置');
    expect(text).toContain('运行诊断');
  });

  it('UX-01: 隐私声明必须与实际行为一致（key 存服务端），禁止再出现"仅存储在浏览器本地"', () => {
    const text = renderModal();

    expect(text).not.toContain('仅存储在浏览器本地');
    expect(text).toContain('保存到服务端配置文件');
    expect(text).toContain('只显示掩码');
  });
});
