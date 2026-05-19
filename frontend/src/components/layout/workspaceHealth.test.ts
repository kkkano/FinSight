import { describe, expect, it } from 'vitest';

import { buildWorkspaceHealthStatus } from './workspaceHealth';

describe('buildWorkspaceHealthStatus', () => {
  it('maps dry-run health checks to a persistent workspace warning', () => {
    const status = buildWorkspaceHealthStatus({
      components: {
        live_tools: { status: 'dry_run' },
      },
    });

    expect(status.state).toBe('dry_run');
    expect(status.title).toBe('Dry-run 模式');
    expect(status.message).toContain('模拟工具调用');
  });

  it('maps invalid health payloads to an unreachable state', () => {
    const status = buildWorkspaceHealthStatus(null);

    expect(status.state).toBe('unreachable');
    expect(status.title).toBe('后端状态未知');
  });
});
