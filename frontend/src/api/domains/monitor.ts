import { api } from '../http';
import type * as Contracts from '../contracts';

export const monitorApi = {
// 订阅管理
  async subscribe(payload: {
    email: string;
    ticker: string;
    alert_types?: string[];
    price_threshold?: number | null;
    alert_mode?: 'price_change_pct' | 'price_target';
    price_target?: number | null;
    direction?: 'above' | 'below';
  }): Promise<Contracts.ApiResponse> {
    const response = await api.post('/api/subscribe', payload);
    return response.data;
  },

async unsubscribe(payload: { email: string; ticker?: string | null }): Promise<Contracts.ApiResponse> {
    const response = await api.post('/api/unsubscribe', payload);
    return response.data;
  },

async listSubscriptions(email?: string): Promise<Contracts.ApiResponse> {
    const response = await api.get('/api/subscriptions', {
      params: email ? { email } : {},
    });
    return response.data;
  },

async listAlertFeed(params: {
    email: string;
    limit?: number;
    since?: string;
  }): Promise<{
    success: boolean;
    email: string;
    events: Contracts.AlertFeedEvent[];
    count: number;
  }> {
    const response = await api.get('/api/alerts/feed', {
      params: {
        email: params.email,
        limit: params.limit,
        since: params.since,
      },
    });
    return response.data;
  },

async toggleSubscription(payload: { email: string; ticker: string; enabled: boolean }): Promise<Contracts.ApiResponse> {
    const response = await api.post('/api/subscription/toggle', payload);
    return response.data;
  },

/** 手动触发盯盘扫描 —— POST /api/monitor/scan */
  async triggerMonitorScan(sessionId: string): Promise<Contracts.MonitorScanResponse> {
    const response = await api.post<Contracts.MonitorScanResponse>(
      '/api/monitor/scan',
      null,
      { params: { session_id: sessionId } },
    );
    return response.data;
  },

/** 获取盯盘对象列表 —— GET /api/monitor/targets */
  async getMonitorTargets(sessionId: string): Promise<Contracts.MonitorTargetsResponse> {
    const response = await api.get<Contracts.MonitorTargetsResponse>('/api/monitor/targets', {
      params: { session_id: sessionId },
    });
    return response.data;
  },

/** 创建盯盘对象 —— POST /api/monitor/targets */
  async createMonitorTarget(params: Contracts.CreateMonitorTargetParams): Promise<Contracts.MonitorTargetResponse> {
    const response = await api.post<Contracts.MonitorTargetResponse>('/api/monitor/targets', params);
    return response.data;
  },

/** 更新盯盘对象（阈值 / 开关）—— PATCH /api/monitor/targets/{id} */
  async patchMonitorTarget(
    sessionId: string,
    targetId: string,
    params: Contracts.PatchMonitorTargetParams,
  ): Promise<Contracts.MonitorTargetResponse> {
    const response = await api.patch<Contracts.MonitorTargetResponse>(
      `/api/monitor/targets/${encodeURIComponent(targetId)}`,
      params,
      { params: { session_id: sessionId } },
    );
    return response.data;
  },

/** 删除盯盘对象 —— DELETE /api/monitor/targets/{id} */
  async deleteMonitorTarget(
    sessionId: string,
    targetId: string,
  ): Promise<{ success: boolean }> {
    const response = await api.delete(
      `/api/monitor/targets/${encodeURIComponent(targetId)}`,
      { params: { session_id: sessionId } },
    );
    return response.data;
  },

/** 获取宏观日历（财报/分红/宏观事件）—— GET /api/monitor/macro-calendar */
  async getMonitorMacroCalendar(
    sessionId: string,
    daysAhead = 14,
  ): Promise<Contracts.MacroCalendarResponse> {
    const response = await api.get<Contracts.MacroCalendarResponse>('/api/monitor/macro-calendar', {
      params: { session_id: sessionId, days_ahead: daysAhead },
    });
    return response.data;
  },

/** 获取通知设置（邮箱 / 开关 / SMTP 是否就绪）—— GET /api/monitor/settings */
  async getMonitorSettings(sessionId: string): Promise<Contracts.MonitorSettingsResponse> {
    const response = await api.get<Contracts.MonitorSettingsResponse>('/api/monitor/settings', {
      params: { session_id: sessionId },
    });
    return response.data;
  },

/** 更新通知设置 —— PUT /api/monitor/settings（SMTP 未配置时启用会返回 422） */
  async updateMonitorSettings(
    sessionId: string,
    notifyEmail: string | null,
    notifyEnabled: boolean,
  ): Promise<Contracts.UpdateMonitorSettingsResponse> {
    const response = await api.put<Contracts.UpdateMonitorSettingsResponse>('/api/monitor/settings', {
      session_id: sessionId,
      notify_email: notifyEmail,
      notify_enabled: notifyEnabled,
    });
    return response.data;
  }
};
