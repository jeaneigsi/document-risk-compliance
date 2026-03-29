<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { compareApi, documentsApi } from '@/services/api'
import { useAppStore } from '@/stores/app'

const PdfPageViewer = defineAsyncComponent(() => import('@/components/PdfPageViewer.vue'))

const store = useAppStore()
const route = useRoute()
const router = useRouter()

const session = computed(() => store.compareSession)
const runId = computed(() => String(route.params.runId || session.value?.runId || ''))
const run = ref(session.value?.runId === runId.value ? session.value : null)

const result = computed(() => run.value?.result || null)
const leftDocument = computed(() => session.value?.leftDocument || null)
const rightDocument = computed(() => session.value?.rightDocument || null)
const leftDocumentId = computed(() => run.value?.left_document_id || session.value?.leftDocumentId || '')
const rightDocumentId = computed(() => run.value?.right_document_id || session.value?.rightDocumentId || '')
const sessionModel = computed(() => run.value?.model || session.value?.model || 'openrouter/qwen/qwen3.5-9b:exacto')
const sessionIndexName = computed(() => run.value?.index_name || session.value?.indexName || 'default')
const compareMode = computed(() => result.value?.compare_mode || run.value?.config?.compare_mode || session.value?.compareMode || 'standard')
const canResumeFromSession = computed(() => Boolean(session.value?.leftDocumentId && session.value?.rightDocumentId))

const leftLayout = ref(session.value?.leftLayout || null)
const rightLayout = ref(session.value?.rightLayout || null)
const selectedChangeId = ref('')
const leftPage = ref(1)
const rightPage = ref(1)
const runLoading = ref(false)
const runError = ref('')
const rerunLoading = ref(false)
const rerunError = ref('')
const rerunStrategy = ref('')
const debugOpen = ref(false)

let pollHandle = null

const changes = computed(() => result.value?.changes || [])
const hasChanges = computed(() => changes.value.length > 0)
const selectedChange = computed(() =>
  changes.value.find((change) => change.change_id === selectedChangeId.value) || null
)
const summary = computed(() => result.value?.summary || {})
const runStatus = computed(() => run.value?.status || '')
const showPendingState = computed(() => ['queued', 'running'].includes(runStatus.value))
const summaryText = computed(() => String(result.value?.llm_summary || '').trim())
const summaryItems = computed(() => {
  if (!summaryText.value) return []
  return summaryText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^[-*•]\s*/, ''))
})
const summaryLooksLikeList = computed(() =>
  summaryItems.value.length > 1 || /^[-*•]\s/.test(summaryText.value)
)
const importantChangeTokens = computed(() => {
  const tokens = new Set()
  for (const change of changes.value) {
    if (!['high', 'critical'].includes(String(change.importance || '').toLowerCase())) continue
    const title = String(change.title || '').toLowerCase()
    const subtype = String(change.change_subtype || '').toLowerCase()
    const fieldType = String(change.field_type || '').toLowerCase()
    for (const token of [title, subtype, fieldType]) {
      if (token) tokens.add(token)
    }
  }
  return tokens
})
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

function isImportantSummaryItem(item, index) {
  const normalized = String(item || '').toLowerCase()
  for (const token of importantChangeTokens.value) {
    if (token && normalized.includes(token)) return true
  }
  return index === 0 && changes.value.some((change) => ['high', 'critical'].includes(String(change.importance || '').toLowerCase()))
}

function syncSession(partial) {
  store.setCompareSession({
    ...(session.value || {}),
    ...partial,
  })
}

async function ensureLayout(documentId, side) {
  if (!documentId) return
  const current = side === 'left' ? leftLayout.value : rightLayout.value
  if (current?.num_pages) return
  try {
    const { data } = await documentsApi.getLayout(documentId)
    if (side === 'left') leftLayout.value = data
    else rightLayout.value = data
    syncSession({
      leftLayout: side === 'left' ? data : leftLayout.value,
      rightLayout: side === 'right' ? data : rightLayout.value,
    })
  } catch (e) {
    console.error('compare result layout load failed', e)
  }
}

