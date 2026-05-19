export type WorkspaceHealthStatus =
  | { state: 'ok'; title: string; message: string }
  | { state: 'dry_run'; title: string; message: string }
  | { state: 'unreachable'; title: string; message: string };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

export const buildWorkspaceHealthStatus = (payload: unknown): WorkspaceHealthStatus => {
  if (!isRecord(payload)) {
    return {
      state: 'unreachable',
      title: '后端状态未知',
      message: '健康检查未返回有效数据，部分实时数据可能不可用。',
    };
  }

  const components = isRecord(payload.components) ? payload.components : {};
  const liveTools = isRecord(components.live_tools) ? components.live_tools : {};

  if (liveTools.status === 'dry_run') {
    return {
      state: 'dry_run',
      title: 'Dry-run 模式',
      message: '当前为模拟工具调用模式，不会执行真实外部工具。',
    };
  }

  return {
    state: 'ok',
    title: '后端连接正常',
    message: '健康检查通过。',
  };
};
