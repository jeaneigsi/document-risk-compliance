<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const router = useRouter()

onMounted(async () => {
  await Promise.all([
    store.fetchHealth(),
    store.fetchDocuments(),
    store.fetchExperimentHistory(),
    store.fetchExperimentHistorySummary(),
  ])
})

const stats = computed(() => [
  { title: 'Documents', value: store.documents.length, icon: 'mdi-file-document', color: 'primary' },
  { title: 'Recherches', value: store.searchResults.length, icon: 'mdi-magnify', color: 'info' },
  { title: 'Détections', value: store.detectionResults.length, icon: 'mdi-alert-circle', color: 'warning' },
  { title: 'Expériences', value: store.experimentHistorySummary?.total_runs || 0, icon: 'mdi-flask', color: 'success' },
])

const recentRuns = computed(() => store.experimentHistory.slice(0, 5))

const strategyTrendChart = computed(() => {
  const runs = [...recentRuns.value].reverse()
  if (runs.length === 0) return null
  const categories = runs.map((run) => new Date(run.created_at).toLocaleDateString())
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Recall', 'MRR', 'nDCG', 'Latence'] },
    xAxis: { type: 'category', data: categories },
    yAxis: [
      { type: 'value', name: 'Score', max: 1 },
      { type: 'value', name: 'Latence', max: Math.max(1000, ...runs.map((run) => run.summary_metrics?.avg_latency_ms || 0)) },
    ],
    series: [
      {
        name: 'Recall',
        type: 'line',
        smooth: true,
        data: runs.map((run) => run.summary_metrics?.avg_recall_at_k || 0),
      },
      {
        name: 'MRR',
        type: 'line',
        smooth: true,
        data: runs.map((run) => run.summary_metrics?.avg_mrr || 0),
      },
      {
        name: 'nDCG',
        type: 'line',
        smooth: true,
        data: runs.map((run) => run.summary_metrics?.avg_ndcg_at_k || 0),
      },
      {
        name: 'Latence',
        type: 'bar',
        yAxisIndex: 1,
        data: runs.map((run) => run.summary_metrics?.avg_latency_ms || 0),
      },
    ],
  }
})

function openRun(runId) {
  router.push({ name: 'experiment-run', params: { runId } })
}
</script>

<template>
  <div>
    <v-row class="mb-6">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-view-dashboard" class="mr-2" />
          Dashboard
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Vue d'ensemble connectee du systeme de detection, recherche et experimentation.
        </p>
      </v-col>
    </v-row>

    <v-row class="mb-6">
      <v-col v-for="stat in stats" :key="stat.title" cols="12" sm="6" md="3">
        <v-card :color="stat.color" variant="tonal">
          <v-card-text class="d-flex align-center">
            <v-avatar :color="stat.color" size="48" class="mr-4">
              <v-icon :icon="stat.icon" size="24" />
            </v-avatar>
            <div>
              <div class="text-h4 font-weight-bold">{{ stat.value }}</div>
              <div class="text-body-2">{{ stat.title }}</div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="8">
        <v-card>
          <v-card-title class="d-flex align-center">
            <v-icon icon="mdi-chart-timeline-variant" class="mr-2" />
            Historique des Experiments
            <v-spacer />
            <v-chip v-if="store.experimentHistorySummary?.best_recall_strategy" color="success" size="small">
              meilleur recall: {{ store.experimentHistorySummary.best_recall_strategy }}
            </v-chip>
          </v-card-title>
          <v-card-text>
            <v-chart v-if="strategyTrendChart" class="chart-container" :option="strategyTrendChart" autoresize />
            <v-alert v-else type="info" variant="tonal">
              Aucune experimentation persistée pour le moment.
            </v-alert>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="4">
        <v-card class="mb-4">
          <v-card-title>
            <v-icon icon="mdi-information" class="mr-2" />
            Etat des Services
          </v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item v-for="(service, name) in store.health?.components || {}" :key="name">
                <template #prepend>
                  <v-icon :icon="service === 'ok' ? 'mdi-check-circle' : 'mdi-alert-circle'" :color="service === 'ok' ? 'success' : 'error'" />
                </template>
                <v-list-item-title>{{ name }}</v-list-item-title>
                <template #append>
                  <v-chip :color="service === 'ok' ? 'success' : 'error'" size="small">{{ service }}</v-chip>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>

        <v-card>
          <v-card-title>
            <v-icon icon="mdi-lightning-bolt" class="mr-2" />
            Synthese Economique
          </v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item>
                <v-list-item-title>Recall moyen</v-list-item-title>
                <template #append>
                  <span class="font-weight-bold">{{ ((store.experimentHistorySummary?.avg_recall_at_k || 0) * 100).toFixed(1) }}%</span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Latence moyenne</v-list-item-title>
                <template #append>
                  <span class="font-weight-bold">{{ (store.experimentHistorySummary?.avg_latency_ms || 0).toFixed(0) }}ms</span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Derniere run</v-list-item-title>
                <template #append>
                  <span class="font-weight-bold">{{ store.experimentHistorySummary?.latest_run?.dataset_name || '-' }}</span>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mt-4">
      <v-col cols="12">
        <v-card>
          <v-card-title>
            <v-icon icon="mdi-history" class="mr-2" />
            Dernieres experimentations
          </v-card-title>
          <v-card-text>
            <v-table v-if="recentRuns.length > 0" hover>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Dataset</th>
                  <th>Split</th>
                  <th>Best</th>
                  <th>Recall</th>
                  <th>Latence</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="run in recentRuns" :key="run.run_id" class="cursor-pointer" @click="openRun(run.run_id)">
                  <td>{{ new Date(run.created_at).toLocaleString() }}</td>
                  <td>{{ run.dataset_name }}</td>
                  <td>{{ run.split }}</td>
                  <td>{{ run.best_strategy || '-' }}</td>
                  <td>{{ (run.summary_metrics?.avg_recall_at_k || 0).toFixed(3) }}</td>
                  <td>{{ (run.summary_metrics?.avg_latency_ms || 0).toFixed(0) }}ms</td>
                </tr>
              </tbody>
            </v-table>
            <v-alert v-else type="info" variant="tonal">
              Aucune run historique disponible.
            </v-alert>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.cursor-pointer {
  cursor: pointer;
}
</style>
