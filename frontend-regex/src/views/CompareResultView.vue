<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PdfPageViewer from '@/components/PdfPageViewer.vue'
import { compareApi } from '@/services/api'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const router = useRouter()

const session = computed(() => store.compareSession)
const result = computed(() => session.value?.result || null)
const leftDocument = computed(() => session.value?.leftDocument || null)
const rightDocument = computed(() => session.value?.rightDocument || null)
const leftLayout = computed(() => session.value?.leftLayout || null)
const rightLayout = computed(() => session.value?.rightLayout || null)
const leftDocumentId = computed(() => session.value?.leftDocumentId || '')
const rightDocumentId = computed(() => session.value?.rightDocumentId || '')
const sessionClaims = computed(() => session.value?.claims || [])
const sessionAutoDiff = computed(() => session.value?.autoDiff ?? true)
const sessionModel = computed(() => session.value?.model || 'openrouter/qwen/qwen3.5-9b:exacto')
const sessionIndexName = computed(() => session.value?.indexName || 'default')
const sessionTopK = computed(() => session.value?.topK || 5)

const selectedIssueId = ref('')
const leftPage = ref(1)
const rightPage = ref(1)
const rerunLoading = ref(false)
const rerunError = ref('')
const rerunStrategy = ref('')
const panelOpen = ref(true)
const panelTab = ref('decision')

const selectedIssue = computed(() =>
  (result.value?.issues || []).find((issue) => issue.issue_id === selectedIssueId.value) || null
)
const leftEvidence = computed(() => selectedIssue.value?.left_evidence || [])
const rightEvidence = computed(() => selectedIssue.value?.right_evidence || [])
const structuredDiffs = computed(() => selectedIssue.value?.structured_diffs || [])
const retrievalMeta = computed(() => selectedIssue.value?.retrieval || {})
const strategyItems = [
  { title: 'Hybrid', value: 'hybrid' },
  { title: 'Semantic', value: 'semantic' },
  { title: 'Lexical', value: 'lexical' },
  { title: 'RG', value: 'rg' },
]

const stats = computed(() => {
  const s = result.value?.summary || {}
  const issues = result.value?.issues || []
  return {
    inconsistent: s.inconsistent_count || 0,
    insufficient: s.insufficient_evidence_count || 0,
    consistent: issues.filter((i) => i.verdict === 'consistent').length,
    latency: s.latency_ms || 0,
    tokens: result.value?.usage?.total_tokens || 0,
    total: issues.length,
  }
})

