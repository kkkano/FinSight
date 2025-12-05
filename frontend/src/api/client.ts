import axios from 'axios';
// 确保你有 types/index.ts 文件定义了这些接口
// 如果没有，请将 type 导入行注释掉，使用 any 暂时代替
import type { ChatResponse, KlineResponse } from '../types/index';

// 本地开发地址，生产环境请改为实际域名
const API_BASE_URL = 'http://127.0.0.1:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
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
  // 发送聊天消息
  async sendMessage(query: string, sessionId?: string): Promise<ChatResponse> {
    try {
      const response = await api.post<ChatResponse>('/chat', {
        query,
        session_id: sessionId
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
    } catch (error) {
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
  }
};
