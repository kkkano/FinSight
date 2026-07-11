import { api } from '../http';
import type * as Contracts from '../contracts';

export const configApi = {
// 获取用户配置
  async getConfig(): Promise<Contracts.ConfigResponse> {
    const response = await api.get('/api/config');
    return response.data;
  },

// 保存用户配置
  async saveConfig<T extends object>(config: T): Promise<Contracts.SaveConfigResponse> {
    const response = await api.post('/api/config', config);
    return response.data;
  }
};
