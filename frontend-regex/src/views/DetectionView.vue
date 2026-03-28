<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const selectedDocId = ref(null)
const claims = ref([''])
const runDetection = ref(false)

onMounted(() => {
  store.fetchDocuments()
})

const severityColors = {
  low: 'success',
  medium: 'warning',
  high: 'error',
  critical: 'error',
}

const severityIcons = {
  low: 'mdi-check-circle',
  medium: 'mdi-alert',
  high: 'mdi-alert-circle',
  critical: 'mdi-close-circle',
}

async function runDetectionPipeline() {
  const validClaims = claims.value.filter(c => c.trim())
  if (!selectedDocId.value || validClaims.length === 0) return
  
  runDetection.value = true
  try {
    await store.detect(selectedDocId.value, validClaims)
  } finally {
    runDetection.value = false
  }
}

function addClaim() {
  claims.value.push('')
}

function removeClaim(index) {
  claims.value.splice(index, 1)
}

const confusionMatrix = computed(() => {
  const d = store.detectionResults
  const tp = d.filter(r => r.gold && r.predicted).length
  const fp = d.filter(r => !r.gold && r.predicted).length
  const tn = d.filter(r => !r.gold && !r.predicted).length
  const fn = d.filter(r => r.gold && !r.predicted).length
  return { tp, fp, tn, fn }
})

const confMatrixChart = computed(() => ({
  tooltip: {},
  xAxis: { type: 'category', data: ['Prédit: Incohérent', 'Prédit: Cohérent'] },
  yAxis: { type: 'category', data: ['Réel: Incohérent', 'Réel: Cohérent'] },
  series: [{
    type: 'heatmap',
    data: [
      [0, 0, confusionMatrix.value.tp],
      [1, 0, confusionMatrix.value.fp],
      [0, 1, confusionMatrix.value.fn],
      [1, 1, confusionMatrix.value.tn],
    ],
    label: { show: true },
  }],
  visualMap: {
    min: 0,
    max: Math.max(confusionMatrix.value.tp, confusionMatrix.value.fp, confusionMatrix.value.fn, confusionMatrix.value.tn) || 1,
    inRange: { color: ['#FFEBEE', '#FF5252'] },
  },
}))
</script>

<template>
  <div>
    <v-row class="mb-6">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-alert-circle" class="mr-2" />
          Détection d'Incohérences
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Analysez les documents pour détecter les incohérences
        </p>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            <v-icon icon="mdi-file-search" class="mr-2" />
            Sélection du Document
          </v-card-title>
          <v-card-text>
            <v-select
              v-model="selectedDocId"
              :items="store.documents.filter(d => d.status === 'completed')"
              item-title="filename"
              item-value="document_id"
              label="Document à analyser"
              variant="outlined"
              :disabled="store.loading"
            />

            <v-divider class="my-4" />

            <h4 class="text-h6 mb-4">Claims à vérifier</h4>
            
            <div
              v-for="(claim, index) in claims"
              :key="index"
              class="d-flex align-center mb-2"
            >
              <v-text-field
                v-model="claims[index]"
                :label="`Claim ${index + 1}`"
                variant="outlined"
                density="compact"
                hide-details
                class="flex-grow-1"
              />
              <v-btn
                v-if="claims.length > 1"
                icon="mdi-close"
                variant="text"
                size="small"
                class="ml-2"
                @click="removeClaim(index)"
              />
            </div>

            <v-btn
              variant="text"
              size="small"
              prepend-icon="mdi-plus"
              @click="addClaim"
              class="mt-2"
            >
              Ajouter un claim
            </v-btn>

            <v-divider class="my-4" />

            <v-btn
              color="primary"
              size="large"
              block
              :loading="runDetection"
              :disabled="!selectedDocId || claims.filter(c => c.trim()).length === 0"
              @click="runDetectionPipeline"
            >
              <v-icon icon="mdi-radar" class="mr-2" />
              Lancer la détection
            </v-btn>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            <v-icon icon="mdi-results" class="mr-2" />
            Résultats
          </v-card-title>
          <v-card-text>
            <v-alert
              v-if="store.detectionResults.length === 0"
              type="info"
              variant="tonal"
            >
              Lancez une détection pour voir les résultats
            </v-alert>

            <v-list v-else>
              <v-list-item
                v-for="(result, index) in store.detectionResults"
                :key="index"
                class="mb-2"
              >
                <template v-slot:prepend>
                  <v-icon
                    :icon="severityIcons[result.severity] || 'mdi-help-circle'"
                    :color="severityColors[result.severity] || 'grey'"
                    size="large"
                  />
                </template>

                <v-list-item-title class="font-weight-bold">
                  {{ result.claim }}
                </v-list-item-title>

                <v-list-item-subtitle>
                  {{ result.rationale }}
                </v-list-item-subtitle>

                <template v-slot:append>
                  <v-chip
                    :color="result.verdict === 'inconsistent' ? 'error' : result.verdict === 'consistent' ? 'success' : 'warning'"
                    size="small"
                  >
                    {{ result.verdict }}
                  </v-chip>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row v-if="store.detectionResults.length > 0" class="mt-4">
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Matrice de Confusion</v-card-title>
          <v-card-text>
            <div class="conf-matrix">
              <div></div>
              <div class="label">Incohérent</div>
              <div class="label">Cohérent</div>
              <div class="label">Incohérent</div>
              <div class="cell tp">{{ confusionMatrix.tp }}</div>
              <div class="cell fn">{{ confusionMatrix.fn }}</div>
              <div class="label">Cohérent</div>
              <div class="cell fp">{{ confusionMatrix.fp }}</div>
              <div class="cell tn">{{ confusionMatrix.tn }}</div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Statistiques</v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item>
                <v-list-item-title>Nombre de claims</v-list-item-title>
                <template v-slot:append>
                  <span class="font-weight-bold">{{ store.detectionResults.length }}</span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Incohérences détectées</v-list-item-title>
                <template v-slot:append>
                  <span class="font-weight-bold text-error">
                    {{ store.detectionResults.filter(r => r.verdict === 'inconsistent').length }}
                  </span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Cohérent</v-list-item-title>
                <template v-slot:append>
                  <span class="font-weight-bold text-success">
                    {{ store.detectionResults.filter(r => r.verdict === 'consistent').length }}
                  </span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Incertains</v-list-item-title>
                <template v-slot:append>
                  <span class="font-weight-bold text-warning">
                    {{ store.detectionResults.filter(r => r.verdict === 'uncertain').length }}
                  </span>
                </template>
              </v-list-item>
            </v-list>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.conf-matrix {
  display: grid;
  grid-template-columns: auto 1fr 1fr;
  gap: 8px;
  max-width: 400px;
  margin: 0 auto;
}

.conf-matrix .label {
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
}

.conf-matrix .cell {
  padding: 16px;
  text-align: center;
  border-radius: 8px;
  font-weight: bold;
  font-size: 18px;
}

.conf-matrix .cell.tp { background: #E8F5E9; color: #2E7D32; }
.conf-matrix .cell.fp { background: #FFEBEE; color: #C62828; }
.conf-matrix .cell.tn { background: #E3F2FD; color: #1565C0; }
.conf-matrix .cell.fn { background: #FFF3E0; color: #EF6C00; }
</style>
