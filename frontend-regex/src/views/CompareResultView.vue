<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PdfPageViewer from '@/components/PdfPageViewer.vue'
import { compareApi, documentsApi } from '@/services/api'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const router = useRouter()

const session = computed(() => store.compareSession)
const result = computed(() => session.value?.result || null)
const leftDocument = computed(() => session.value?.leftDocument || null)
const rightDocument = computed(() => session.value?.rightDocument || null)
const leftDocumentId = computed(() => session.value?.leftDocumentId || '')
const rightDocumentId = computed(() => session.value?.rightDocumentId || '')
const sessionModel = computed(() => session.value?.model || 'openrouter/qwen/qwen3.5-9b:exacto')
const sessionIndexName = computed(() => session.value?.indexName || 'default')

const leftLayout = ref(session.value?.leftLayout || null)
const rightLayout = ref(session.value?.rightLayout || null)
const selectedChangeId = ref('')
const leftPage = ref(1)
const rightPage = ref(1)
const rerunLoading = ref(false)
const rerunError = ref('')
const rerunStrategy = ref('')
const debugOpen = ref(false)

const changes = computed(() => result.value?.changes || [])
const hasChanges = computed(() => changes.value.length > 0)
const selectedChange = computed(() =>
  changes.value.find((change) => change.change_id === selectedChangeId.value) || null
)
const summary = computed(() => result.value?.summary || {})
const strategyItems = [
  { title: 'Hybrid', value: 'hybrid' },
  { title: 'Semantic', value: 'semantic' },
  { title: 'Lexical', value: 'lexical' },
  { title: 'RG', value: 'rg' },
]

const leftHighlights = computed(() => buildHighlights(selectedChange.value?.left_evidence || [], leftPage.value, '#dc2626'))
const rightHighlights = computed(() => buildHighlights(selectedChange.value?.right_evidence || [], rightPage.value, '#0f766e'))

function buildHighlights(evidenceRows, pageNumber, color) {
  return evidenceRows
    .filter((row) => Number(row?.metadata?.page_number || 0) === Number(pageNumber))
    .map((row, index) => ({
      id: `${row.id}-${index}`,
      bbox_2d: row?.metadata?.bbox_2d,
      color,
      fill: color === '#dc2626' ? 'rgba(220, 38, 38, 0.18)' : 'rgba(15, 118, 110, 0.18)',
    }))
    .filter((row) => row.bbox_2d)
}

async function ensureLayout(documentId, side) {
  if (!documentId) return
  const current = side === 'left' ? leftLayout.value : rightLayout.value
  if (current?.num_pages) return
  try {
    const { data } = await documentsApi.getLayout(documentId)
    if (side === 'left') leftLayout.value = data
    else rightLayout.value = data
    if (session.value) {
      store.setCompareSession({
        ...session.value,
        leftLayout: side === 'left' ? data : leftLayout.value,
        rightLayout: side === 'right' ? data : rightLayout.value,
      })
    }
  } catch (e) {
    console.error('compare result layout load failed', e)
  }
}

onMounted(() => {
  ensureLayout(leftDocumentId.value, 'left')
  ensureLayout(rightDocumentId.value, 'right')
})

watch(result, (value) => {
  if (!value?.changes?.length) {
    selectedChangeId.value = ''
    return
  }
  selectedChangeId.value = value.changes[0].change_id
  rerunStrategy.value = session.value?.strategy || value?.strategy || 'hybrid'
}, { immediate: true })

watch(selectedChange, (change) => {
  if (!change) return
  leftPage.value = Number(change.left_page || 1)
  rightPage.value = Number(change.right_page || 1)
})

function backToSetup() {
  router.push({ name: 'compare' })
}

