<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import MarkdownSurface from '@/components/MarkdownSurface.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()

const selectedStrategy = ref('')
const selectedSampleId = ref('')

onMounted(async () => {
  await store.fetchExperimentRun(route.params.runId)
})

const run = computed(() => store.currentExperimentRun)
const reports = computed(() => run.value?.result?.comparison?.reports || {})
const strategyOptions = computed(() => Object.keys(reports.value))

watch(strategyOptions, (options) => {
  if (!selectedStrategy.value && options.length > 0) {
    selectedStrategy.value = options[0]
  }
})

const activeStrategy = computed(() => reports.value[selectedStrategy.value] || null)
const sampleRows = computed(() => activeStrategy.value?.rows || [])

watch(sampleRows, (rows) => {
  if (!rows.some((row) => row.sample_id === selectedSampleId.value)) {
    selectedSampleId.value = rows[0]?.sample_id || ''
  }
}, { immediate: true })

const selectedSample = computed(() => sampleRows.value.find((row) => row.sample_id === selectedSampleId.value) || null)

function truncateText(value, limit = 220) {
  if (!value) return '-'
  return value.length > limit ? `${value.slice(0, limit)}...` : value
}

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

function openSampleReader(sampleId) {
  if (!selectedStrategy.value || !sampleId) return
  router.push({
    name: 'experiment-sample-reader',
    params: {
      runId: route.params.runId,
      strategy: selectedStrategy.value,
      sampleId,
    },
  })
}
</script>