const severityColor = { critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#3b82f6' }
const verdictConf = {
  inconsistent: { bg: '#fef2f2', fg: '#dc2626', ring: '#fca5a5' },
  consistent: { bg: '#f0fdf4', fg: '#16a34a', ring: '#86efac' },
  insufficient_evidence: { bg: '#fffbeb', fg: '#d97706', ring: '#fcd34d' },
}

const leftHighlights = computed(() => buildHighlights(selectedIssue.value?.left_evidence || [], leftPage.value, '#dc2626'))
const rightHighlights = computed(() => buildHighlights(selectedIssue.value?.right_evidence || [], rightPage.value, '#0f766e'))

watch(result, (value) => {
  if (!value?.issues?.length) return
  selectedIssueId.value = value.issues[0].issue_id
  rerunStrategy.value = session.value?.strategy || value?.strategy || 'hybrid'
}, { immediate: true })

watch(selectedIssue, (issue) => {
  if (!issue) return
  const leftHit = issue.left_evidence?.[0]
  const rightHit = issue.right_evidence?.[0]
  if (leftHit?.metadata?.page_number) leftPage.value = Number(leftHit.metadata.page_number)
  if (rightHit?.metadata?.page_number) rightPage.value = Number(rightHit.metadata.page_number)
})

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

function backToSetup() { router.push({ name: 'compare' }) }

async function rerunAnalyze() {
  if (!leftDocumentId.value || !rightDocumentId.value) return
  rerunLoading.value = true
  rerunError.value = ''
  try {
    const { data } = await compareApi.analyze({
      left_document_id: leftDocumentId.value,
      right_document_id: rightDocumentId.value,
      claims: sessionClaims.value,
      auto_diff: sessionAutoDiff.value,
      model: sessionModel.value,
      index_name: sessionIndexName.value,
      strategy: rerunStrategy.value,
      top_k: sessionTopK.value,
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
  <!-- EMPTY STATE -->
  <div v-if="!result" class="empty-root">
    <div class="empty-card">
      <v-icon size="56" color="primary" icon="mdi-file-compare" />
      <h2 class="mt-4 text-h6 font-weight-bold">No active comparison</h2>
      <p class="text-body-2 text-medium-emphasis mt-1 mb-5">Start by selecting two documents on the setup page.</p>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-arrow-left" @click="backToSetup">Back to setup</v-btn>
    </div>
  </div>

  <!-- FULL-HEIGHT APP LAYOUT -->
  <div v-else class="app-root">
    <!-- ═══ HEADER ═══ -->
    <header class="app-header">
      <div class="app-header__left">
        <v-btn icon="mdi-arrow-left" variant="text" density="compact" @click="backToSetup" />
        <v-icon icon="mdi-file-compare" size="20" class="ml-1" />
        <span class="app-header__title">Comparison</span>
      </div>

      <div class="app-header__stats">
        <span class="pill" :class="'pill--' + (stats.inconsistent ? 'danger' : 'muted')">
          <v-icon size="13" icon="mdi-alert-circle" class="mr-1" />
          {{ stats.inconsistent }} inconsistent
        </span>
        <span class="pill pill--warn" v-if="stats.insufficient">
          <v-icon size="13" icon="mdi-help-circle-outline" class="mr-1" />
          {{ stats.insufficient }} low evidence
        </span>
        <span class="pill pill--ok" v-if="stats.consistent">
          <v-icon size="13" icon="mdi-check-circle-outline" class="mr-1" />
          {{ stats.consistent }} consistent
        </span>
        <span class="pill pill--muted">
          <v-icon size="13" icon="mdi-timer-outline" class="mr-1" />
          {{ stats.latency }} ms
        </span>
        <span class="pill pill--muted">
          <v-icon size="13" icon="mdi-counter" class="mr-1" />
          {{ stats.tokens }} tokens
        </span>
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
          Rerun
        </v-btn>
      </div>
    </header>

    <v-alert v-if="rerunError" type="error" variant="tonal" density="compact" class="ma-3">
      {{ rerunError }}
    </v-alert>

    <!-- ═══ MAIN WORKSPACE ═══ -->
    <div class="workspace">
      <!-- ISSUE RAIL -->
      <nav class="issue-rail">
        <div class="issue-rail__head">
          <span>Issues</span>
          <span class="issue-rail__count">{{ stats.total }}</span>
        </div>
        <div class="issue-rail__scroll">
          <button
            v-for="issue in result.issues"
            :key="issue.issue_id"
            type="button"
            class="issue-card"
            :class="{ 'issue-card--active': selectedIssueId === issue.issue_id }"
            @click="selectedIssueId = issue.issue_id"
          >
            <div class="issue-card__dot" :style="{ background: severityColor[issue.severity] || '#64748b' }" />
            <div class="issue-card__body">
              <div class="issue-card__row">
                <span class="issue-card__claim">{{ issue.claim }}</span>
                <span
                  class="issue-card__badge"
                  :style="{
                    background: (verdictConf[issue.verdict] || verdictConf.insufficient_evidence).bg,
                    color: (verdictConf[issue.verdict] || verdictConf.insufficient_evidence).fg,
                  }"
                >{{ issue.verdict }}</span>
              </div>
              <span class="issue-card__summary">{{ issue.summary }}</span>
            </div>
          </button>
        </div>
      </nav>

      <!-- CENTER: PDF AREA -->
      <div class="pdf-area">
        <!-- VERDICT BAR -->
        <div class="verdict-bar" v-if="selectedIssue">
          <div class="verdict-bar__indicator" :style="{ background: severityColor[selectedIssue.severity] || '#64748b' }" />
          <div class="verdict-bar__content">
            <span
              class="verdict-bar__tag"
              :style="{
                background: (verdictConf[selectedIssue.verdict] || verdictConf.insufficient_evidence).bg,
                color: (verdictConf[selectedIssue.verdict] || verdictConf.insufficient_evidence).fg,
                border: '1px solid ' + (verdictConf[selectedIssue.verdict] || verdictConf.insufficient_evidence).ring,
              }"
            >{{ selectedIssue.verdict }}</span>
            <span class="verdict-bar__claim">{{ selectedIssue.claim }}</span>
            <span class="verdict-bar__sep">|</span>
            <span class="verdict-bar__text">{{ selectedIssue.summary }}</span>
          </div>
          <button class="verdict-bar__toggle" @click="panelOpen = !panelOpen">
            <v-icon size="18" :icon="panelOpen ? 'mdi-chevron-down' : 'mdi-chevron-up'" />
          </button>
        </div>

        <!-- PDFs -->
        <div class="pdf-split">
          <div class="pdf-pane">
            <PdfPageViewer
              title="Document A"
              :document-id="leftDocumentId"
              :filename="leftDocument?.filename || ''"
              :page="leftPage"
              :total-pages="leftLayout?.num_pages || leftDocument?.total_pages || leftDocument?.num_pages || 0"
              :highlights="leftHighlights"
              :viewer-height="'calc(100vh - ' + (panelOpen ? '380' : '180') + 'px)'"
              @update:page="leftPage = $event"
            />
          </div>
          <div class="pdf-divider" />
          <div class="pdf-pane">
            <PdfPageViewer
              title="Document B"
              :document-id="rightDocumentId"
              :filename="rightDocument?.filename || ''"
              :page="rightPage"
              :total-pages="rightLayout?.num_pages || rightDocument?.total_pages || rightDocument?.num_pages || 0"
              :highlights="rightHighlights"
              :viewer-height="'calc(100vh - ' + (panelOpen ? '380' : '180') + 'px)'"
              @update:page="rightPage = $event"
            />
          </div>
        </div>

        <!-- BOTTOM PANEL -->
        <transition name="slide-panel">
          <div v-if="panelOpen" class="bottom-panel">
            <div class="bottom-panel__tabs">
              <button
                v-for="t in [
                  { key: 'decision', icon: 'mdi-gavel', label: 'Decision' },
                  { key: 'diffs', icon: 'mdi-swap-horizontal', label: 'Diffs' },
                  { key: 'evidence', icon: 'mdi-file-search-outline', label: 'Evidence' },
                  { key: 'meta', icon: 'mdi-cog-outline', label: 'Retrieval' },
                ]"
                :key="t.key"
                class="bp-tab"
                :class="{ 'bp-tab--active': panelTab === t.key }"
                @click="panelTab = t.key"
              >
                <v-icon size="14" :icon="t.icon" />
                {{ t.label }}
              </button>
            </div>

            <div class="bottom-panel__body">
              <!-- DECISION TAB -->
              <div v-if="panelTab === 'decision'" class="bp-grid">
                <div class="bp-field">
                  <span class="bp-label">Verdict</span>
                  <span
                    class="bp-value bp-value--tag"
                    :style="{
                      background: (verdictConf[selectedIssue?.verdict] || verdictConf.insufficient_evidence).bg,
                      color: (verdictConf[selectedIssue?.verdict] || verdictConf.insufficient_evidence).fg,
                    }"
                  >{{ selectedIssue?.verdict || 'n/a' }}</span>
                </div>
                <div class="bp-field">
                  <span class="bp-label">Severity</span>
                  <span class="bp-value" :style="{ color: severityColor[selectedIssue?.severity] || '#334155' }">
                    {{ selectedIssue?.severity || 'n/a' }}
                  </span>
                </div>
                <div class="bp-field">
                  <span class="bp-label">Confidence</span>
                  <span class="bp-value">{{ selectedIssue?.confidence ?? 'n/a' }}</span>
                </div>
                <div class="bp-field">
                  <span class="bp-label">Evidence quality</span>
                  <span class="bp-value">{{ selectedIssue?.evidence_quality || 'unknown' }}</span>
                </div>
                <div class="bp-field">
                  <span class="bp-label">Source</span>
                  <span class="bp-value">{{ selectedIssue?.decision_source || 'unknown' }}</span>
                </div>
                <div class="bp-field">
                  <span class="bp-label">Category</span>
                  <span class="bp-value">{{ selectedIssue?.category || 'general' }}</span>
                </div>
                <div class="bp-field bp-field--full">
                  <span class="bp-label">Rationale</span>
                  <span class="bp-value bp-value--prose">{{ selectedIssue?.rationale || 'No rationale available.' }}</span>
                </div>
              </div>

              <!-- DIFFS TAB -->
              <div v-if="panelTab === 'diffs'" class="bp-diffs">
                <div v-if="!structuredDiffs.length" class="bp-empty">No structured diffs for this issue.</div>
                <div v-for="(diff, i) in structuredDiffs" :key="i" class="bp-diff-card">
                  <div class="bp-diff-card__head">
                    <span>{{ diff.field_type }}</span>
                    <span class="bp-diff-card__kind" :class="{ 'bp-diff-card__kind--bad': diff.diff_kind === 'value_mismatch' }">
                      {{ diff.diff_kind }}
                    </span>
                  </div>
                  <div class="bp-diff-card__row">
                    <span class="bp-diff-card__side bp-diff-card__side--a">A</span>
                    <span>{{ diff.left_raw || 'n/a' }}</span>
                  </div>
                  <div class="bp-diff-card__row">
                    <span class="bp-diff-card__side bp-diff-card__side--b">B</span>
                    <span>{{ diff.right_raw || 'n/a' }}</span>
                  </div>
                </div>
              </div>

              <!-- EVIDENCE TAB -->
              <div v-if="panelTab === 'evidence'" class="bp-evidence">
                <div class="bp-evidence__col">
                  <div class="bp-evidence__head">
                    <span>Evidence A</span>
                    <span class="bp-evidence__cnt bp-evidence__cnt--a">{{ leftEvidence.length }}</span>
                  </div>
                  <div v-if="!leftEvidence.length" class="bp-empty">No left evidence.</div>
                  <div v-for="item in leftEvidence" :key="item.id" class="bp-ev">
                    <div class="bp-ev__meta">
                      <span>{{ item.metadata?.page_number ? `p.${item.metadata.page_number}` : 'no page' }}</span>
                      <span v-if="item.score !== undefined">{{ Number(item.score).toFixed(3) }}</span>
                    </div>
                    <div v-if="item.section_hint" class="bp-ev__section">{{ item.section_hint }}</div>
                    <div class="bp-ev__text">{{ item.text || 'Unavailable' }}</div>
                  </div>
                </div>
                <div class="bp-evidence__col">
                  <div class="bp-evidence__head">
                    <span>Evidence B</span>
                    <span class="bp-evidence__cnt bp-evidence__cnt--b">{{ rightEvidence.length }}</span>
                  </div>
                  <div v-if="!rightEvidence.length" class="bp-empty">No right evidence.</div>
                  <div v-for="item in rightEvidence" :key="item.id" class="bp-ev">
                    <div class="bp-ev__meta">
                      <span>{{ item.metadata?.page_number ? `p.${item.metadata.page_number}` : 'no page' }}</span>
                      <span v-if="item.score !== undefined">{{ Number(item.score).toFixed(3) }}</span>
                    </div>
                    <div v-if="item.section_hint" class="bp-ev__section">{{ item.section_hint }}</div>
                    <div class="bp-ev__text">{{ item.text || 'Unavailable' }}</div>
                  </div>
                </div>
              </div>

              <!-- META TAB -->
              <div v-if="panelTab === 'meta'" class="bp-grid">
                <div class="bp-field"><span class="bp-label">Strategy</span><span class="bp-value">{{ retrievalMeta.strategy || result.strategy || 'n/a' }}</span></div>
                <div class="bp-field"><span class="bp-label">Candidates</span><span class="bp-value">{{ retrievalMeta.candidate_count ?? 0 }}</span></div>
                <div class="bp-field"><span class="bp-label">Pairs</span><span class="bp-value">{{ retrievalMeta.pair_candidate_count ?? 0 }}</span></div>
                <div class="bp-field"><span class="bp-label">Evidence kept</span><span class="bp-value">{{ retrievalMeta.evidence_kept_count ?? 0 }}</span></div>
                <div class="bp-field"><span class="bp-label">Latency</span><span class="bp-value">{{ retrievalMeta.latency_ms ?? 0 }} ms</span></div>
                <div class="bp-field"><span class="bp-label">Semantic error</span><span class="bp-value">{{ retrievalMeta.semantic_error || 'none' }}</span></div>
                <div class="bp-field bp-field--full" v-if="retrievalMeta.best_pair_reason">
                  <span class="bp-label">Pairing reason</span>
                  <span class="bp-value bp-value--prose">{{ retrievalMeta.best_pair_reason }}</span>
                </div>
              </div>
            </div>
          </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════
   FULL-HEIGHT APP LAYOUT
   ═══════════════════════════════════════ */

/* Empty state */
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

/* Root: fills the viewport below the app-bar */
.app-root {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px - 48px); /* app-bar + container padding */
  margin: -24px; /* counteract v-container pa-6 */
  overflow: hidden;
  background: #f8fafc;
}