function clearPoll() {
  if (pollHandle) {
    window.clearTimeout(pollHandle)
    pollHandle = null
  }
}

function schedulePoll() {
  clearPoll()
  if (!showPendingState.value || !runId.value) return
  pollHandle = window.setTimeout(() => {
    void loadRun({ silent: true })
  }, 1500)
}

async function loadRun({ silent = false } = {}) {
  if (!runId.value) return
  if (!silent) {
    runLoading.value = true
    runError.value = ''
  }
  try {
    const { data } = await compareApi.getRun(runId.value)
    run.value = data
    syncSession({
      runId: data.run_id,
      status: data.status,
      leftDocumentId: data.left_document_id,
      rightDocumentId: data.right_document_id,
      model: data.model || sessionModel.value,
      indexName: data.index_name,
      strategy: data.strategy,
      compareMode: data.result?.compare_mode || data.config?.compare_mode || session.value?.compareMode || 'standard',
      result: data.result || null,
      error: data.error || '',
      leftLayout: leftLayout.value,
      rightLayout: rightLayout.value,
    })
    if (data.error) runError.value = data.error
    if (data.result) {
      await Promise.all([
        ensureLayout(data.left_document_id, 'left'),
        ensureLayout(data.right_document_id, 'right'),
      ])
    }
  } catch (e) {
    runError.value = e.response?.data?.detail || e.message
  } finally {
    if (!silent) runLoading.value = false
    schedulePoll()
  }
}

function backToSetup() {
  router.push({ name: 'compare' })
}

async function launchFromSession() {
  if (!canResumeFromSession.value) return
  rerunLoading.value = true
  rerunError.value = ''
  try {
    const { data } = await compareApi.createRun({
      left_document_id: session.value.leftDocumentId,
      right_document_id: session.value.rightDocumentId,
      model: session.value.model || sessionModel.value,
      index_name: session.value.indexName || sessionIndexName.value,
      strategy: session.value.strategy || rerunStrategy.value || 'hybrid',
      compare_mode: session.value.compareMode || compareMode.value || 'adaptive',
    })
    syncSession({
      runId: data.run_id,
      status: data.status,
      result: data.result || null,
    })
    await router.replace({ name: 'compare-result', params: { runId: data.run_id } })
  } catch (e) {
    rerunError.value = e.response?.data?.detail || e.message
  } finally {
    rerunLoading.value = false
  }
}

async function rerunAnalyze() {
  if (!leftDocumentId.value || !rightDocumentId.value) return
  rerunLoading.value = true
  rerunError.value = ''
  try {
    const { data } = await compareApi.createRun({
      left_document_id: leftDocumentId.value,
      right_document_id: rightDocumentId.value,
      model: sessionModel.value,
      index_name: sessionIndexName.value,
      strategy: rerunStrategy.value,
      compare_mode: compareMode.value,
    })
    syncSession({
      runId: data.run_id,
      status: data.status,
      strategy: rerunStrategy.value,
      compareMode: compareMode.value,
      result: data.result || null,
    })
    await router.replace({ name: 'compare-result', params: { runId: data.run_id } })
  } catch (e) {
    rerunError.value = e.response?.data?.detail || e.message
  } finally {
    rerunLoading.value = false
  }
}

onMounted(() => {
  if (!runId.value && canResumeFromSession.value) {
    void launchFromSession()
    return
  }
  void loadRun()
})

onBeforeUnmount(() => {
  clearPoll()
})

watch(runId, () => {
  void loadRun()
})

watch(result, (value) => {
  if (!value?.changes?.length) {
    selectedChangeId.value = ''
    return
  }
  if (!value.changes.some((change) => change.change_id === selectedChangeId.value)) {
    selectedChangeId.value = value.changes[0].change_id
  }
  rerunStrategy.value = run.value?.strategy || session.value?.strategy || value?.strategy || 'hybrid'
}, { immediate: true })

