<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const router = useRouter()

const experimentConfig = ref({
  datasetName: 'kensho/FIND',
  split: 'validation',
  datasetSubset: null,
  maxSamples: 100,
  indexName: 'default',
  topK: 10,
  strategies: ['baseline', 'lexical', 'semantic', 'hybrid', 'rg'],
  streaming: true,
  cacheDir: null,
  maxQueryChars: 8192,
})

const runningExperiment = ref(false)
const experimentLogs = ref([])
const datasetOptions = [
  { title: 'FIND', value: 'kensho/FIND' },
  { title: 'NanoBEIR (streaming)', value: 'sionic-ai/NanoBEIR-en' },
  { title: 'Wikipedia Contradict', value: 'ibm-research/Wikipedia_contradict_benchmark' },
]
const nanoBeirSubsetOptions = ['NanoSciFact', 'NanoNFCorpus', 'NanoFiQA2018', 'NanoArguAna']
const splitOptions = computed(() =>
  experimentConfig.value.datasetName === 'ibm-research/Wikipedia_contradict_benchmark'
    ? ['train']
    : ['validation', 'test']
)
watch(splitOptions, (options) => {
  if (experimentConfig.value.datasetName !== 'sionic-ai/NanoBEIR-en' && !options.includes(experimentConfig.value.split)) {
    experimentConfig.value.split = options[0]
  }
}, { immediate: true })
watch(() => experimentConfig.value.datasetName, (datasetName) => {
  if (datasetName === 'sionic-ai/NanoBEIR-en') {
    experimentConfig.value.datasetSubset = experimentConfig.value.datasetSubset || 'NanoSciFact'
    experimentConfig.value.split = 'validation'
  } else {
    experimentConfig.value.datasetSubset = null
  }
}, { immediate: true })
const canRunExperiment = computed(() =>
  !runningExperiment.value
  && Number(experimentConfig.value.maxSamples) > 0
  && Number(experimentConfig.value.topK) > 0
  && Array.isArray(experimentConfig.value.strategies)
  && experimentConfig.value.strategies.length > 0
)

const strategies = [
  { title: 'Baseline (naïf)', value: 'baseline' },
  { title: 'Lexical (Cursor-like)', value: 'lexical' },
  { title: 'Sémantique (NextPlaid)', value: 'semantic' },
  { title: 'Hybride (recherche)', value: 'hybrid' },
  { title: 'RG (full scan regex)', value: 'rg' },
]

const experimentHistory = computed(() => store.experimentHistory.slice(0, 10))
const resultSummary = computed(() => {
  const comparison = store.experimentResults?.comparison
  if (!comparison) return null
  const bestStrategy = comparison.best_strategy_by_recall || '-'
  const reports = comparison.reports || {}
  const bestRow = reports[bestStrategy] || null
  return {
    bestStrategy,
    recall: Number(bestRow?.mean_recall_at_k || 0),
    latency: Number(bestRow?.mean_latency_ms || 0),
    samples: Number(store.experimentResults?.samples_count || 0),
    skipped: Number(store.experimentResults?.skipped_too_long_queries || 0),
  }
})

onMounted(async () => {
  await Promise.all([
    store.fetchExperimentHistory(),
    store.fetchExperimentHistorySummary(),
  ])
})

const comparisonRows = computed(() => {
  const reports = store.experimentResults?.comparison?.reports
  if (!reports || typeof reports !== 'object') return []
  return Object.entries(reports).map(([strategy, values]) => ({
    strategy,
    ...values,
  }))
})

