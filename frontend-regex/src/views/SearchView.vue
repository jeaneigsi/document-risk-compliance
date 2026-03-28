<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const query = ref('')
const strategy = ref('hybrid')
const topK = ref(10)
const indexName = ref('default')
const searchHistory = ref([])

const strategies = [
  { title: 'Hybride (70% sémantique + 30% lexical)', value: 'hybrid' },
  { title: 'Sémantique (NextPlaid)', value: 'semantic' },
  { title: 'Lexical (Cursor-like)', value: 'lexical' },
  { title: 'RG (full scan regex)', value: 'rg' },
]

const chartOption = computed(() => ({
  tooltip: { trigger: 'item' },
  legend: { top: '5%', left: 'center' },
  series: [
    {
      name: 'Score',
      type: 'pie',
      radius: ['40%', '70%'],
      avoidLabelOverlap: false,
      itemStyle: {
        borderRadius: 10,
        borderColor: '#fff',
        borderWidth: 2,
      },
      label: { show: false },
      emphasis: {
        label: { show: true, fontSize: 14, fontWeight: 'bold' },
      },
      data: store.searchResults.map((r, i) => ({
        value: r.score || (1 - i * 0.1).toFixed(2),
        name: r.id?.substring(0, 20) || `Result ${i + 1}`,
      })),
    },
  ],
}))

async function doSearch() {
  if (!query.value.trim()) return
  
  searchHistory.value.unshift({
    query: query.value,
    strategy: strategy.value,
    timestamp: new Date(),
  })
  
  await store.search(query.value, strategy.value, topK.value, indexName.value)
}

function clearResults() {
  store.searchResults = []
}
</script>

<template>
  <div>
    <v-row class="mb-6">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-magnify" class="mr-2" />
          Recherche
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Recherche sémantique et lexicale dans les documents indexés
        </p>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="8">
        <v-card class="mb-4">
          <v-card-text>
            <v-text-field
              v-model="query"
              label="Requête de recherche"
              placeholder="Entrez votre requête..."
              prepend-inner-icon="mdi-magnify"
              variant="outlined"
              clearable
              @keyup.enter="doSearch"
            />

            <v-row>
              <v-col cols="12" md="4">
                <v-select
                  v-model="strategy"
                  :items="strategies"
                  label="Stratégie"
                  variant="outlined"
                />
              </v-col>
              <v-col cols="12" md="4">
                <v-select
                  v-model="indexName"
                  :items="['default', 'documents', 'evidence']"
                  label="Index"
                  variant="outlined"
                />
              </v-col>
              <v-col cols="12" md="4">
                <v-slider
                  v-model="topK"
                  label="Top K"
                  :min="1"
                  :max="50"
                  :step="1"
                  thumb-label
                />
              </v-col>
            </v-row>

            <v-btn
              color="primary"
              size="large"
              :loading="store.loading"
              @click="doSearch"
            >
              <v-icon icon="mdi-magnify" class="mr-2" />
              Rechercher
            </v-btn>
          </v-card-text>
        </v-card>

        <v-card v-if="store.searchResults.length > 0">
          <v-card-title class="d-flex align-center">
            <v-icon icon="mdi-format-list-numbered" class="mr-2" />
            Résultats ({{ store.searchResults.length }})
            <v-spacer />
            <v-btn variant="text" size="small" @click="clearResults">
              Effacer
            </v-btn>
          </v-card-title>
          <v-list>
            <v-list-item
              v-for="(result, index) in store.searchResults"
              :key="index"
              class="mb-2"
            >
              <template v-slot:prepend>
                <v-avatar color="primary" size="small">
                  {{ index + 1 }}
                </v-avatar>
              </template>
              
              <v-list-item-title class="font-weight-bold">
                {{ result.id || result.title || 'Document' }}
              </v-list-item-title>
              
              <v-list-item-subtitle>
                {{ result.content || result.text || result.excerpt || '...' }}
              </v-list-item-subtitle>
              
              <template v-slot:append>
                <v-chip color="success" size="small">
                  Score: {{ (result.score || 0).toFixed(3) }}
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
        </v-card>

        <v-alert v-else-if="!store.loading" type="info" class="mt-4">
          Entrez une requête et cliquez sur Rechercher pour commencer
        </v-alert>
      </v-col>

      <v-col cols="12" md="4">
        <v-card class="mb-4">
          <v-card-title>
            <v-icon icon="mdi-chart-pie" class="mr-2" />
            Distribution des Scores
          </v-card-title>
          <v-card-text>
            <v-chart
              v-if="store.searchResults.length > 0"
              class="chart-container"
              :option="chartOption"
              autoresize
            />
            <div v-else class="text-center pa-8 text-medium-emphasis">
              <v-icon icon="mdi-chart-box-outline" size="48" />
              <p class="mt-2">Aucune donnée</p>
            </div>
          </v-card-text>
        </v-card>

        <v-card>
          <v-card-title>
            <v-icon icon="mdi-history" class="mr-2" />
            Historique
          </v-card-title>
          <v-list v-if="searchHistory.length > 0" density="compact">
            <v-list-item
              v-for="(h, i) in searchHistory.slice(0, 10)"
              :key="i"
              @click="query = h.query; strategy = h.strategy"
            >
              <v-list-item-title>{{ h.query }}</v-list-item-title>
              <v-list-item-subtitle>
                {{ h.strategy }} - {{ h.timestamp.toLocaleTimeString() }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-center text-medium-emphasis">
            Aucun historique
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>