/* ═══ HEADER ═══ */
.app-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  height: 48px;
  background: #0f172a;
  color: #e2e8f0;
  flex-shrink: 0;
}
.app-header__left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.app-header__title {
  font-weight: 700;
  font-size: 0.9rem;
  letter-spacing: -0.01em;
}
.app-header__stats {
  display: flex;
  gap: 8px;
  flex: 1;
  justify-content: center;
}
.app-header__right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.strat-sel {
  width: 130px;
}
.strat-sel :deep(.v-field) {
  background: rgba(255, 255, 255, 0.08) !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: #e2e8f0;
  font-size: 0.8rem;
}

/* Pills in header */
.pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.pill--danger { background: rgba(239, 68, 68, 0.18); color: #fca5a5; }
.pill--warn { background: rgba(234, 179, 8, 0.18); color: #fde68a; }
.pill--ok { background: rgba(22, 163, 74, 0.18); color: #86efac; }
.pill--muted { background: rgba(148, 163, 184, 0.12); color: #94a3b8; }

/* ═══ WORKSPACE (sidebar + center) ═══ */
.workspace {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ═══ ISSUE RAIL ═══ */
.issue-rail {
  width: 300px;
  min-width: 300px;
  background: #fff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.issue-rail__head {
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
.issue-rail__count {
  background: #f1f5f9;
  color: #64748b;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
}
.issue-rail__scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* Issue card */
.issue-card {
  display: flex;
  gap: 10px;
  text-align: left;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  transition: all 0.1s;
}
.issue-card:hover { background: #f8fafc; border-color: #e2e8f0; }
.issue-card--active { background: #eff6ff; border-color: #93c5fd; }
.issue-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}
.issue-card__body { flex: 1; min-width: 0; }
.issue-card__row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.issue-card__claim {
  font-size: 0.8rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.issue-card__badge {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.03em;
  white-space: nowrap;
}
.issue-card__summary {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 0.72rem;
  color: #94a3b8;
  margin-top: 3px;
  line-height: 1.4;
}

/* ═══ PDF AREA ═══ */
.pdf-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

/* Verdict bar */
.verdict-bar {
  display: flex;
  align-items: center;
  gap: 0;
  height: 40px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.verdict-bar__indicator {
  width: 3px;
  height: 100%;
  flex-shrink: 0;
}
.verdict-bar__content {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  padding: 0 12px;
  overflow: hidden;
}
.verdict-bar__tag {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 5px;
  letter-spacing: 0.03em;
  white-space: nowrap;
  flex-shrink: 0;
}
.verdict-bar__claim {
  font-size: 0.82rem;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.verdict-bar__sep {
  color: #e2e8f0;
  font-size: 0.8rem;
  flex-shrink: 0;
}
.verdict-bar__text {
  font-size: 0.78rem;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.verdict-bar__toggle {
  padding: 0 12px;
  height: 100%;
  display: flex;
  align-items: center;
  cursor: pointer;
  color: #94a3b8;
  flex-shrink: 0;
  background: none;
  border: none;
  border-left: 1px solid #f1f5f9;
  transition: color 0.12s;
}
.verdict-bar__toggle:hover { color: #475569; }

/* PDF split */
.pdf-split {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.pdf-pane {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.pdf-divider {
  width: 1px;
  background: #e2e8f0;
  flex-shrink: 0;
}

/* ═══ BOTTOM PANEL ═══ */
.bottom-panel {
  background: #fff;
  border-top: 1px solid #e2e8f0;
  flex-shrink: 0;
  max-height: 240px;
  display: flex;
  flex-direction: column;
}

/* Panel tabs */
.bottom-panel__tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid #f1f5f9;
  padding: 0 12px;
  flex-shrink: 0;
}
.bp-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 14px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  cursor: pointer;
  border: none;
  background: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 0.1s;
}
.bp-tab:hover { color: #475569; }
.bp-tab--active { color: #1e293b; border-bottom-color: #3b82f6; }

/* Panel body */
.bottom-panel__body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
}

/* Grid layout for decision/meta */
.bp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px 20px;
}
.bp-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.bp-field--full {
  grid-column: 1 / -1;
}
.bp-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  font-weight: 600;
}
.bp-value {
  font-size: 0.85rem;
  font-weight: 600;
  color: #1e293b;
}
.bp-value--tag {
  display: inline-block;
  width: fit-content;
  padding: 2px 8px;
  border-radius: 5px;
  text-transform: uppercase;
  font-size: 0.72rem;
  letter-spacing: 0.03em;
}
.bp-value--prose {
  font-weight: 400;
  font-size: 0.82rem;
  color: #475569;
  line-height: 1.55;
}

/* Diffs */
.bp-diffs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.bp-diff-card {
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  min-width: 220px;
  flex: 1;
}
.bp-diff-card__head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 700;
  font-size: 0.82rem;
  color: #334155;
}
.bp-diff-card__kind {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 4px;
  background: #f0fdf4;
  color: #16a34a;
}
.bp-diff-card__kind--bad {
  background: #fef2f2;
  color: #dc2626;
}
.bp-diff-card__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 0.85rem;
  color: #334155;
}
.bp-diff-card__side {
  font-size: 0.68rem;
  font-weight: 700;
  width: 20px;
  height: 20px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.bp-diff-card__side--a { background: #dc2626; }
.bp-diff-card__side--b { background: #0f766e; }

/* Evidence */
.bp-evidence {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.bp-evidence__col {
  min-width: 0;
}
.bp-evidence__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 0.82rem;
  color: #334155;
  margin-bottom: 10px;
}
.bp-evidence__cnt {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 999px;
  color: #fff;
}
.bp-evidence__cnt--a { background: #dc2626; }
.bp-evidence__cnt--b { background: #0f766e; }
.bp-empty {
  font-size: 0.8rem;
  color: #94a3b8;
}
.bp-ev {
  padding: 10px;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  margin-bottom: 8px;
}
.bp-ev__meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.68rem;
  color: #94a3b8;
  margin-bottom: 4px;
}
.bp-ev__section {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.68rem;
  font-weight: 600;
  margin-bottom: 5px;
}
.bp-ev__text {
  font-size: 0.8rem;
  color: #334155;
  line-height: 1.5;
  white-space: pre-wrap;
}

/* Slide panel transition */
.slide-panel-enter-active,
.slide-panel-leave-active {
  transition: max-height 0.2s ease, opacity 0.15s ease;
}
.slide-panel-enter-from,
.slide-panel-leave-to {
  max-height: 0;
  opacity: 0;
}
.slide-panel-enter-to,
.slide-panel-leave-from {
  max-height: 240px;
  opacity: 1;
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 1100px) {
  .app-root { height: auto; overflow: auto; margin: -24px; }
  .workspace { flex-direction: column; }
  .issue-rail { width: 100%; min-width: 0; max-height: 200px; border-right: none; border-bottom: 1px solid #e2e8f0; }
  .issue-rail__scroll { flex-direction: row; overflow-x: auto; overflow-y: hidden; }
  .issue-card { min-width: 240px; }
  .pdf-split { flex-direction: column; }
  .pdf-divider { width: 100%; height: 1px; }
  .bp-evidence { grid-template-columns: 1fr; }
}
</style>
