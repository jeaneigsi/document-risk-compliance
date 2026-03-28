<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { compareApi, documentsApi } from '@/services/api'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const router = useRouter()

const leftDocumentId = ref('')
const rightDocumentId = ref('')
const selectedModel = ref('openrouter/qwen/qwen3.5-9b:exacto')
const strategy = ref('hybrid')
const indexName = ref('default')
const topK = ref(5)
const autoDiff = ref(true)
const claims = ref([])
const suggestions = ref([])
const compareResult = ref(null)
const loading = ref(false)
const loadingSuggestions = ref(false)
const error = ref('')
const uploadInput = ref(null)
const uploadTarget = ref('left')
const leftLayout = ref(null)
const rightLayout = ref(null)

const completedDocs = computed(() => (store.documents || []).filter((doc) => doc.status === 'completed'))
const documentItems = computed(() =>
  completedDocs.value.map((doc) => ({
    title: doc.filename,
    value: doc.document_id || doc.id,
  }))
)

const leftDocument = computed(() =>
  completedDocs.value.find((doc) => (doc.document_id || doc.id) === leftDocumentId.value)
)
const rightDocument = computed(() =>
  completedDocs.value.find((doc) => (doc.document_id || doc.id) === rightDocumentId.value)
)

const summaryChips = computed(() => {
  const summary = compareResult.value?.summary || {}
  return [
    { label: 'Critical / inconsistent', value: summary.inconsistent_count || 0, color: 'error' },
    { label: 'Insufficient evidence', value: summary.insufficient_evidence_count || 0, color: 'warning' },
    { label: 'Latency ms', value: summary.latency_ms || 0, color: 'info' },
    { label: 'Total tokens', value: compareResult.value?.usage?.total_tokens || 0, color: 'primary' },
  ]
})

onMounted(async () => {
  await store.fetchDocuments()
})

watch(leftDocumentId, async (value) => {
  leftLayout.value = value ? await fetchLayout(value) : null
  suggestions.value = []
  compareResult.value = null
})

watch(rightDocumentId, async (value) => {
  rightLayout.value = value ? await fetchLayout(value) : null
  suggestions.value = []
  compareResult.value = null
})

async function fetchLayout(documentId) {
  try {
    const { data } = await documentsApi.getLayout(documentId)
    return data
  } catch (e) {
    console.error('layout load failed', e)
    return null
  }
}

function triggerUpload(target) {
  uploadTarget.value = target
  uploadInput.value?.click()
}

async function onUploadSelected(event) {
  const file = event.target?.files?.[0]
  if (!file) return
  try {
    error.value = ''
    const result = await store.uploadDocument(file)
    await pollUntilCompleted(result.document_id)
    await store.fetchDocuments()
    if (uploadTarget.value === 'left') leftDocumentId.value = result.document_id
    if (uploadTarget.value === 'right') rightDocumentId.value = result.document_id
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  } finally {
    if (event.target) event.target.value = ''
  }
}

async function pollUntilCompleted(documentId) {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const status = await store.getDocumentStatus(documentId)
    if (status.status === 'completed') return
    if (status.status === 'failed') {
      throw new Error(status.error || 'Document processing failed')
    }
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
  throw new Error('Timed out waiting for document processing')
}

async function loadSuggestions() {
  if (!leftDocumentId.value || !rightDocumentId.value) return
  loadingSuggestions.value = true
  error.value = ''
  try {
    const { data } = await compareApi.suggestClaims({
      left_document_id: leftDocumentId.value,
      right_document_id: rightDocumentId.value,
      limit: 8,
    })
    suggestions.value = data.suggestions || []
    if (!claims.value.length) {
      claims.value = suggestions.value.slice(0, 4).map((item) => item.claim)
    }
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  } finally {
    loadingSuggestions.value = false
  }
}

function addSuggestion(claim) {
  if (!claims.value.includes(claim)) claims.value.push(claim)
}

function addClaim() {
  claims.value.push('')
}

function removeClaim(index) {
  claims.value.splice(index, 1)
}