<template>
  <div>
    <v-row class="mb-6">
      <v-col cols="12">
        <div class="d-flex align-center mb-3">
          <v-btn variant="text" prepend-icon="mdi-arrow-left" @click="router.push({ name: 'experiments' })">
            Retour
          </v-btn>
        </div>
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-chart-box-outline" class="mr-2" />
          Detail d'experience
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Drill-down complet d'une run: exercice pose, gold attendu, passages recuperes et classement final.
        </p>
      </v-col>
    </v-row>

    <v-alert v-if="!run" type="info" variant="tonal">
      Chargement de la run...
    </v-alert>

    <template v-else>
      <v-row class="mb-4">
        <v-col cols="12" md="3">
          <v-card>
            <v-card-text>
              <div class="text-overline">Run</div>
              <div class="text-body-1 font-weight-bold text-break">{{ run.run_id }}</div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="12" md="3">
          <v-card>
            <v-card-text>
              <div class="text-overline">Dataset</div>
              <div class="text-body-1 font-weight-bold">{{ run.dataset_name }}</div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="12" md="3">
          <v-card>
            <v-card-text>
              <div class="text-overline">Best</div>
              <div class="text-body-1 font-weight-bold">{{ run.best_strategy || '-' }}</div>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="12" md="3">
          <v-card>
            <v-card-text>
              <div class="text-overline">Samples</div>
              <div class="text-body-1 font-weight-bold">{{ run.samples_count }}</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mb-4">
        <v-col cols="12" md="4">
          <v-card class="h-100">
            <v-card-title>Configuration</v-card-title>
            <v-card-text>
              <pre class="config-block">{{ JSON.stringify(run.config, null, 2) }}</pre>
            </v-card-text>
          </v-card>
        </v-col>
        <v-col cols="12" md="8">
          <v-card class="h-100">
            <v-card-title>Strategie</v-card-title>
            <v-card-text>
              <v-row>
                <v-col cols="12" md="6">
                  <v-select
                    v-model="selectedStrategy"
                    :items="strategyOptions"
                    label="Strategie"
                    variant="outlined"
                    density="comfortable"
                  />
                </v-col>
                <v-col cols="12" md="6">
                  <v-select
                    v-model="selectedSampleId"
                    :items="sampleRows.map((row) => ({ title: row.sample_id, value: row.sample_id }))"
                    label="Sample"
                    variant="outlined"
                    density="comfortable"
                  />
                </v-col>
              </v-row>

              <v-row v-if="activeStrategy">
                <v-col cols="12" md="3">
                  <v-card variant="tonal" color="primary">
                    <v-card-text>Recall {{ (activeStrategy.mean_recall_at_k || 0).toFixed(3) }}</v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="12" md="3">
                  <v-card variant="tonal" color="info">
                    <v-card-text>MRR {{ (activeStrategy.mean_mrr || 0).toFixed(3) }}</v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="12" md="3">
                  <v-card variant="tonal" color="success">
                    <v-card-text>nDCG {{ (activeStrategy.mean_ndcg_at_k || 0).toFixed(3) }}</v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="12" md="3">
                  <v-card variant="tonal" color="warning">
                    <v-card-text>Latence {{ (activeStrategy.mean_latency_ms || 0).toFixed(1) }}ms</v-card-text>
                  </v-card>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mb-4">
        <v-col cols="12" md="5">
          <v-card class="h-100">
            <v-card-title>Samples de la strategie</v-card-title>
            <v-card-text class="sample-list">
              <v-list lines="three" density="compact">
                <v-list-item
                  v-for="row in sampleRows"
                  :key="row.sample_id"
                  :active="row.sample_id === selectedSampleId"
                  rounded="lg"
                  @click="selectedSampleId = row.sample_id"
                >
                  <v-list-item-title class="font-weight-medium">
                    {{ row.sample_id }}
                  </v-list-item-title>
                  <v-list-item-subtitle>
                    Recall {{ (row.recall_at_k || 0).toFixed(3) }} | MRR {{ (row.mrr || 0).toFixed(3) }} |
                    Gold {{ row.gold_present ? 'present' : 'missing' }} | Rank {{ row.best_relevant_rank || '-' }}
                  </v-list-item-subtitle>
                  <v-list-item-subtitle class="text-wrap">
                    {{ truncateText(row.query, 150) }}
                  </v-list-item-subtitle>
                </v-list-item>
              </v-list>
            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" md="7">
          <v-card v-if="selectedSample" class="h-100">
            <v-card-title>Lecture du sample</v-card-title>
            <v-card-text>
              <div class="detail-block">
                <div class="text-overline">Question / probleme pose</div>
                <MarkdownSurface :source="selectedSample.query" />
              </div>

              <div class="mb-4">
                <v-btn
                  color="primary"
                  variant="flat"
                  prepend-icon="mdi-book-open-page-variant"
                  @click="openSampleReader(selectedSample.sample_id)"
                >
                  Ouvrir la lecture detaillee
                </v-btn>
              </div>

              <div class="detail-grid">
                <div class="metric-pill">
                  <span>Recall</span>
                  <strong>{{ (selectedSample.recall_at_k || 0).toFixed(3) }}</strong>
                </div>
                <div class="metric-pill">
                  <span>MRR</span>
                  <strong>{{ (selectedSample.mrr || 0).toFixed(3) }}</strong>
                </div>
                <div class="metric-pill">
                  <span>nDCG</span>
                  <strong>{{ (selectedSample.ndcg_at_k || 0).toFixed(3) }}</strong>
                </div>
                <div class="metric-pill">
                  <span>Gold best rank</span>
                  <strong>{{ selectedSample.best_relevant_rank || '-' }}</strong>
                </div>
                <div class="metric-pill">
                  <span>Latency</span>
                  <strong>{{ (selectedSample.latency_ms || 0).toFixed(1) }} ms</strong>
                </div>
                <div class="metric-pill">
                  <span>Candidates</span>
                  <strong>{{ selectedSample.candidate_count || 0 }}</strong>
                </div>
              </div>

              <v-alert
                v-if="selectedSample.error"
                type="warning"
                variant="tonal"
                class="mb-4"
              >
                {{ selectedSample.error }}
              </v-alert>

              <v-expansion-panels variant="accordion">
                <v-expansion-panel>
                  <v-expansion-panel-title>Contexte du sample</v-expansion-panel-title>
                  <v-expansion-panel-text>
                    <pre class="config-block">{{ formatJson(selectedSample.sample_metadata) }}</pre>
                  </v-expansion-panel-text>
                </v-expansion-panel>

                <v-expansion-panel>
                  <v-expansion-panel-title>Gold attendu</v-expansion-panel-title>
                  <v-expansion-panel-text>
                    <div
                      v-for="item in selectedSample.relevant_items || []"
                      :key="item.id"
                      class="evidence-card gold-card"
                    >
                      <div class="evidence-head">
                        <strong>{{ item.id }}</strong>
                        <span>relevance {{ (item.relevance || 0).toFixed(3) }}</span>
                      </div>
                      <MarkdownSurface :source="item.text" empty-label="Aucun texte gold" />
                      <pre class="config-block metadata-block">{{ formatJson(item.metadata) }}</pre>
                    </div>
                  </v-expansion-panel-text>
                </v-expansion-panel>

                <v-expansion-panel>
                  <v-expansion-panel-title>Reponses de la strategie</v-expansion-panel-title>
                  <v-expansion-panel-text>
                    <div
                      v-for="item in selectedSample.retrieved_items || []"
                      :key="`${selectedSample.sample_id}-${item.id}-${item.rank}`"
                      class="evidence-card"
                      :class="{ 'gold-card': item.is_relevant }"
                    >
                      <div class="evidence-head">
                        <strong>#{{ item.rank }} {{ item.id }}</strong>
                        <span>score {{ (item.score || 0).toFixed(6) }}</span>
                      </div>
                      <div class="text-caption mb-2">
                        {{ item.is_relevant ? 'Gold retrouve' : 'Non gold' }}
                      </div>
                      <MarkdownSurface :source="item.text" empty-label="Aucun texte retourne" />
                      <pre class="config-block metadata-block">{{ formatJson(item.metadata) }}</pre>
                    </div>
                  </v-expansion-panel-text>
                </v-expansion-panel>
              </v-expansion-panels>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </div>
</template>

<style scoped>
.config-block {
  white-space: pre-wrap;
  word-break: break-word;
}

.sample-list {
  max-height: 70vh;
  overflow: auto;
}

.detail-block {
  margin-bottom: 16px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.metric-pill {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px;
  padding: 12px;
}

.metric-pill span {
  display: block;
  font-size: 0.75rem;
  opacity: 0.7;
}

.evidence-card {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  padding: 14px;
  margin-bottom: 12px;
}

.gold-card {
  border-color: rgba(var(--v-theme-success), 0.6);
  background: rgba(var(--v-theme-success), 0.06);
}

.evidence-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.evidence-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.metadata-block {
  margin-top: 10px;
}
</style>
