<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { compareApi } from '@/services/api'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const router = useRouter()

const leftDocumentId = ref('')
const rightDocumentId = ref('')
const selectedModel = ref('openrouter/qwen/qwen3.5-9b:exacto')
const strategy = ref('hybrid')
const indexName = ref('default')
const compareMode = ref('adaptive')
const loading = ref(false)
const error = ref('')
const historyLoading = ref(false)
const uploadInput = ref(null)
const uploadTarget = ref('left')
const compareRuns = ref([])

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
const compareReady = computed(() => Boolean(leftDocumentId.value && rightDocumentId.value))
const compareHistory = computed(() =>
  compareRuns.value.map((run) => ({
    ...run,
    leftFilename: completedDocs.value.find((doc) => (doc.document_id || doc.id) === run.left_document_id)?.filename || run.left_document_id,
    rightFilename: completedDocs.value.find((doc) => (doc.document_id || doc.id) === run.right_document_id)?.filename || run.right_document_id,
  }))
)

onMounted(async () => {
  await Promise.all([store.fetchDocuments(), loadCompareHistory()])
})

async function loadCompareHistory() {
  historyLoading.value = true
  try {
    const { data } = await compareApi.listRuns(12)
    compareRuns.value = data.runs || []
  } catch (e) {
    console.error('compare history load failed', e)
  } finally {
    historyLoading.value = false
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

async function analyze() {
  if (!compareReady.value) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await compareApi.createRun({
      left_document_id: leftDocumentId.value,
      right_document_id: rightDocumentId.value,
      model: selectedModel.value,
      index_name: indexName.value,
      strategy: strategy.value,
      compare_mode: compareMode.value,
    })
    store.setCompareSession({
      runId: data.run_id,
      status: data.status,
      leftDocument: leftDocument.value,
      rightDocument: rightDocument.value,
      leftDocumentId: leftDocumentId.value,
      rightDocumentId: rightDocumentId.value,
      model: selectedModel.value,
      indexName: indexName.value,
      strategy: strategy.value,
      compareMode: compareMode.value,
      result: data.result || null,
    })
    await loadCompareHistory()
    await router.push({ name: 'compare-result', params: { runId: data.run_id } })
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  } finally {
    loading.value = false
  }
}

function openRun(runId) {
  if (!runId) return
  router.push({ name: 'compare-result', params: { runId } })
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

    <section class="head">
      <div>
        <h1 class="head__title">Comparer deux documents</h1>
        <p class="head__subtitle">
          Ce mode détecte les changements entre deux documents. Pour vérifier un seul document avec des questions, utilise l’onglet <strong>Analyse LLM</strong>.
        </p>
      </div>
    </section>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>

    <div class="layout">
      <v-card class="surface-card">
        <v-card-title class="card-title-row">
          <div>
            <div class="card-title-text">Sources</div>
            <div class="card-subtitle-text">Choisis les deux documents à comparer.</div>
          </div>
        </v-card-title>
        <v-card-text class="card-body">
          <div class="doc-grid">
            <div class="doc-slot">
              <div class="doc-slot__head">
                <div>
                  <div class="doc-slot__title">Document A</div>
                  <div class="doc-slot__hint">Source gauche</div>
                </div>
                <v-btn color="secondary" variant="tonal" prepend-icon="mdi-upload" @click="triggerUpload('left')">
                  Upload
                </v-btn>
              </div>
              <v-select
                v-model="leftDocumentId"
                :items="documentItems"
                label="Choisir un document"
                variant="outlined"
                density="comfortable"
              />
              <div v-if="leftDocument" class="doc-chip">
                <v-icon size="16" icon="mdi-file-pdf-box" />
                <span>{{ leftDocument.filename }}</span>
              </div>
            </div>

            <div class="doc-slot">
              <div class="doc-slot__head">
                <div>
                  <div class="doc-slot__title">Document B</div>
                  <div class="doc-slot__hint">Source droite</div>
                </div>
                <v-btn color="secondary" variant="tonal" prepend-icon="mdi-upload" @click="triggerUpload('right')">
                  Upload
                </v-btn>
              </div>
              <v-select
                v-model="rightDocumentId"
                :items="documentItems"
                label="Choisir un document"
                variant="outlined"
                density="comfortable"
              />
              <div v-if="rightDocument" class="doc-chip">
                <v-icon size="16" icon="mdi-file-pdf-box" />
                <span>{{ rightDocument.filename }}</span>
              </div>
            </div>
          </div>
        </v-card-text>
      </v-card>

      <v-card class="surface-card">
        <v-card-title class="card-title-row">
          <div>
            <div class="card-title-text">Réglages</div>
            <div class="card-subtitle-text">Le compareur est diff-first. Le sémantique n’aide que l’alignement.</div>
          </div>
        </v-card-title>
        <v-card-text class="card-body">
          <div class="settings-grid">
            <v-select
              v-model="selectedModel"
              :items="[
                { title: 'Qwen 3.5 9B (exacto)', value: 'openrouter/qwen/qwen3.5-9b:exacto' },
                { title: 'Qwen 3.5 Flash', value: 'openrouter/qwen/qwen3.5-flash-02-23:exacto' },
              ]"
              item-title="title"
              item-value="value"
              label="Modèle de synthèse"
              variant="outlined"
              density="comfortable"
            />
            <v-select
              v-model="compareMode"
              :items="[
                { title: 'Adaptive', value: 'adaptive' },
                { title: 'Compare standard', value: 'standard' },
                { title: 'Full lexical diff', value: 'full_lexical' },
              ]"
              item-title="title"
              item-value="value"
              label="Mode de comparaison"
              variant="outlined"
              density="comfortable"
            />
            <v-select v-model="strategy" :items="['hybrid', 'semantic', 'lexical', 'rg']" label="Stratégie" variant="outlined" density="comfortable" />
            <v-select v-model="indexName" :items="['default', 'evidence', 'documents']" label="Index" variant="outlined" density="comfortable" />
          </div>
        </v-card-text>
      </v-card>

      <v-card class="surface-card launch-card">
        <v-card-text class="launch-card__body">
          <div class="launch-copy">
            <strong>Analyse automatique</strong>
            <span>
              {{
                compareMode === 'full_lexical'
                  ? 'Le système remonte une liste beaucoup plus large de différences, y compris les micro-changements.'
                  : compareMode === 'adaptive'
                    ? 'Le système produit un résultat rapide puis raffine lexicalement les zones suspectes sans fouiller tout le document.'
                  : 'Le système aligne les blocs, calcule les diffs locaux, puis résume les changements importants.'
              }}
            </span>
          </div>
          <v-btn
            color="primary"
            size="large"
            prepend-icon="mdi-file-compare"
            :loading="loading"
            :disabled="!compareReady"
            @click="analyze"
          >
            Lancer la comparaison
          </v-btn>
        </v-card-text>
      </v-card>

      <v-card class="surface-card">
        <v-card-title class="card-title-row">
          <div>
            <div class="card-title-text">Historique des comparaisons</div>
            <div class="card-subtitle-text">Rouvre un run existant sans relancer toute l’analyse.</div>
          </div>
          <v-btn variant="text" prepend-icon="mdi-refresh" size="small" :loading="historyLoading" @click="loadCompareHistory">
            Actualiser
          </v-btn>
        </v-card-title>
        <v-card-text class="card-body">
          <div v-if="compareHistory.length === 0" class="history-empty">
            Aucun run compare enregistré pour l’instant.
          </div>
          <div v-else class="history-list">
            <button
              v-for="run in compareHistory"
              :key="run.run_id"
              type="button"
              class="history-row"
              @click="openRun(run.run_id)"
            >
              <div class="history-row__main">
                <div class="history-row__files">
                  <span class="history-row__file">{{ run.leftFilename }}</span>
                  <span class="history-row__arrow">→</span>
                  <span class="history-row__file">{{ run.rightFilename }}</span>
                </div>
                <div class="history-row__meta">
                  <span>{{ new Date(run.created_at).toLocaleString() }}</span>
                  <span>{{ run.strategy }}</span>
                  <span>{{ run.status }}</span>
                </div>
              </div>
              <v-icon icon="mdi-open-in-new" size="18" />
            </button>
          </div>
        </v-card-text>
      </v-card>
    </div>
  </div>