const comparisonChart = computed(() => {
  if (comparisonRows.value.length === 0) return null

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Recall@K', 'MRR', 'nDCG'] },
    xAxis: {
      type: 'category',
      data: comparisonRows.value.map(c => c.strategy),
    },
    yAxis: [
      { type: 'value', name: 'Recall@K', max: 1 },
      { type: 'value', name: 'MRR / nDCG', max: 1 },
    ],
    series: [
      {
        name: 'Recall@K',
        type: 'bar',
        data: comparisonRows.value.map(c => c.mean_recall_at_k || 0),
      },
      {
        name: 'MRR',
        type: 'line',
        yAxisIndex: 1,
        data: comparisonRows.value.map(c => c.mean_mrr || 0),
      },
      {
        name: 'nDCG',
        type: 'line',
        yAxisIndex: 1,
        data: comparisonRows.value.map(c => c.mean_ndcg_at_k || 0),
      },
    ],
  }
})

async function runExperiment() {
  if (!canRunExperiment.value) {
    experimentLogs.value.push({
      time: new Date(),
      message: 'Configuration invalide: vérifie split, top_k, max_samples et stratégies.',
      isError: true,
    })
    return
  }

  runningExperiment.value = true
  experimentLogs.value = []
  
  experimentLogs.value.push({ time: new Date(), message: 'Démarrage de l\'expérience...' })
  
  try {
    if (!splitOptions.value.includes(experimentConfig.value.split)) {
      throw new Error(`Split invalide: ${experimentConfig.value.split}. Utilise validation ou test.`)
    }

    experimentLogs.value.push({ time: new Date(), message: `Chargement dataset: ${experimentConfig.value.datasetName}` })
    experimentLogs.value.push({ time: new Date(), message: `Split: ${experimentConfig.value.split}, Samples: ${experimentConfig.value.maxSamples}` })
    
    const result = await store.runExperiment(experimentConfig.value)
    
    experimentLogs.value.push({ time: new Date(), message: 'Expérience terminée avec succès!' })
    experimentLogs.value.push({
      time: new Date(),
      message: `Meilleure stratégie: ${result?.comparison?.best_strategy_by_recall || '-'}`,
    })
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || 'Erreur inconnue'
    experimentLogs.value.push({ time: new Date(), message: `Erreur: ${detail}`, isError: true })
  } finally {
    runningExperiment.value = false
  }
}