watch(selectedChange, (change) => {
  if (!change) return
  leftPage.value = Number(change.left_page || 1)
  rightPage.value = Number(change.right_page || 1)
})
</script>

<template>
  <div v-if="runLoading && !run" class="empty-root">
    <div class="empty-card">
      <v-progress-circular indeterminate color="primary" size="52" width="4" />
      <h2 class="mt-4 text-h6 font-weight-bold">Chargement du run</h2>
      <p class="text-body-2 text-medium-emphasis mt-1 mb-0">Le résultat est récupéré depuis le backend.</p>
    </div>
  </div>

  <div v-else-if="runError && !run" class="empty-root">
    <div class="empty-card">
      <v-icon size="56" color="error" icon="mdi-alert-circle-outline" />
      <h2 class="mt-4 text-h6 font-weight-bold">Run indisponible</h2>
      <p class="text-body-2 text-medium-emphasis mt-1 mb-5">{{ runError }}</p>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-arrow-left" @click="backToSetup">Retour</v-btn>
    </div>
  </div>

  <div v-else-if="!result && !showPendingState && !canResumeFromSession" class="empty-root">
    <div class="empty-card">
      <v-icon size="56" color="primary" icon="mdi-file-compare" />
      <h2 class="mt-4 text-h6 font-weight-bold">Aucune comparaison active</h2>
      <p class="text-body-2 text-medium-emphasis mt-1 mb-5">Sélectionne deux documents sur la page de préparation.</p>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-arrow-left" @click="backToSetup">Retour</v-btn>
    </div>
  </div>

  <div v-else-if="!result && !showPendingState && canResumeFromSession" class="empty-root">
    <div class="empty-card">
      <v-icon size="56" color="primary" icon="mdi-file-compare" />
      <h2 class="mt-4 text-h6 font-weight-bold">Relancer la comparaison</h2>
      <p class="text-body-2 text-medium-emphasis mt-1 mb-5">
        La sélection existe encore en session, mais aucun run actif n’est chargé.
      </p>
      <div class="d-flex ga-3 justify-center flex-wrap">
        <v-btn color="primary" variant="flat" prepend-icon="mdi-refresh" :loading="rerunLoading" @click="launchFromSession">
          Relancer avec ces documents
        </v-btn>
        <v-btn color="default" variant="tonal" prepend-icon="mdi-arrow-left" @click="backToSetup">Retour</v-btn>
      </div>
    </div>
  </div>

  <div v-else class="app-root">
    <header class="app-header">
      <div class="app-header__left">
        <v-btn icon="mdi-arrow-left" variant="text" size="small" color="white" @click="backToSetup" />
        <v-icon icon="mdi-file-compare" size="20" class="ml-1" />
        <span class="app-header__title">Changements détectés</span>
      </div>
      <div class="app-header__stats">
        <span class="pill" :class="hasChanges ? 'pill--danger' : 'pill--success'">
          <v-icon size="13" :icon="hasChanges ? 'mdi-alert-circle' : 'mdi-check-circle'" class="mr-1" />
          {{ summary.change_count || 0 }} changements
        </span>
        <span class="pill pill--muted">
          <v-icon size="13" icon="mdi-timer-outline" class="mr-1" />
          {{ summary.latency_ms || 0 }} ms
        </span>
        <span class="pill pill--muted">
          <v-icon size="13" icon="mdi-counter" class="mr-1" />
          {{ result?.usage?.total_tokens || 0 }} tokens
        </span>
        <span class="pill pill--accent">
          <v-icon size="13" icon="mdi-lightning-bolt" class="mr-1" />
          {{ run?.strategy || session?.strategy || result?.strategy || 'hybrid' }}
        </span>
        <span class="pill pill--muted">
          <v-icon size="13" icon="mdi-tune-variant" class="mr-1" />
          {{
            compareMode === 'full_lexical'
              ? 'full lexical diff'
              : compareMode === 'adaptive'
                ? 'adaptive'
                : 'standard'
          }}
        </span>
        <span v-if="summary.refined_change_count" class="pill pill--muted">
          <v-icon size="13" icon="mdi-tune" class="mr-1" />
          {{ summary.refined_change_count }} raffinés
        </span>
      </div>
      <div class="app-header__right">
        <v-select
          v-model="rerunStrategy"
          :items="strategyItems"
          density="default"
          variant="outlined"
          hide-details
          class="strat-sel"
          prepend-inner-icon="mdi-strategy"
        />
        <v-btn
          color="white"
          variant="flat"
          density="default"
          prepend-icon="mdi-refresh"
          :loading="rerunLoading"
          @click="rerunAnalyze"
          class="rerun-btn"
        >
          Relancer
        </v-btn>
      </div>
    </header>

    <v-alert v-if="runError || rerunError" type="error" variant="tonal" density="compact" class="ma-3">
      {{ rerunError || runError }}
    </v-alert>

    <v-alert v-if="showPendingState" type="info" variant="tonal" density="comfortable" class="ma-3">
      <div class="pending-alert">
        <div>
          <strong>{{ runStatus === 'queued' ? 'Run en file d’attente' : 'Comparaison en cours' }}</strong>
          <div class="text-body-2 text-medium-emphasis">
            Le backend aligne les blocs et calcule les diffs. Le résultat s’affichera automatiquement.
          </div>
        </div>
        <v-progress-circular indeterminate color="primary" size="20" width="3" />
      </div>
    </v-alert>

    <template v-if="result">
      <div class="summary-strip">
        <div class="summary-strip__main">
          <div class="summary-strip__label">Synthèse</div>
          <div v-if="summaryLooksLikeList" class="summary-strip__list">
            <div
              v-for="(item, index) in summaryItems"
              :key="`${index}-${item}`"
              class="summary-strip__item"
              :class="{ 'summary-strip__item--important': isImportantSummaryItem(item, index) }"
            >
              <span class="summary-strip__bullet" />
              <span class="summary-strip__item-text">{{ item }}</span>
            </div>
          </div>
          <div v-else class="summary-strip__text">{{ summaryText || 'Aucune synthèse disponible.' }}</div>
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
                <span class="change-card__title" :title="change.title">{{ change.title }}</span>
                <span class="change-card__importance" :class="`change-card__importance--${change.importance || 'medium'}`">
                  {{ change.importance || 'medium' }}
                </span>
              </div>
              <div class="change-card__meta">
                <span class="change-meta-chip">{{ change.change_subtype }}</span>
                <span v-if="change.left_page || change.right_page" class="change-meta-chip">
                  p.{{ change.left_page || '?' }} / p.{{ change.right_page || '?' }}
                </span>
                <span v-if="change.change_type !== 'modified'" class="change-meta-chip">{{ change.change_type }}</span>
              </div>
              <div class="change-card__summary" :title="change.summary">{{ change.summary }}</div>
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
                :viewer-height="'clamp(32rem, 72vh, 56rem)'"
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
                :viewer-height="'clamp(32rem, 72vh, 56rem)'"
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
    </template>
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
  gap: 20px;
  padding: 0 24px;
  min-height: 60px;
  background: #0f172a;
  color: #e2e8f0;
}