</template>

<style scoped>
.compare-page {
  min-height: 100%;
  padding-bottom: 2rem;
}

.head {
  margin-bottom: 1rem;
}

.head__title {
  font-size: clamp(1.25rem, 1.5vw, 1.6rem);
  line-height: 1.1;
  letter-spacing: -0.02em;
  color: #0f172a;
}

.head__subtitle {
  margin-top: 0.5rem;
  max-width: 68ch;
  font-size: 0.9rem;
  line-height: 1.55;
  color: #475569;
}

.layout {
  display: grid;
  gap: 1rem;
}

.surface-card {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 1rem;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
}

.card-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.card-title-text {
  font-size: 1rem;
  font-weight: 700;
  color: #0f172a;
}

.card-subtitle-text {
  margin-top: 0.25rem;
  font-size: 0.82rem;
  line-height: 1.45;
  color: #64748b;
}

.card-body {
  display: grid;
  gap: 1rem;
}

.doc-grid,
.settings-grid {
  display: grid;
  gap: 0.875rem;
}

.doc-slot {
  padding: 1rem;
  border-radius: 0.9rem;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.doc-slot__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.875rem;
}

.doc-slot__title {
  font-size: 0.92rem;
  font-weight: 700;
  color: #0f172a;
}

.doc-slot__hint {
  margin-top: 0.2rem;
  font-size: 0.78rem;
  color: #64748b;
}

.doc-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding: 0.45rem 0.75rem;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: rgb(30, 64, 175);
  font-size: 0.78rem;
  font-weight: 600;
}

.launch-card__body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.launch-copy {
  display: grid;
  gap: 0.35rem;
  font-size: 0.86rem;
  color: #475569;
}

.history-empty {
  padding: 0.75rem 0;
  font-size: 0.88rem;
  color: #64748b;
}

.history-list {
  display: grid;
  gap: 0.75rem;
}

.history-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  width: 100%;
  padding: 0.9rem 1rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 0.9rem;
  background: #fff;
  text-align: left;
}

.history-row__main {
  min-width: 0;
  display: grid;
  gap: 0.3rem;
}

.history-row__files {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
}

.history-row__file {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.85rem;
  font-weight: 600;
  color: #0f172a;
}

.history-row__arrow {
  color: #94a3b8;
}

.history-row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  font-size: 0.76rem;
  color: #64748b;
}

@media (min-width: 768px) {
  .doc-grid,
  .settings-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .launch-card__body {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

@media (max-width: 767px) {
  .card-title-row,
  .doc-slot__head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
