import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { healthApi, documentsApi, searchApi, detectApi, evalApi } from '@/services/api'

const COMPARE_SESSION_STORAGE_KEY = 'docs-regex.compare-session'

function loadStoredCompareSession() {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(COMPARE_SESSION_STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    window.localStorage.removeItem(COMPARE_SESSION_STORAGE_KEY)
    return null
  }
}

export const useAppStore = defineStore('app', () => {
  const health = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const documents = ref([])
  const currentDocument = ref(null)
  const searchResults = ref([])
  const detectionResults = ref([])
  const experimentResults = ref({})
  const experimentHistory = ref([])
  const experimentHistorySummary = ref(null)
  const currentExperimentRun = ref(null)
  const compareSession = ref(loadStoredCompareSession())
  const metrics = ref({
    search: {},
    detection: {},
    economics: {},
  })

  const isHealthy = computed(() => health.value?.status === 'healthy')

  async function fetchHealth() {
    try {
      const { data } = await healthApi.get()
      health.value = data
    } catch (e) {
      health.value = { status: 'error', error: e.message }
    }
  }

  async function fetchDocuments() {
    loading.value = true
    try {
      const { data } = await documentsApi.list()
      const rawDocs = data.documents || []
      const withStatus = await Promise.all(
        rawDocs.map(async (doc) => {
          const docId = doc.document_id || doc.id
          const base = {
            ...doc,
            id: docId,
            document_id: docId,
          }
          if (!docId) return base
          try {
            const { data: statusData } = await documentsApi.getStatus(docId)
            return {
              ...base,
              status: statusData.status,
              progress: statusData.progress,
              pages_processed: statusData.pages_processed,
              total_pages: statusData.total_pages,
              error: statusData.error,
              index_status: statusData.index_status,
              indexed_count: statusData.indexed_count,
              details: statusData.details,
            }
          } catch {
            return {
              ...base,
              status: base.status || 'unknown',
            }
          }
        })
      )
      documents.value = withStatus
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function uploadDocument(file) {
    loading.value = true
    error.value = null
    try {
      const { data } = await documentsApi.upload(file)
      return data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function getDocumentStatus(id) {
    const { data } = await documentsApi.getStatus(id)
    return data
  }

  async function getDocumentContent(id) {
    const { data } = await documentsApi.getContent(id)
    currentDocument.value = data
    return data
  }

  async function deleteDocument(id) {
    await documentsApi.delete(id)
    documents.value = documents.value.filter((d) => (d.document_id || d.id) !== id)
  }

  async function retryExtract(id) {
    const { data } = await documentsApi.retryExtract(id)
    return data
  }

  async function retryIndex(id, indexName = 'default') {
    const { data } = await documentsApi.retryIndex(id, indexName)
    return data
  }

  async function search(query, strategy = 'hybrid', topK = 10, indexName = 'default') {
    loading.value = true
    try {
      const { data } = await searchApi.search(query, strategy, topK, indexName)
      searchResults.value = data.results || []
      return data
    } finally {
      loading.value = false
    }
  }

  async function detect(documentId, claims) {
    loading.value = true
    try {
      const { data } = await detectApi.detect(documentId, claims)
      detectionResults.value = (data.results || []).map((item) => {
        const inconsistent = Array.isArray(item.conflicts) && item.conflicts.length > 0
        return {
          ...item,
          verdict: inconsistent ? 'inconsistent' : 'consistent',
          rationale: inconsistent
            ? item.conflicts.map((c) => c.type || 'conflict').join(', ')
            : 'Aucune incohérence détectée',
          predicted: inconsistent,
          gold: inconsistent,
        }
      })
      return data
    } finally {
      loading.value = false
    }
  }

  async function runExperiment(config) {
    loading.value = true
    try {
      const payload = {
        dataset_name: config.datasetName || 'kensho/FIND',
        split: config.split,
        max_samples: config.maxSamples,
        index_name: config.indexName,
        top_k: config.topK,
        strategies: config.strategies,
        streaming: config.streaming,
        cache_dir: config.cacheDir,
        max_query_chars: config.maxQueryChars || 8192,
      }
      const { data } = await evalApi.findExperiment(payload)
      experimentResults.value = data
      await fetchExperimentHistory()
      await fetchExperimentHistorySummary()
      return data
    } finally {
      loading.value = false
    }
  }

  async function fetchExperimentHistory(limit = 20) {
    const { data } = await evalApi.history(limit)
    experimentHistory.value = data.runs || []
    return data
  }

  async function fetchExperimentHistorySummary() {
    const { data } = await evalApi.historySummary()
    experimentHistorySummary.value = data
    return data
  }

  async function fetchExperimentRun(runId) {
    const { data } = await evalApi.historyRun(runId)
    currentExperimentRun.value = data
    return data
  }

  async function evalSearch(data) {
    const { data: result } = await evalApi.search(data)
    metrics.value.search = result
    return result
  }

  async function evalDetection(data) {
    const { data: result } = await evalApi.detection(data)
    metrics.value.detection = result
    return result
  }

  async function evalEconomics(data) {
    const { data: result } = await evalApi.economics(data)
    metrics.value.economics = result
    return result
  }

  function setCompareSession(session) {
    compareSession.value = session
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(COMPARE_SESSION_STORAGE_KEY, JSON.stringify(session))
    }
  }

  function clearCompareSession() {
    compareSession.value = null
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(COMPARE_SESSION_STORAGE_KEY)
    }
  }

  return {
    health,
    loading,
    error,
    documents,
    currentDocument,
    searchResults,
    detectionResults,
    experimentResults,
    experimentHistory,
    experimentHistorySummary,
    currentExperimentRun,
    compareSession,
    metrics,
    isHealthy,
    fetchHealth,
    fetchDocuments,
    uploadDocument,
    getDocumentStatus,
    getDocumentContent,
    deleteDocument,
    retryExtract,
    retryIndex,
    search,
    detect,
    runExperiment,
    fetchExperimentHistory,
    fetchExperimentHistorySummary,
    fetchExperimentRun,
    evalSearch,
    evalDetection,
    evalEconomics,
    setCompareSession,
    clearCompareSession,
  }
})
