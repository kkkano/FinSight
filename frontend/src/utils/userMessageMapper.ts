/**
 * 前端侧用户友好消息回退映射。
 *
 * 当后端 SSE 事件未携带 userMessage 字段时，
 * 根据 stage / eventType / agent 等维度提供中文消息。
 * 保持与后端 NODE_USER_MESSAGES 的同步（优先使用后端值）。
 */

// Graph 节点 → 用户友好消息（与 backend/graph/trace.py 保持同步）
const NODE_USER_MESSAGES: Record<string, string> = {
  langgraph_build_initial_state_start: '正在准备分析环境...',
  langgraph_reset_turn_start: '正在重置对话轮次...',
  langgraph_trim_messages_start: '正在整理对话记录...',
  langgraph_summarize_history_start: '正在回顾历史对话...',
  langgraph_normalize_ui_context_start: '正在理解你的操作意图...',
  langgraph_decide_output_mode_start: '正在判断最佳输出方式...',
  langgraph_chat_respond_start: '正在思考回复...',
  langgraph_resolve_subject_start: '正在识别你关注的标的...',
  langgraph_clarify_start: '需要进一步确认你的意图...',
  langgraph_parse_operation_start: '正在分析你想做什么...',
  langgraph_policy_gate_start: '正在制定分析策略...',
  langgraph_planner_start: '正在规划分析步骤...',
  langgraph_confirmation_gate_start: '正在确认执行方案...',
  langgraph_execute_plan_start: '正在执行分析计划...',
  langgraph_synthesize_start: '正在整合分析结果...',
  langgraph_render_start: '正在生成最终报告...',
  // _done 事件复用同一消息（前端可自行追加"完成"后缀）
  langgraph_build_initial_state_done: '分析环境准备完成',
  langgraph_resolve_subject_done: '已识别分析标的',
  langgraph_parse_operation_done: '操作分析完成',
  langgraph_policy_gate_done: '分析策略已制定',
  langgraph_planner_done: '分析步骤规划完成',
  langgraph_execute_plan_done: '分析计划执行完成',
  langgraph_synthesize_done: '分析结果整合完成',
  langgraph_render_done: '报告生成完成',
};

// Agent 中文显示名称（与 backend/graph/trace.py AGENT_DISPLAY_NAMES 保持同步）
export const AGENT_DISPLAY_NAMES: Record<string, string> = {
  price_agent: '行情分析师',
  news_agent: '新闻分析师',
  fundamental_agent: '基本面分析师',
  technical_agent: '技术面分析师',
  macro_agent: '宏观分析师',
  risk_agent: '风险分析师',
  deep_search_agent: '深度研究员',
};

/**
 * 获取 Agent 的中文显示名称。
 * 未找到时返回原始名称（去除 _agent 后缀并首字母大写）。
 */
export function getAgentDisplayName(agentName: string): string {
  if (AGENT_DISPLAY_NAMES[agentName]) {
    return AGENT_DISPLAY_NAMES[agentName];
  }
  // 回退：去除 _agent 后缀，首字母大写
  return agentName
    .replace(/_agent$/, '')
    .replace(/(^|\s)\S/g, (t) => t.toUpperCase());
}

/**
 * 根据 stage 获取用户友好消息（前端回退）。
 *
 * @param stage - SSE 事件的 stage 字段（如 "langgraph_planner_start"）
 * @param backendMessage - 后端已提供的 userMessage（优先使用）
 * @returns 中文用户友好消息，或 undefined（完全无法匹配时）
 */
export function resolveUserMessage(
  stage: string,
  backendMessage?: string,
): string | undefined {
  // 后端值优先
  if (backendMessage) return backendMessage;
  // 前端回退映射
  return NODE_USER_MESSAGES[stage];
}
