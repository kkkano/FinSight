export type WorkspaceHealthStatus =
  | { state: 'ok'; title: string; message: string }
  | { state: 'dry_run'; title: string; message: string }
  | { state: 'degraded'; title: string; message: string }
  | { state: 'retrieval_limited'; title: string; message: string }
  | { state: 'unreachable'; title: string; message: string };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

type HealthContext = { httpStatus?: number; capabilities?: unknown; capabilitiesStatus?: number };

export const buildWorkspaceHealthStatus = (payload: unknown, context: HealthContext = {}): WorkspaceHealthStatus => {
  if (!isRecord(payload)) {
    return {
      state: 'unreachable',
      title: '后端状态未知',
      message: '健康检查未返回有效数据，部分实时数据可能不可用。',
    };
  }

  const components = isRecord(payload.components) ? payload.components : {};
  const liveTools = isRecord(components.live_tools) ? components.live_tools : {};

  const componentLabels: Record<string, string> = {
    authentication: '身份认证', database: '数据存储', market_data: '行情数据',
    langgraph_runner: '研究运行服务', checkpointer: '运行恢复', llm: '模型服务',
  };
  const failed = Object.entries(components).filter(([name, component]) => name in componentLabels
    && isRecord(component) && ['error', 'degraded', 'initializing', 'unavailable'].includes(String(component.status)));
  if ((context.httpStatus ?? 200) >= 400 || ['degraded', 'not_ready', 'error'].includes(String(payload.status)) || failed.length > 0) {
    return {
      state: 'degraded', title: '部分服务暂不可用',
      message: failed.length > 0 ? `${failed.map(([name]) => componentLabels[name]).join('、')}暂不可用。` : '后端尚未就绪，部分请求可能无法完成。',
    };
  }

  if (liveTools.status === 'dry_run') {
    return {
      state: 'dry_run',
      title: 'Dry-run 模式',
      message: '当前为模拟工具调用模式，不会执行真实外部工具。',
    };
  }

  if (!['healthy', 'ready', 'ok'].includes(String(payload.status))) {
    return { state: 'unreachable', title: '后端状态未知', message: '健康检查未返回有效运行状态。' };
  }

  if ((context.capabilitiesStatus && context.capabilitiesStatus >= 400)
    || (context.capabilities !== undefined && !isRecord(context.capabilities))) {
    return { state: 'degraded', title: '服务能力状态未知', message: '后端连接正常，当前能力状态读取失败。' };
  }
  if (isRecord(context.capabilities)) {
    const capabilities = context.capabilities;
    const features = isRecord(capabilities.features) ? capabilities.features : {};
    const retrieval = isRecord(features.retrieval) ? features.retrieval : {};
    if (!['hybrid', 'semantic', 'lexical', 'unavailable'].includes(String(retrieval.mode))) {
      return { state: 'degraded', title: '服务能力状态未知', message: '后端连接正常，当前能力状态尚未确认。' };
    }
    if (capabilities.ready === false) {
      return { state: 'degraded', title: '部分服务暂不可用', message: '后端尚未就绪，部分请求可能无法完成。' };
    }
    if (retrieval.full_ready === false || retrieval.mode === 'lexical' || retrieval.mode === 'unavailable') {
      return {
        state: 'retrieval_limited', title: '检索能力受限',
        message: retrieval.mode === 'lexical' ? '当前使用词法检索，语义检索和重排暂不可用。'
          : retrieval.mode === 'unavailable' ? '当前检索服务暂不可用。' : '语义检索可用，完整检索能力尚未就绪。',
      };
    }
    if (capabilities.status === 'degraded') {
      return { state: 'degraded', title: '部分能力受限', message: '后端已连接，部分数据或运行能力暂不可用。' };
    }
  }

  return {
    state: 'ok',
    title: '后端连接正常',
    message: '健康检查通过。',
  };
};