async function rerunAnalyze() {
  if (!leftDocumentId.value || !rightDocumentId.value) return
  rerunLoading.value = true
  rerunError.value = ''
  try {
    const { data } = await compareApi.analyze({
      left_document_id: leftDocumentId.value,
      right_document_id: rightDocumentId.value,
      model: sessionModel.value,
      index_name: sessionIndexName.value,
      strategy: rerunStrategy.value,
    })
    store.setCompareSession({ ...session.value, strategy: rerunStrategy.value, result: data })
  } catch (e) {
    rerunError.value = e.response?.data?.detail || e.message
  } finally {
    rerunLoading.value = false
  }
}
</script>

<template>
  <div v-if="!result" class="empty-root">
    <div class="empty-card">
      <v-icon size="56" color="primary" icon="mdi-file-compare" />
      <h2 class="mt-4 text-h6 font-weight-bold">Aucune comparaison active</h2>
      <p class="text-body-2 text-medium-emphasis mt-1 mb-5">Sélectionne deux documents sur la page de préparation.</p>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-arrow-left" @click="backToSetup">Retour</v-btn>
    </div>
  </div>

  <div v-else class="app-root">
    <header class="app-header">
      <div class="app-header__left">
        <v-btn icon="mdi-arrow-left" variant="text" density="compact" @click="backToSetup" />
        <span class="app-header__title">Changements détectés</span>
      </div>
      <div class="app-header__stats">
        <span class="pill" :class="hasChanges ? 'pill--danger' : 'pill--success'">{{ summary.change_count || 0 }} changements</span>
        <span class="pill pill--muted">{{ summary.latency_ms || 0 }} ms</span>
        <span class="pill pill--muted">{{ result.usage?.total_tokens || 0 }} tokens</span>
      </div>
      <div class="app-header__right">
        <v-select
          v-model="rerunStrategy"
          :items="strategyItems"
          density="compact"
          variant="outlined"
          hide-details
          class="strat-sel"
        />
        <v-btn
          color="primary"
          variant="flat"
          density="compact"
          prepend-icon="mdi-refresh"
          :loading="rerunLoading"
          @click="rerunAnalyze"
        >
          Relancer
        </v-btn>
      </div>
    </header>

    <v-alert v-if="rerunError" type="error" variant="tonal" density="compact" class="ma-3">
      {{ rerunError }}
    </v-alert>

    <div class="summary-strip">
      <div class="summary-strip__main">
        <div class="summary-strip__label">Synthèse</div>
        <div class="summary-strip__text">{{ result.llm_summary || 'Aucune synthèse disponible.' }}</div>
      </div>
      <div v-if="result.groups?.length" class="summary-strip__groups">
        <span v-for="group in result.groups" :key="group.key" class="group-chip">{{ group.key }} · {{ group.count }}</span>
      </div>
    </div>

    <div class="workspace">
      <aside class="change-rail">
        <div class="change-rail__head">
          <span>Changements</span>
          <span class="change-rail__count">{{ changes.length }}</span>
        </div>
        <div v-if="hasChanges" class="change-rail__scroll">
          <button
            v-for="change in changes"
            :key="change.change_id"
            type="button"
            class="change-card"
            :class="{ 'change-card--active': selectedChangeId === change.change_id }"
            @click="selectedChangeId = change.change_id"
          >
            <div class="change-card__top">
              <span class="change-card__title">{{ change.title }}</span>
              <span class="change-card__importance">{{ change.importance }}</span>
            </div>
            <div class="change-card__meta">
              <span>{{ change.change_type }}</span>
              <span>{{ change.change_subtype }}</span>
              <span v-if="change.left_page || change.right_page">p.{{ change.left_page || '?' }} / p.{{ change.right_page || '?' }}</span>
            </div>
            <div class="change-card__summary">{{ change.summary }}</div>
          </button>
        </div>
        <div v-else class="change-rail__empty">
          <v-icon size="22" icon="mdi-check-circle-outline" color="success" />
          <div class="change-rail__empty-title">Aucun changement significatif</div>
          <div class="change-rail__empty-copy">
            Les blocs alignés ne montrent pas de différence exploitable entre les deux documents.
          </div>
        </div>
      </aside>

      <div class="pdf-area">
        <div class="detail-bar" v-if="selectedChange">
          <div class="detail-bar__title">{{ selectedChange.title }}</div>
          <div class="detail-bar__summary">{{ selectedChange.summary }}</div>
        </div>
        <div v-else class="detail-bar detail-bar--empty">
          <div class="detail-bar__title">Documents alignés</div>
          <div class="detail-bar__summary">Aucun changement significatif détecté. Utilise “Relancer” avec une autre stratégie si tu veux tester un autre alignement.</div>
        </div>

        <div class="pdf-split">
          <div class="pdf-pane">
            <PdfPageViewer
              title="Document A"
              :document-id="leftDocumentId"
              :filename="leftDocument?.filename || ''"
              :page="leftPage"
              :total-pages="leftLayout?.num_pages || leftDocument?.total_pages || leftDocument?.num_pages || 0"
              :highlights="leftHighlights"
              :viewer-height="'calc(100vh - 360px)'"
              @update:page="leftPage = $event"
            />
          </div>
          <div class="pdf-pane">
            <PdfPageViewer
              title="Document B"
              :document-id="rightDocumentId"
              :filename="rightDocument?.filename || ''"
              :page="rightPage"
              :total-pages="rightLayout?.num_pages || rightDocument?.total_pages || rightDocument?.num_pages || 0"
              :highlights="rightHighlights"
              :viewer-height="'calc(100vh - 360px)'"
              @update:page="rightPage = $event"
            />
          </div>
        </div>

        <div class="detail-panel" v-if="selectedChange">
          <div class="detail-grid">
            <div class="detail-card">
              <div class="detail-card__label">Avant</div>
              <div class="detail-card__text">{{ selectedChange.left_raw || '—' }}</div>
            </div>
            <div class="detail-card">
              <div class="detail-card__label">Après</div>
              <div class="detail-card__text">{{ selectedChange.right_raw || '—' }}</div>
            </div>
          </div>

          <div v-if="selectedChange.lexical_diff_ops?.length" class="diff-inline">
            <span
              v-for="(op, index) in selectedChange.lexical_diff_ops"
              :key="`${selectedChange.change_id}-${index}`"
              class="diff-inline__op"
              :class="{
                'diff-inline__op--insert': op.op === 'insert',
                'diff-inline__op--delete': op.op === 'delete',
                'diff-inline__op--equal': op.op === 'equal',
              }"
            >{{ op.text }}</span>
          </div>

          <button type="button" class="debug-toggle" @click="debugOpen = !debugOpen">
            <v-icon size="15" :icon="debugOpen ? 'mdi-chevron-up' : 'mdi-chevron-down'" />
            Détails techniques
          </button>

          <div v-if="debugOpen" class="debug-grid">
            <div class="debug-item"><span>Alignment</span><strong>{{ selectedChange.alignment_source }}</strong></div>
            <div class="debug-item"><span>Confidence</span><strong>{{ selectedChange.alignment_confidence }}</strong></div>
            <div class="debug-item"><span>Field</span><strong>{{ selectedChange.field_type }}</strong></div>
            <div class="debug-item"><span>Reason</span><strong>{{ selectedChange.pairing_reason || 'n/a' }}</strong></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.empty-root {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
}

