import { api } from '../http';
import type * as Contracts from '../contracts';

export const ragApi = {
async diagnosticsRagStatus(): Promise<Contracts.ApiResponse> {
    const response = await api.get('/diagnostics/rag/status');
    return response.data;
  },

async diagnosticsRagRuns(params?: { limit?: number; cursor?: string | null; q?: string; fallback_only?: boolean; include_deleted?: boolean }): Promise<Contracts.ApiResponse> {
    const response = await api.get('/diagnostics/rag/runs', {
      params: {
        limit: params?.limit ?? 20,
        cursor: params?.cursor || undefined,
        q: params?.q || undefined,
        fallback_only: params?.fallback_only ?? false,
        include_deleted: params?.include_deleted || undefined,
      },
    });
    return response.data;
  },

async diagnosticsRagRunDetail(runId: string): Promise<Contracts.ApiResponse> {
    const response = await api.get(`/diagnostics/rag/runs/${encodeURIComponent(runId)}`);
    return response.data;
  },

async diagnosticsRagRunEvents(runId: string, limit: number = 500, includeDeleted: boolean = false): Promise<Contracts.ApiResponse> {
    const response = await api.get(`/diagnostics/rag/runs/${encodeURIComponent(runId)}/events`, { params: { limit, include_deleted: includeDeleted || undefined } });
    return response.data;
  },

async diagnosticsRagRunDocuments(runId: string, limit: number = 200): Promise<Contracts.ApiResponse> {
    const response = await api.get('/diagnostics/rag/documents', { params: { run_id: runId, limit } });
    return response.data;
  },

async diagnosticsRagRunChunks(runId: string, limit: number = 500): Promise<Contracts.ApiResponse> {
    const response = await api.get('/diagnostics/rag/chunks', { params: { run_id: runId, limit } });
    return response.data;
  },

async diagnosticsRagRunHits(runId: string, limit: number = 500): Promise<Contracts.ApiResponse> {
    const response = await api.get('/diagnostics/rag/hits', { params: { run_id: runId, limit } });
    return response.data;
  },

async diagnosticsRagCollections(params?: { limit?: number }): Promise<Contracts.ApiResponse> {
    const response = await api.get('/diagnostics/rag/collections', { params: { limit: params?.limit ?? 200 } });
    return response.data;
  },

async diagnosticsRagCollectionDocuments(collection: string, limit: number = 200): Promise<Contracts.ApiResponse> {
    const response = await api.get(`/diagnostics/rag/collections/${encodeURIComponent(collection)}/documents`, { params: { limit } });
    return response.data;
  },

async diagnosticsRagCollectionChunks(collection: string, limit: number = 500): Promise<Contracts.ApiResponse> {
    const response = await api.get(`/diagnostics/rag/collections/${encodeURIComponent(collection)}/chunks`, { params: { limit } });
    return response.data;
  },

async diagnosticsRagDbBrowser(tableName: string, params?: { limit?: number; offset?: number; q?: string; collection?: string; run_id?: string; source_doc_id?: string; layer?: string }): Promise<Contracts.ApiResponse> {
    const response = await api.get(`/diagnostics/rag/db-browser/${encodeURIComponent(tableName)}`, {
      params: {
        limit: params?.limit ?? 50,
        offset: params?.offset ?? 0,
        q: params?.q || undefined,
        collection: params?.collection || undefined,
        run_id: params?.run_id || undefined,
        source_doc_id: params?.source_doc_id || undefined,
        layer: params?.layer || undefined,
      },
    });
    return response.data;
  },

async diagnosticsRagSearchPreview(payload: { query: string; collection: string; top_k?: number }): Promise<Contracts.ApiResponse> {
    const response = await api.post('/diagnostics/rag/search-preview', payload);
    return response.data;
  }
};
