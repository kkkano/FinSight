import { api } from '../http';
import type { CatalogModel, ModelCapabilities, ModelTestSelection } from '../../store/modelSelection';

export const modelsApi = {
  async getModels(): Promise<{ models: CatalogModel[] }> {
    return (await api.get('/api/models', { timeout: 15_000 })).data;
  },
  async getModelCapabilities(model: string, baseUrl: string): Promise<ModelCapabilities> {
    return (await api.get('/api/models/capabilities', {
      params: { model, base_url: baseUrl }, timeout: 15_000,
    })).data;
  },
  async testModel(selection: ModelTestSelection): Promise<{
    success: boolean; model: string; latency_ms: number; message: string;
  }> {
    return (await api.post('/api/models/test', selection, { timeout: 65_000 })).data;
  },
};