.empty-card {
  text-align: center;
  padding: 48px;
  border-radius: 20px;
  background: #fff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.06);
}

.app-root {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 64px - 48px);
  margin: -24px;
  background: #f8fafc;
}

.app-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  min-height: 52px;
  background: #0f172a;
  color: #e2e8f0;
}

.app-header__left,
.app-header__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-header__title {
  font-weight: 700;
  font-size: 0.95rem;
}

.app-header__stats {
  display: flex;
  gap: 8px;
  flex: 1;
  justify-content: center;
  flex-wrap: wrap;
}

.strat-sel {
  width: 130px;
}

.strat-sel :deep(.v-field) {
  background: rgba(255, 255, 255, 0.08) !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: #e2e8f0;
}

.pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
}

.pill--danger {
  background: rgba(239, 68, 68, 0.18);
  color: #fecaca;
}

.pill--muted {
  background: rgba(148, 163, 184, 0.12);
  color: #cbd5e1;
}

.pill--success {
  background: rgba(22, 163, 74, 0.18);
  color: #bbf7d0;
}

.summary-strip {
  display: grid;
  gap: 0.75rem;
  padding: 0.9rem 1rem;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
}

.summary-strip__label {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.summary-strip__text {
  margin-top: 0.25rem;
  font-size: 0.9rem;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.summary-strip__groups {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.group-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.75rem;
  font-weight: 600;
}

.workspace {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  flex: 1;
  min-height: 0;
}

.change-rail {
  background: #fff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.change-rail__head {
  padding: 14px 16px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #94a3b8;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.change-rail__count {
  background: #f1f5f9;
  color: #64748b;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
}

.change-rail__scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: grid;
  gap: 6px;
}

.change-rail__empty {
  display: grid;
  justify-items: start;
  gap: 0.4rem;
  padding: 1rem;
  color: #475569;
}

.change-rail__empty-title {
  font-size: 0.86rem;
  font-weight: 700;
  color: #0f172a;
}

.change-rail__empty-copy {
  font-size: 0.76rem;
  line-height: 1.5;
}

.change-card {
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.change-card:hover {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.change-card--active {
  background: #eff6ff;
  border-color: #93c5fd;
}

.change-card__top,
.change-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.change-card__title {
  font-size: 0.82rem;
  font-weight: 700;
  color: #1e293b;
}

.change-card__importance {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  color: #dc2626;
}

.change-card__meta {
  margin-top: 0.35rem;
  font-size: 0.7rem;
  color: #64748b;
  flex-wrap: wrap;
}

.change-card__summary {
  margin-top: 0.45rem;
  font-size: 0.74rem;
  line-height: 1.45;
  color: #475569;
}

.pdf-area {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.detail-bar {
  padding: 0.85rem 1rem;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
}

.detail-bar--empty {
  display: grid;
  gap: 0.35rem;
}

.detail-bar__title {
  font-size: 0.92rem;
  font-weight: 700;
  color: #0f172a;
}

.detail-bar__summary {
  margin-top: 0.3rem;
  font-size: 0.82rem;
  color: #64748b;
}

.pdf-split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
  padding: 1rem;
}

.pdf-pane {
  min-width: 0;
}

.detail-panel {
  padding: 0 1rem 1rem;
  display: grid;
  gap: 0.875rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.875rem;
}

.detail-card {
  padding: 0.95rem 1rem;
  border-radius: 0.9rem;
  border: 1px solid #e2e8f0;
  background: #fff;
}

.detail-card__label {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.detail-card__text {
  margin-top: 0.5rem;
  font-size: 0.86rem;
  line-height: 1.55;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
}

.diff-inline {
  padding: 0.9rem 1rem;
  border-radius: 0.9rem;
  border: 1px solid #e2e8f0;
  background: #fff;
  line-height: 1.8;
}

.diff-inline__op--insert {
  background: rgba(34, 197, 94, 0.15);
  color: #166534;
}

.diff-inline__op--delete {
  background: rgba(239, 68, 68, 0.15);
  color: #991b1b;
  text-decoration: line-through;
}

.debug-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  width: fit-content;
  border: none;
  background: none;
  color: #475569;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.debug-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
}

.debug-item {
  padding: 0.9rem 1rem;
  border-radius: 0.85rem;
  border: 1px solid #e2e8f0;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.debug-item span {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.debug-item strong {
  font-size: 0.85rem;
  color: #0f172a;
}

@media (max-width: 1100px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .pdf-split,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