.app-header__left,
.app-header__right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.app-header__title {
  font-weight: 700;
  font-size: 1rem;
  letter-spacing: -0.01em;
}

.app-header__stats {
  display: flex;
  gap: 8px;
  flex: 1;
  justify-content: center;
  flex-wrap: wrap;
}

.strat-sel {
  width: 160px;
}

.strat-sel :deep(.v-field) {
  background: rgba(255, 255, 255, 0.08) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  color: #e2e8f0;
  border-radius: 8px;
  min-height: 38px;
}

.strat-sel :deep(.v-field__input) {
  color: #e2e8f0 !important;
  font-size: 0.82rem;
  padding-top: 4px;
  padding-bottom: 4px;
}

.pill {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.76rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
  gap: 5px;
  line-height: 1.2;
}

.pill--danger {
  background: rgba(239, 68, 68, 0.2);
  color: #fecaca;
}

.pill--muted {
  background: rgba(148, 163, 184, 0.15);
  color: #cbd5e1;
}

.pill--success {
  background: rgba(34, 197, 94, 0.2);
  color: #bbf7d0;
}

.pill--accent {
  background: rgba(99, 102, 241, 0.25);
  color: #c4b5fd;
}

.rerun-btn {
  font-weight: 600;
  letter-spacing: 0.01em;
  text-transform: none;
  font-size: 0.82rem;
  padding: 0 22px !important;
  height: 38px !important;
  border-radius: 8px !important;
  background: rgba(255, 255, 255, 0.12) !important;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fff !important;
  box-shadow: none !important;
  transition: background 0.15s, border-color 0.15s;
}