async function analyze() {
  if (!leftDocumentId.value || !rightDocumentId.value) return
  loading.value = true
  error.value = ''
  compareResult.value = null
  try {
    const { data } = await compareApi.analyze({
      left_document_id: leftDocumentId.value,
      right_document_id: rightDocumentId.value,
      claims: claims.value.filter((item) => item && item.trim()),
      auto_diff: autoDiff.value,
      model: selectedModel.value,
      index_name: indexName.value,
      strategy: strategy.value,
      top_k: topK.value,
    })
    compareResult.value = data
    store.setCompareSession({
      leftDocument: leftDocument.value,
      rightDocument: rightDocument.value,
      leftLayout: leftLayout.value,
      rightLayout: rightLayout.value,
      leftDocumentId: leftDocumentId.value,
      rightDocumentId: rightDocumentId.value,
      claims: claims.value.filter((item) => item && item.trim()),
      autoDiff: autoDiff.value,
      model: selectedModel.value,
      indexName: indexName.value,
      strategy: strategy.value,
      topK: topK.value,
      result: data,
    })
    await router.push({ name: 'compare-result' })
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="compare-page">
    <input
      ref="uploadInput"
      type="file"
      accept=".pdf,.jpg,.jpeg,.png"
      class="d-none"
      @change="onUploadSelected"
    />

    <v-row class="mb-6">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-file-compare" class="mr-2" />
          Compare 2 Documents
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Prépare la comparaison ici. Une fois l’analyse terminée, la zone comparative s’ouvre dans une page dédiée.
        </p>
      </v-col>
    </v-row>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>

    <v-row class="mb-4">
      <v-col cols="12" md="6">
        <v-card class="selection-card">
          <v-card-title class="d-flex align-center">
            <span>Document gauche</span>
            <v-spacer />
            <v-btn color="secondary" variant="tonal" prepend-icon="mdi-upload" @click="triggerUpload('left')">
              Upload live
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-select
              v-model="leftDocumentId"
              :items="documentItems"
              label="Choisir un document"
              variant="outlined"
            />
            <v-chip v-if="leftDocument" size="small" color="info" class="mt-2">
              {{ leftDocument.filename }} · {{ leftDocument.total_pages || leftDocument.num_pages || '?' }} pages
            </v-chip>
          </v-card-text>
        </v-card>
      </v-col>
      <v-col cols="12" md="6">
        <v-card class="selection-card">
          <v-card-title class="d-flex align-center">
            <span>Document droit</span>
            <v-spacer />
            <v-btn color="secondary" variant="tonal" prepend-icon="mdi-upload" @click="triggerUpload('right')">
              Upload live
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-select
              v-model="rightDocumentId"
              :items="documentItems"
              label="Choisir un document"
              variant="outlined"
            />
            <v-chip v-if="rightDocument" size="small" color="info" class="mt-2">
              {{ rightDocument.filename }} · {{ rightDocument.total_pages || rightDocument.num_pages || '?' }} pages
            </v-chip>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="5">
        <v-card class="control-card">
          <v-card-title class="d-flex align-center">
            <span>Claims & pilotage</span>
            <v-spacer />
            <v-switch v-model="autoDiff" inset color="primary" label="Auto-diff" hide-details />
          </v-card-title>
          <v-card-text>
            <div class="d-flex flex-wrap ga-2 mb-4">
              <v-btn
                variant="tonal"
                prepend-icon="mdi-lightbulb-on-outline"
                :disabled="!leftDocumentId || !rightDocumentId"
                :loading="loadingSuggestions"
                @click="loadSuggestions"
              >
                Suggérer des claims
              </v-btn>
              <v-btn color="primary" prepend-icon="mdi-robot" :loading="loading" :disabled="!leftDocumentId || !rightDocumentId" @click="analyze">
                Lancer l'analyse compare
              </v-btn>
            </div>

            <v-text-field
              v-for="(claim, index) in claims"
              :key="`claim-${index}`"
              v-model="claims[index]"
              :label="`Claim ${index + 1}`"
              variant="outlined"
              density="comfortable"
              class="mb-2"
            >
              <template #append-inner>
                <v-btn icon="mdi-close" variant="text" size="small" @click="removeClaim(index)" />
              </template>
            </v-text-field>

            <v-btn variant="text" prepend-icon="mdi-plus" @click="addClaim">Ajouter un claim</v-btn>

            <v-divider class="my-4" />

            <v-select v-model="selectedModel" :items="[
              { title: 'Qwen 3.5 9B (exacto)', value: 'openrouter/qwen/qwen3.5-9b:exacto' },
              { title: 'Qwen 3.5 Flash', value: 'openrouter/qwen/qwen3.5-flash-02-23:exacto' },
            ]" item-title="title" item-value="value" label="Modèle" variant="outlined" />
            <v-select v-model="strategy" :items="['hybrid', 'semantic', 'lexical', 'rg']" label="Stratégie" variant="outlined" />
            <v-select v-model="indexName" :items="['default', 'evidence', 'documents']" label="Index" variant="outlined" />
            <v-select v-model="topK" :items="[3, 5, 8]" label="Top K par document" variant="outlined" />
          </v-card-text>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>Suggestions</v-card-title>
          <v-card-text>
            <v-alert v-if="!suggestions.length" type="info" variant="tonal">
              Lance d’abord “Suggérer des claims” pour préremplir des écarts métier.
            </v-alert>
            <v-list v-else density="compact">
              <v-list-item v-for="item in suggestions" :key="item.claim">
                <v-list-item-title class="text-body-2">{{ item.claim }}</v-list-item-title>
                <v-list-item-subtitle>{{ item.left_value }} vs {{ item.right_value }}</v-list-item-subtitle>
                <template #append>
                  <v-btn size="small" variant="tonal" @click="addSuggestion(item.claim)">Ajouter</v-btn>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="7">
        <v-card class="summary-card">
          <v-card-title>Préparation de la vue comparative</v-card-title>
          <v-card-text>
            <v-alert v-if="!compareResult && !loading" type="info" variant="tonal">
              La page dédiée des résultats s’ouvrira automatiquement une fois l’analyse terminée.
            </v-alert>
            <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />
            <div class="d-flex flex-wrap ga-3 mb-4">
              <v-chip
                v-for="chip in summaryChips"
                :key="chip.label"
                :color="chip.color"
                size="large"
                variant="elevated"
              >
                {{ chip.label }}: {{ chip.value }}
              </v-chip>
            </div>
            <div v-if="compareResult" class="issue-grid">
              <div
                v-for="issue in compareResult.issues"
                :key="issue.issue_id"
                class="issue-tile"
              >
                <div class="d-flex align-center justify-space-between mb-2">
                  <strong>{{ issue.severity }}</strong>
                  <v-chip :color="issue.verdict === 'inconsistent' ? 'error' : issue.verdict === 'consistent' ? 'success' : 'warning'" size="small">
                    {{ issue.verdict }}
                  </v-chip>
                </div>
                <div class="text-body-2 font-weight-medium">{{ issue.claim }}</div>
                <div class="text-caption text-medium-emphasis mt-2">{{ issue.summary }}</div>
              </div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.compare-page {
  min-height: 100%;
}

.selection-card,
.control-card,
.summary-card {
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.08);
}

.issue-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.issue-tile {
  text-align: left;
  padding: 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: linear-gradient(180deg, #fff, #f8fafc);
}
</style>
