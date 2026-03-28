<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { llmApi } from '@/services/api'
import { useAppStore } from '@/stores/app'

const store = useAppStore()

const selectedModel = ref('openrouter/qwen/qwen3.5-9b:exacto')
const selectedDocumentId = ref('')
const claim = ref('')
const indexName = ref('default')
const strategy = ref('hybrid')
const topK = ref(5)

const loading = ref(false)
const result = ref(null)
const error = ref(null)
const history = ref([])
const uploadInput = ref(null)
const uploading = ref(false)
const uploadFileName = ref('')
const uploadStatus = ref('')
const uploadProgress = ref(0)
const uploadDocumentId = ref('')
let statusPollTimer = null

const models = [
  { title: 'Qwen 3.5 9B (exacto)', value: 'openrouter/qwen/qwen3.5-9b:exacto' },
  { title: 'Qwen 3.5 Flash 02-23', value: 'openrouter/qwen/qwen3.5-flash-02-23:exacto' },
]

const completedDocs = computed(() =>
  (store.documents || []).filter((d) => d.status === 'completed')
)

const hasCompletedDocs = computed(() => completedDocs.value.length > 0)

const docItems = computed(() =>
  completedDocs.value.map((d) => ({
    title: d.filename,
    value: d.document_id || d.id,
  }))
)

const selectedDoc = computed(() =>
  completedDocs.value.find((d) => (d.document_id || d.id) === selectedDocumentId.value)
)

const canAnalyze = computed(() =>
  Boolean(selectedDocumentId.value && claim.value.trim() && !loading.value)
)

const parsedContent = computed(() => {
  if (!result.value?.content) return null
  return tryParseJson(result.value.content)
})

const parsedVerdict = computed(() => parsedContent.value?.verdict || null)
const parsedConfidence = computed(() => parsedContent.value?.confidence ?? null)
const promptTokens = computed(() => Number(result.value?.usage?.prompt_tokens || 0))
const completionTokens = computed(() => Number(result.value?.usage?.completion_tokens || 0))
const totalTokens = computed(() => {
  const explicitTotal = Number(result.value?.usage?.total_tokens || 0)
  if (explicitTotal > 0) return explicitTotal
  return promptTokens.value + completionTokens.value
})

onMounted(async () => {
  await store.fetchDocuments()
  if (!selectedDocumentId.value && docItems.value.length > 0) {
    selectedDocumentId.value = docItems.value[0].value
  }
})

onBeforeUnmount(() => {
  if (statusPollTimer) clearInterval(statusPollTimer)
})

function openUploadDialog() {
  uploadInput.value?.click()
}

async function onUploadSelected(event) {
  const file = event.target?.files?.[0]
  if (!file) return

  uploading.value = true
  uploadFileName.value = file.name
  uploadStatus.value = 'uploading'
  uploadProgress.value = 0.05
  error.value = null

  try {
    const response = await store.uploadDocument(file)
    uploadDocumentId.value = response.document_id
    selectedDocumentId.value = response.document_id
    uploadStatus.value = 'pending'
    uploadProgress.value = 0.15
    startPollingUploadStatus(response.document_id)
  } catch (e) {
    uploading.value = false
    uploadStatus.value = 'failed'
    error.value = e.response?.data?.detail || e.message
  } finally {
    if (event.target) event.target.value = ''
  }
}

function startPollingUploadStatus(documentId) {
  if (statusPollTimer) clearInterval(statusPollTimer)

  statusPollTimer = setInterval(async () => {
    try {
      const status = await store.getDocumentStatus(documentId)
      uploadStatus.value = status.status
      uploadProgress.value = Math.max(uploadProgress.value, Number(status.progress || 0))

      if (status.status === 'completed') {
        clearInterval(statusPollTimer)
        statusPollTimer = null
        uploading.value = false
        uploadProgress.value = 1
        await store.fetchDocuments()
        selectedDocumentId.value = documentId
      }

      if (status.status === 'failed') {
        clearInterval(statusPollTimer)
        statusPollTimer = null
        uploading.value = false
        uploadProgress.value = 1
        error.value = status.error || 'Extraction failed'
        await store.fetchDocuments()
      }
    } catch (e) {
      clearInterval(statusPollTimer)
      statusPollTimer = null
      uploading.value = false
      uploadStatus.value = 'failed'
      error.value = e.response?.data?.detail || e.message
    }
  }, 2000)
}