.rerun-btn:hover {
  background: rgba(255, 255, 255, 0.22) !important;
  border-color: rgba(255, 255, 255, 0.4);
}

.pending-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.summary-strip {
  display: grid;
  gap: 0.65rem;
  padding: 1rem 1.5rem;
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

.summary-strip__list {
  display: grid;
  gap: 0.45rem;
  margin-top: 0.35rem;
}

.summary-strip__item {
  display: grid;
  grid-template-columns: 0.55rem minmax(0, 1fr);
  gap: 0.55rem;
  align-items: start;
  padding: 0.1rem 0;
}

.summary-strip__item--important {
  padding: 0.45rem 0.6rem;
  border-radius: 0.8rem;
  background: linear-gradient(180deg, rgba(254, 242, 242, 0.9), rgba(255, 255, 255, 0.95));
  border: 1px solid rgba(248, 113, 113, 0.25);
}

.summary-strip__bullet {
  width: 0.4rem;
  height: 0.4rem;
  margin-top: 0.42rem;
  border-radius: 999px;
  background: #2563eb;
}

.summary-strip__item--important .summary-strip__bullet {
  background: #dc2626;
}

.summary-strip__item-text {
  min-width: 0;
  font-size: 0.88rem;
  line-height: 1.55;
  color: #334155;
  overflow-wrap: anywhere;
}

.summary-strip__item--important .summary-strip__item-text {
  color: #7f1d1d;
  font-weight: 600;
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
  overflow: hidden;
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
  padding: 0.5rem;
  display: grid;
  gap: 0.45rem;
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
  display: grid;
  gap: 0.35rem;
  padding: 0.65rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  min-width: 0;
  transition: background 0.1s, border-color 0.1s;
}

.change-card:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.change-card--active {
  background: #eff6ff;
  border-color: #93c5fd;
  box-shadow: 0 0 0 1px #93c5fd;
}

.change-card__top,
.change-card__meta {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.change-card__title {
  flex: 1;
  min-width: 0;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
  overflow: hidden;
  font-size: 0.78rem;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.3;
}

.change-card__importance {
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.42rem;
  border-radius: 6px;
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.change-card__importance--high,
.change-card__importance--critical {
  background: rgba(220, 38, 38, 0.12);
  color: #b91c1c;
}

.change-card__importance--medium {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}

.change-card__importance--low {
  background: rgba(37, 99, 235, 0.12);
  color: #1d4ed8;
}

.change-card__meta {
  margin-top: 0;
  row-gap: 0.16rem;
  column-gap: 0.18rem;
  min-width: 0;
}

.change-meta-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.12rem 0.38rem;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  font-size: 0.64rem;
  line-height: 1.2;
  color: #64748b;
  white-space: nowrap;
  font-weight: 500;
}

.change-card__summary {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  font-size: 0.7rem;
  line-height: 1.4;
  color: #64748b;
}

.pdf-area {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
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
  align-items: stretch;
  min-height: 0;
}

.pdf-pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.pdf-pane :deep(.pdf-viewer-card) {
  width: 100%;
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
