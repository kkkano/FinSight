import axios from 'axios';
// 确保 types/index.ts 文件定义了这些接口
// 如果没有，请将 type 导入行注释掉，使用 any 暂时代替
import type { ChatResponse, KlineResponse, RawSSEEvent, RawEventType } from '../types/index';
import type { SelectionItem } from '../types/dashboard';
import { API_BASE_URL, buildApiUrl } from '../config/runtime';

/**
 * Chat Context - 临时上下文（不入库，仅本次请求生效）
 */
export interface ChatContext {
  active_symbol?: string;
  view?: string;
  selection?: SelectionItem;
  selections?: SelectionItem[];
}

export interface ChatOptions {
  output_mode?: 'chat' | 'brief' | 'investment_report';
  strict_selection?: boolean;
  locale?: string;
  trace_raw_override?: 'on' | 'off' | 'inherit';
}

export interface ReportIndexItem {
  report_id: string;
  session_id: string;
  ticker?: string;
  title?: string;
  summary?: string;
  generated_at?: string;
  confidence_score?: number;
  is_favorite?: boolean;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
}

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
  },
  timeout: 120000, // 120秒超时，防止 LLM 生成长文时前端断开
});

// 响应拦截器：处理后端返回的非 200 错误
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response || error.message);
    return Promise.reject(error);
  }
);

export const createCancelToken = () => {
  return axios.CancelToken.source();
};

