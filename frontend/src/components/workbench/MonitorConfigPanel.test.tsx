import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { ToastProvider } from '../ui';
import { MonitorConfigPanel } from './MonitorConfigPanel';

// 静态渲染不触发 useEffect / 真实请求，mock 掉 apiClient 隔离副作用。
// 初始状态：targets 为空、settings 为 null（smtp_configured 默认 false）。
vi.mock('../../api/client', () => ({
  apiClient: {
    getMonitorTargets: vi.fn(),
    createMonitorTarget: vi.fn(),
    patchMonitorTarget: vi.fn(),
    deleteMonitorTarget: vi.fn(),
    getMonitorSettings: vi.fn(),
    updateMonitorSettings: vi.fn(),
  },
}));

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(<ToastProvider>{node}</ToastProvider>).replace(/\s+/g, ' ');

describe('MonitorConfigPanel', () => {
  it('渲染面板头部与添加监控按钮', () => {
    const text = renderText(<MonitorConfigPanel sessionId="s-1" />);
    expect(text).toContain('监控配置');
    expect(text).toContain('添加监控');
    expect(text).toContain('monitor-add-button');
  });

  it('渲染邮件通知分区（含说明文案）', () => {
    const text = renderText(<MonitorConfigPanel sessionId="s-1" />);
    expect(text).toContain('邮件通知');
    expect(text).toContain('notification-settings');
    // 说明文案
    expect(text).toContain('盯盘扫描发现新异常时会汇总发送到该邮箱');
  });

  it('SMTP 未配置时显示不可用提示（初始 settings 为 null）', () => {
    const text = renderText(<MonitorConfigPanel sessionId="s-1" />);
    expect(text).toContain('notification-smtp-unavailable');
    expect(text).toContain('服务器未配置 SMTP，邮件通知不可用');
  });

  it('空列表时显示引导文案 + 持仓自动监控说明', () => {
    const text = renderText(<MonitorConfigPanel sessionId="s-1" />);
    expect(text).toContain('暂无自定义监控');
    expect(text).toContain('持仓标的自动纳入监控');
  });
});