function exportResults() {
  const data = JSON.stringify(store.experimentResults, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `experiment-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function openRun(runId) {
  router.push({ name: 'experiment-run', params: { runId } })
}
</script>

<template>
  <div class="experiments-view">
    <v-row class="mb-5">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-flask" class="mr-2" />
          Benchmarks de recherche
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Mesure la qualité de récupération des stratégies de recherche. Cette surface benchmarke le retrieval, pas le compareur diff-first.
        </p>
        <v-alert type="info" variant="tonal" class="mt-4 experiments-alert">
          Ici, <strong>hybrid</strong> signifie <strong>recherche hybride</strong>:
          fusion sémantique + lexicale pour retrouver les bons passages.
          Ce n'est pas le mode <strong>adaptive/full lexical</strong> du compareur documentaire.
        </v-alert>
        <v-alert type="warning" variant="tonal" class="mt-4 experiments-alert">
          <strong>FIND</strong> reste utile comme sanity check, mais il favorise souvent le lexical exact.
          Utilise <strong>NanoBEIR</strong> pour challenger plus sérieusement les stratégies actuelles sans cache local manuel.
        </v-alert>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" lg="4">
        <v-card class="config-card">
          <v-card-title>
            <v-icon icon="mdi-cog" class="mr-2" />
            Configuration
          </v-card-title>
          <v-card-text>
            <v-btn
              color="primary"
              size="large"
              block
              :loading="runningExperiment"
              :disabled="!canRunExperiment"
              @click="runExperiment"
              class="mb-4"
            >
              <v-icon icon="mdi-play" class="mr-2" />
              Lancer le benchmark
            </v-btn>

            <v-select
              v-model="experimentConfig.datasetName"
              :items="datasetOptions"
              label="Dataset"
              variant="outlined"
              density="compact"
            />

            <v-select
              v-if="experimentConfig.datasetName !== 'sionic-ai/NanoBEIR-en'"
              v-model="experimentConfig.split"
              :items="splitOptions"
              label="Split"
              variant="outlined"
              density="compact"
            />

            <v-select
              v-if="experimentConfig.datasetName === 'sionic-ai/NanoBEIR-en'"
              v-model="experimentConfig.datasetSubset"
              :items="nanoBeirSubsetOptions"
              label="Subset"
              variant="outlined"
              density="compact"
            />

            <v-text-field
              v-model.number="experimentConfig.maxSamples"
              label="Nombre d'échantillons"
              type="number"
              variant="outlined"
              density="compact"
            />

            <v-select
              v-model="experimentConfig.indexName"
              :items="['default', 'documents', 'evidence']"
              label="Index"
              variant="outlined"
              density="compact"
            />

            <v-select
              v-model="experimentConfig.topK"
              :items="[5, 10, 20, 50]"
              label="Top K"
              variant="outlined"
              density="compact"
            />

            <v-select
              v-model="experimentConfig.strategies"
              :items="strategies"
              label="Stratégies à comparer"
              multiple
              variant="outlined"
              density="compact"
            />

            <v-expansion-panels variant="accordion" class="mb-2">
              <v-expansion-panel>
                <v-expansion-panel-title>Réglages avancés</v-expansion-panel-title>
                <v-expansion-panel-text>
                  <v-switch
                    v-model="experimentConfig.streaming"
                    label="Mode streaming dataset"
                    color="primary"
                    hide-details
                    class="mb-2"
                  />

                  <v-text-field
                    v-model.number="experimentConfig.maxQueryChars"
                    label="Longueur max des requêtes"
                    type="number"
                    variant="outlined"
                    density="compact"
                    hint="Évite les runs biaisés par des requêtes anormalement longues."
                    persistent-hint
                  />
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </v-card-text>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>
            <v-icon icon="mdi-console" class="mr-2" />
            Journal du run
          </v-card-title>
          <v-card-text class="logs-card">
            <v-list density="compact">
              <v-list-item
                v-for="(log, i) in experimentLogs"
                :key="i"
                :class="{ 'text-error': log.isError }"
              >
                <template v-slot:prepend>
                  <v-icon
                    :icon="log.isError ? 'mdi-alert-circle' : 'mdi-clock-outline'"
                    :color="log.isError ? 'error' : 'grey'"
                    size="small"
                  />
                </template>
                <v-list-item-title class="text-body-2">
                  <span class="text-medium-emphasis">[{{ log.time.toLocaleTimeString() }}]</span>
                  {{ log.message }}
                </v-list-item-title>
              </v-list-item>
            </v-list>
            <div v-if="experimentLogs.length === 0" class="text-center text-medium-emphasis pa-4">
              Aucun log
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" lg="8">
        <v-row class="mb-4" v-if="resultSummary">
          <v-col cols="12" md="3">
            <v-card class="summary-card">
              <v-card-text>
                <div class="summary-label">Meilleure stratégie</div>
                <div class="summary-value">{{ resultSummary.bestStrategy }}</div>
              </v-card-text>
            </v-card>
          </v-col>
          <v-col cols="12" md="3">
            <v-card class="summary-card">
              <v-card-text>
                <div class="summary-label">Recall moyen</div>
                <div class="summary-value">{{ resultSummary.recall.toFixed(3) }}</div>
              </v-card-text>
            </v-card>
          </v-col>
          <v-col cols="12" md="3">
            <v-card class="summary-card">
              <v-card-text>
                <div class="summary-label">Latence moyenne</div>
                <div class="summary-value">{{ resultSummary.latency.toFixed(0) }} ms</div>
              </v-card-text>
            </v-card>
          </v-col>
          <v-col cols="12" md="3">
            <v-card class="summary-card">
              <v-card-text>
                <div class="summary-label">Samples / skipped</div>
                <div class="summary-value">{{ resultSummary.samples }} / {{ resultSummary.skipped }}</div>
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>

        <v-card class="mb-4">
          <v-card-title class="d-flex align-center">
            <v-icon icon="mdi-chart-bar" class="mr-2" />
            Comparaison des Stratégies
            <v-spacer />
            <v-btn
              v-if="comparisonRows.length > 0"
              variant="text"
              size="small"
              prepend-icon="mdi-download"
              @click="exportResults"
            >
              Exporter
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-alert
              v-if="!store.experimentResults.comparison"
              type="info"
              variant="tonal"
            >
              Lance un benchmark pour comparer le rappel, le classement et la latence des stratégies de recherche.
            </v-alert>
            <v-chart
              v-else
              class="chart-container"
              :option="comparisonChart"
              autoresize
            />
          </v-card-text>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>
            <v-icon icon="mdi-database-clock" class="mr-2" />
            Historique persiste
          </v-card-title>
          <v-card-text>
            <v-list v-if="experimentHistory.length > 0" density="compact">
              <v-list-item
                v-for="run in experimentHistory"
                :key="run.run_id"
                @click="openRun(run.run_id)"
              >
                <v-list-item-title>{{ run.dataset_name }} · {{ run.best_strategy || '-' }}</v-list-item-title>
                <v-list-item-subtitle>
                  {{ new Date(run.created_at).toLocaleString() }} · recall={{ (run.summary_metrics?.avg_recall_at_k || 0).toFixed(3) }}
                </v-list-item-subtitle>
              </v-list-item>
            </v-list>
            <div v-else class="text-center text-medium-emphasis pa-4">
              Aucun historique persiste
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row v-if="comparisonRows.length > 0" class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>Résultats Détaillés par Stratégie</v-card-title>
          <v-card-text>
            <v-table>
              <thead>
                <tr>
                  <th>Stratégie</th>
                  <th>Recall@K</th>
                  <th>MRR</th>
                  <th>nDCG@K</th>
                  <th>Latence (ms)</th>
                  <th>Candidats moyens</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in comparisonRows"
                  :key="row.strategy"
                  class="cursor-pointer"
                  @click="store.experimentResults.run_id && openRun(store.experimentResults.run_id)"
                >
                  <td class="font-weight-bold">{{ row.strategy }}</td>
                  <td>{{ (row.mean_recall_at_k || 0).toFixed(3) }}</td>
                  <td>{{ (row.mean_mrr || 0).toFixed(3) }}</td>
                  <td>{{ (row.mean_ndcg_at_k || 0).toFixed(3) }}</td>
                  <td>{{ (row.mean_latency_ms || 0).toFixed(0) }}</td>
                  <td>{{ (row.mean_candidate_count || 0).toFixed(0) }}</td>
                </tr>
              </tbody>
            </v-table>
            <v-alert v-if="store.experimentResults.run_id" type="info" variant="tonal" class="mt-4">
              run_id={{ store.experimentResults.run_id }}
              · semantic_top_k_internal={{ comparisonRows.find((row) => row.strategy === 'hybrid')?.rows?.[0]?.semantic_top_k_internal || '-' }}
              · skipped_too_long_queries={{ store.experimentResults.skipped_too_long_queries || 0 }}
            </v-alert>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.experiments-view {
  padding-bottom: 32px;
}

.cursor-pointer {
  cursor: pointer;
}

.experiments-alert {
  max-width: 980px;
}

.config-card {
  /* no sticky */
}

.logs-card {
  max-height: 260px;
  overflow-y: auto;
}

.summary-card {
  height: 100%;
}

.summary-label {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: rgba(var(--v-theme-on-surface), 0.62);
}

.summary-value {
  margin-top: 8px;
  font-size: 1.15rem;
  font-weight: 700;
}

@media (max-width: 1279px) {
  .config-card {
    position: static;
  }
}
</style>