export const apiClient = {
  // 发送聊天消息（协调者主入口）
  async sendMessage(query: string, sessionId?: string, options?: ChatOptions): Promise<ChatResponse> {
    try {
      const response = await api.post<ChatResponse>('/chat/supervisor', {
        query,
        session_id: sessionId,
        options,
      });

      // 兼容性处理：如果后端返回结构不一致，确保前端不白屏
      if (!response.data) {
        throw new Error("Empty response from server");
      }
      return response.data;
    } catch (error) {
      console.error("sendMessage failed:", error);
      throw error;
    }
  },

  // 获取 K 线数据
  async fetchKline(ticker: string, period: string = "1y", interval: string = "1d"): Promise<KlineResponse> {
    const response = await api.get<KlineResponse>(`/api/stock/kline/${ticker}`, {
      params: { period, interval }
    });
    return response.data;
  },

  async fetchStockPrice(ticker: string): Promise<any> {
    const response = await api.get(`/api/stock/price/${encodeURIComponent(ticker)}`);
    return response.data;
  },

  // 将图表数据加入聊天上下文
  async addChartData(ticker: string, summary: string): Promise<any> {
    const response = await api.post('/api/chat/add-chart-data', {
      ticker,
      summary
    });
    return response.data;
  },

  // 智能检测图表类型
  async detectChartType(query: string, ticker?: string): Promise<any> {
    try {
      const response = await api.post('/api/chart/detect', {
        query,
        ticker
      });
      return response.data;
    } catch {
      // 即使检测失败也不要阻断流程，返回默认值
      return { success: false, should_generate: false };
    }
  },

  // 获取用户配置
  async getConfig(): Promise<any> {
    const response = await api.get('/api/config');
    return response.data;
  },

  // 保存用户配置
  async saveConfig(config: any): Promise<any> {
    const response = await api.post('/api/config', config);
    return response.data;
  },

  async listReportIndex(params: {
    sessionId: string;
    ticker?: string;
    query?: string;
    dateFrom?: string;
    dateTo?: string;
    tag?: string;
    favoriteOnly?: boolean;
    limit?: number;
  }): Promise<{ success: boolean; session_id: string; items: ReportIndexItem[]; count: number }> {
    const response = await api.get('/api/reports/index', {
      params: {
        session_id: params.sessionId,
        ticker: params.ticker,
        query: params.query,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        tag: params.tag,
        favorite_only: params.favoriteOnly,
        limit: params.limit,
      },
    });
    return response.data;
  },

  async getReportReplay(params: {
    sessionId: string;
    reportId: string;
  }): Promise<{ success: boolean; session_id: string; report: any; citations: any[]; trace_digest: Record<string, any> }> {
    const response = await api.get(`/api/reports/replay/${encodeURIComponent(params.reportId)}`, {
      params: { session_id: params.sessionId },
    });
    return response.data;
  },

  async setReportFavorite(params: {
    sessionId: string;
    reportId: string;
    isFavorite: boolean;
  }): Promise<{ success: boolean; session_id: string; report_id: string; is_favorite: boolean }> {
    const response = await api.post(`/api/reports/${encodeURIComponent(params.reportId)}/favorite`, {
      session_id: params.sessionId,
      is_favorite: params.isFavorite,
    });
    return response.data;
  },

  // User profile / watchlist
  async getUserProfile(user_id?: string): Promise<any> {
    const response = await api.get('/api/user/profile', {
      params: user_id ? { user_id } : {},
    });
    return response.data;
  },

  async addWatchlist(payload: { user_id?: string; ticker: string }): Promise<any> {
    const response = await api.post('/api/user/watchlist/add', payload);
    return response.data;
  },

  async removeWatchlist(payload: { user_id?: string; ticker: string }): Promise<any> {
    const response = await api.post('/api/user/watchlist/remove', payload);
    return response.data;
  },

  // 订阅管理
  async subscribe(payload: {
    email: string;
    ticker: string;
    alert_types?: string[];
    price_threshold?: number | null;
  }): Promise<any> {
    const response = await api.post('/api/subscribe', payload);
    return response.data;
  },

  async unsubscribe(payload: { email: string; ticker?: string | null }): Promise<any> {
    const response = await api.post('/api/unsubscribe', payload);
    return response.data;
  },

  async listSubscriptions(email?: string): Promise<any> {
    const response = await api.get('/api/subscriptions', {
      params: email ? { email } : {},
    });
    return response.data;
  },

  async toggleSubscription(payload: { email: string; ticker: string; enabled: boolean }): Promise<any> {
    const response = await api.post('/api/subscription/toggle', payload);
    return response.data;
  },

  // 导出 PDF
  async exportPDF(messages: any[], charts?: any[], title?: string): Promise<Blob> {
    const response = await api.post('/api/export/pdf', {
      messages,
      charts: charts || [],
      title: title || 'FinSight 对话记录'
    }, {
      responseType: 'blob' // 关键：声明返回二进制流
    });
    return response.data;
  },

  async diagnosticsOrchestrator(): Promise<any> {
    const response = await api.get('/diagnostics/orchestrator');
    return response.data;
  },

  // 健康检查（含子Agent状态）
  async healthCheck(): Promise<any> {
    const response = await api.get('/health');
    return response.data;
  },

  // 流式发送消息 - SSE 逐字输出
  async sendMessageStream(
    query: string,
    onToken: (token: string) => void,
    onToolStart?: (name: string) => void,
    onToolEnd?: () => void,
    onDone?: (report?: any, thinking?: any[], meta?: any) => void,  // Phase 2: 支持 report 数据
    onError?: (error: string) => void,
    onThinking?: (step: any) => void,
    history?: Array<{role: string, content: string}>,  // 对话历史
    onRawEvent?: (event: RawSSEEvent) => void,  // 原始 SSE 事件回调
    context?: ChatContext,  // 临时上下文（不入库，仅本次请求生效）
    options?: ChatOptions,  // 输出/路由选项（不入库，仅本次请求生效）
    sessionId?: string,
    traceRawEnabled: boolean = true,
  ): Promise<void> {
    let eventCounter = 0;

    const body: Record<string, any> = { query, history };
    if (sessionId) {
      body.session_id = sessionId;
    }
    if (context) {
      body.context = context;
    }
    if (options) {
      body.options = options;
    }

    const response = await fetch(buildApiUrl('/chat/supervisor/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error('No reader available');

    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const rawJson = line.slice(6);
          try {
            const data = JSON.parse(rawJson);

            // 发送原始事件到控制台
            if (onRawEvent && traceRawEnabled) {
              const eventType: RawEventType = data.type || 'any';
              onRawEvent({
                id: `sse-${Date.now()}-${eventCounter++}`,
                timestamp: new Date().toISOString(),
                eventType,
                rawData: rawJson,
                parsedData: data,
                size: new Blob([rawJson]).size,
                sessionId: typeof data.session_id === 'string' ? data.session_id : undefined,
              });
            }

            if (data.type === 'token' && data.content) {
              // 立即调用 onToken，确保流式效果
              onToken(data.content);
            } else if (data.type === 'tool_start') {
              onToolStart?.(data.name);
            } else if (data.type === 'tool_end') {
              onToolEnd?.();
            } else if (data.type === 'thinking') {
              // 从 thinking 事件中提取 ThinkingStep 格式的数据
              // 后端发送 {type: "thinking", stage: "...", message: "...", result: {...}, timestamp: "..."}
              const step = {
                stage: data.stage || 'any',
                message: data.message,
                result: data.result,
                timestamp: data.timestamp || new Date().toISOString()
              };
              onThinking?.(step);
            } else if (data.type === 'done') {
              onDone?.(data.report, data.thinking, data);  // Phase 2: 传递 report 数据
            } else if (data.type === 'error') {
              onError?.(data.message);
            } else if (['supervisor_start', 'agent_start', 'agent_done', 'agent_error', 'forum_start', 'forum_done'].includes(data.type)) {
            // Agent 进度事件 - 转换为 thinking 格式（兼容后端字段）
              const agentName = data.agent || data.name;
              onThinking?.({
                stage: data.type,
                message: agentName ? `${agentName} Agent` : (data.message || ''),
                result: {
                  agent: agentName,
                  status: data.status,
                  step_id: data.step_id,
                  inputs: data.inputs,
                  error: data.error,
                  agents: data.agents,
                },
                timestamp: new Date().toISOString()
              });
            }
          } catch (e) {
            // 解析失败也要发送到控制台
            if (onRawEvent && traceRawEnabled) {
              onRawEvent({
                id: `sse-err-${Date.now()}-${eventCounter++}`,
                timestamp: new Date().toISOString(),
                eventType: 'any',
                rawData: rawJson,
                parsedData: { parseError: true, raw: rawJson, error: String(e) },
                size: new Blob([rawJson]).size,
                sessionId: undefined,
              });
            }
          }
        }
      }
    }
  },
};



