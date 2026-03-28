import axios from 'axios'
import settings from '@/plugins/settings'

const api = axios.create({
  baseURL: settings.apiBaseUrl,
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export const healthApi = {
  get: () => api.get('/health'),
}

export const documentsApi = {
  upload: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  list: () => api.get('/documents'),
  getStatus: (id) => api.get(`/documents/${id}/status`),
  getContent: (id) => api.get(`/documents/${id}/content`),
  delete: (id) => api.delete(`/documents/${id}`),
  retryExtract: (id) => api.post(`/documents/${id}/extract/retry`),
  retryIndex: (id, indexName = 'default') => api.post(`/documents/${id}/index/retry`, { index_name: indexName }),
}

export const searchApi = {
  search: (query, strategy = 'hybrid', topK = 10, indexName = 'default') =>
    api.post('/search', { query, strategy, top_k: topK, index_name: indexName }),
  index: (indexName, evidenceUnits) =>
    api.post('/search/index', { index_name: indexName, evidence_units: evidenceUnits }),
}

export const detectApi = {
  detect: (documentId, claims) =>
    api.post('/detect', { document_id: documentId, claims }),
}

export const llmApi = {
  analyze: (prompt, model) => api.post('/llm/analyze', { prompt, model }),
  analyzeDocument: (payload) => api.post('/llm/analyze/document', payload),
}

export const evalApi = {
  search: (data) => api.post('/eval/search', data),
  detection: (data) => api.post('/eval/detection', data),
  economics: (data) => api.post('/eval/economics', data),
  findExperiment: (data) => api.post('/eval/experiments/find', data),
  history: (limit = 20) => api.get('/eval/experiments/history', { params: { limit } }),
  historySummary: () => api.get('/eval/experiments/history/summary'),
  historyRun: (runId) => api.get(`/eval/experiments/history/${runId}`),
}

export default api
