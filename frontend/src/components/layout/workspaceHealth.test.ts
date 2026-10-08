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
    expect(buildWorkspaceHealthStatus({}).state).toBe('unreachable');
  });

  it('does not call a JSON response healthy when the HTTP status is 503', () => {
    expect(buildWorkspaceHealthStatus({ status: 'healthy' }, { httpStatus: 503 }).state).toBe('degraded');
    expect(buildWorkspaceHealthStatus({ status: 'degraded', components: { database: { status: 'error' } } }).message).toContain('数据存储');
  });

  it('shows lexical retrieval limits even when core readiness is successful', () => {
    const status = buildWorkspaceHealthStatus({ status: 'healthy' }, {
      capabilities: { status: 'ready', ready: true, features: { retrieval: { mode: 'lexical', full_ready: false } } },
    });
    expect(status.state).toBe('retrieval_limited');
    expect(status.message).toContain('词法检索');
  });

  it('does not show a warning when core services and full retrieval are ready', () => {
    expect(buildWorkspaceHealthStatus({ status: 'healthy' }, {
      capabilities: { status: 'ready', ready: true, features: { retrieval: { mode: 'hybrid', full_ready: true } } },
    }).state).toBe('ok');
  });
});