async function retryUploadExtraction() {
  if (!uploadDocumentId.value) return
  uploading.value = true
  uploadStatus.value = 'pending'
  uploadProgress.value = 0.2
  error.value = null
  await store.retryExtract(uploadDocumentId.value)
  startPollingUploadStatus(uploadDocumentId.value)
}

async function analyzeDocument() {
  if (!selectedDocumentId.value || !claim.value.trim()) return

  loading.value = true
  error.value = null
  result.value = null

  try {
    const payload = {
      document_id: selectedDocumentId.value,
      claim: claim.value,
      model: selectedModel.value || undefined,
      index_name: indexName.value,
      strategy: strategy.value,
      top_k: topK.value,
    }
    const { data } = await llmApi.analyzeDocument(payload)
    result.value = data
    history.value.unshift({
      timestamp: new Date(),
      document_id: selectedDocumentId.value,
      claim: claim.value,
      success: true,
    })
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
    history.value.unshift({
      timestamp: new Date(),
      document_id: selectedDocumentId.value,
      claim: claim.value,
      success: false,
      error: error.value,
    })
  } finally {
    loading.value = false
  }
}

function tryParseJson(str) {
  try {
    return JSON.parse(str)
  } catch {
    return null
  }
}
</script>

<template>
  <div>
    <input
      ref="uploadInput"
      type="file"
      accept=".pdf,.jpg,.jpeg,.png"
      style="display: none"
      @change="onUploadSelected"
    />

    <v-row class="mb-6">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-robot" class="mr-2" />
          Analyse LLM sur Document
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Workflow: 1) choisir un document extrait 2) soumettre un claim 3) analyser le verdict à partir des evidence récupérées.
        </p>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="5">
        <v-card class="mb-4">
          <v-card-title class="d-flex align-center">
            <span>Nouveau document</span>
            <v-spacer />
            <v-btn
              color="secondary"
              prepend-icon="mdi-upload"
              :loading="uploading && uploadStatus === 'uploading'"
              @click="openUploadDialog"
            >
              Ajouter un document
            </v-btn>
          </v-card-title>
          <v-card-text>
            <div v-if="uploadFileName" class="text-body-2 mb-2">
              Fichier: {{ uploadFileName }}
            </div>
            <v-progress-linear
              v-if="uploading || uploadStatus === 'completed' || uploadStatus === 'failed'"
              :model-value="Math.round(uploadProgress * 100)"
              color="primary"
              height="8"
              rounded
              class="mb-2"
            />
            <v-chip
              v-if="uploadStatus"
              :color="uploadStatus === 'completed' ? 'success' : (uploadStatus === 'failed' ? 'error' : 'info')"
              size="small"
            >
              pipeline: {{ uploadStatus }}
            </v-chip>
            <v-btn
              v-if="uploadStatus === 'failed'"
              class="ml-2"
              size="small"
              variant="outlined"
              @click="retryUploadExtraction"
            >
              Relancer extraction
            </v-btn>
          </v-card-text>
        </v-card>

        <v-alert v-if="!hasCompletedDocs" type="warning" variant="tonal" class="mb-4">
          Aucun document au statut completed. Chargez un document et attendez la fin de l'extraction avant d'analyser.
        </v-alert>

        <v-card>
          <v-card-title>Contexte d'analyse</v-card-title>
          <v-card-text>
            <v-select
              v-model="selectedDocumentId"
              :items="docItems"
              label="Document (status=completed)"
              variant="outlined"
            />

            <v-textarea
              v-model="claim"
              label="Claim à vérifier"
              variant="outlined"
              rows="4"
              placeholder="Ex: Le contrat indique un budget de 1200 EUR."
            />

            <v-select
              v-model="selectedModel"
              :items="models"
              label="Modèle"
              variant="outlined"
            />

            <v-select
              v-model="strategy"
              :items="['hybrid', 'semantic', 'lexical', 'rg']"
              label="Stratégie retrieval"
              variant="outlined"
            />

            <v-select
              v-model="indexName"
              :items="['default', 'evidence', 'documents']"
              label="Index"
              variant="outlined"
            />

            <v-select
              v-model="topK"
              :items="[3, 5, 10]"
              label="Top K"
              variant="outlined"
            />

            <v-btn
              color="primary"
              block
              :loading="loading"
              :disabled="!canAnalyze"
              @click="analyzeDocument"
            >
              Analyser avec contexte documentaire
            </v-btn>
            <v-alert
              v-if="selectedDoc"
              type="info"
              variant="tonal"
              class="mt-4"
            >
              Document sélectionné: <strong>{{ selectedDoc.filename }}</strong>
            </v-alert>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="7">
        <v-card>
          <v-card-title>Résultat</v-card-title>
          <v-card-text>
            <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
            <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />

            <v-alert v-if="!result && !loading && !error" type="info" variant="tonal">
              Sélectionnez un document et une claim pour lancer l'analyse.
            </v-alert>

            <div v-if="result">
              <v-alert
                v-if="parsedVerdict"
                :type="parsedVerdict === 'inconsistent' ? 'error' : (parsedVerdict === 'consistent' ? 'success' : 'warning')"
                variant="tonal"
                class="mb-3"
              >
                Verdict: <strong>{{ parsedVerdict }}</strong>
                <span v-if="parsedConfidence !== null"> · confidence={{ parsedConfidence }}</span>
              </v-alert>

              <v-list density="compact" class="mb-3">
                <v-list-item>
                  <v-list-item-title>Document</v-list-item-title>
                  <template #append><v-chip size="small">{{ result.document_id }}</v-chip></template>
                </v-list-item>
                <v-list-item>
                  <v-list-item-title>Evidence récupérée</v-list-item-title>
                  <template #append><v-chip size="small">{{ result.evidence_count || 0 }}</v-chip></template>
                </v-list-item>
                <v-list-item>
                  <v-list-item-title>Retrieval</v-list-item-title>
                  <template #append>
                    <v-chip size="small" class="mr-2">{{ result.strategy }}</v-chip>
                    <v-chip size="small">{{ result.index_name }}</v-chip>
                  </template>
                </v-list-item>
                <v-list-item>
                  <v-list-item-title>Prompt tokens</v-list-item-title>
                  <template #append>
                    <v-chip size="small">{{ promptTokens }}</v-chip>
                  </template>
                </v-list-item>
                <v-list-item>
                  <v-list-item-title>Completion tokens</v-list-item-title>
                  <template #append>
                    <v-chip size="small">{{ completionTokens }}</v-chip>
                  </template>
                </v-list-item>
                <v-list-item>
                  <v-list-item-title>Total tokens</v-list-item-title>
                  <template #append>
                    <v-chip size="small" color="primary">{{ totalTokens }}</v-chip>
                  </template>
                </v-list-item>
              </v-list>

              <v-divider class="mb-3" />

              <h4 class="text-h6 mb-2">Réponse LLM</h4>
              <pre class="text-body-2 whitespace-pre-wrap mb-4">{{ result.content }}</pre>

              <h4 class="text-h6 mb-2">Evidence utilisée</h4>
              <v-table density="compact">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Score</th>
                    <th>Texte</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="ev in result.evidence || []" :key="ev.id">
                    <td>{{ ev.id }}</td>
                    <td>{{ (ev.score || 0).toFixed(3) }}</td>
                    <td class="truncate-cell">{{ ev.text || '(no_text)' }}</td>
                  </tr>
                </tbody>
              </v-table>

              <h4 class="text-h6 mt-4 mb-2">JSON</h4>
              <pre class="text-body-2">{{ JSON.stringify(parsedContent || result, null, 2) }}</pre>
            </div>
          </v-card-text>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>Historique</v-card-title>
          <v-card-text style="max-height: 240px; overflow-y: auto;">
            <v-list density="compact">
              <v-list-item v-for="(h, i) in history.slice(0, 20)" :key="i">
                <template #prepend>
                  <v-icon :icon="h.success ? 'mdi-check-circle' : 'mdi-close-circle'" :color="h.success ? 'success' : 'error'" size="small" />
                </template>
                <v-list-item-title class="text-body-2">
                  {{ h.claim.substring(0, 70) }}{{ h.claim.length > 70 ? '...' : '' }}
                </v-list-item-title>
                <v-list-item-subtitle>
                  doc={{ h.document_id }} · {{ h.timestamp.toLocaleTimeString() }}
                </v-list-item-subtitle>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.whitespace-pre-wrap {
  white-space: pre-wrap;
  word-break: break-word;
}

.truncate-cell {
  max-width: 520px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
