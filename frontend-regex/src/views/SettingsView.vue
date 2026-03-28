<script setup>
import { ref } from 'vue'

const apiUrl = ref(localStorage.getItem('apiUrl') || 'http://localhost:8000/api/v1')
const darkMode = ref(localStorage.getItem('darkMode') === 'true')
const autoRefresh = ref(localStorage.getItem('autoRefresh') === 'true')
const refreshInterval = ref(parseInt(localStorage.getItem('refreshInterval') || '30'))

const defaultConfig = {
  apiUrl: 'http://localhost:8000/api/v1',
  defaultSearchStrategy: 'hybrid',
  defaultTopK: 10,
  maxFileSize: 50 * 1024 * 1024,
}

function saveSettings() {
  localStorage.setItem('apiUrl', apiUrl.value)
  localStorage.setItem('darkMode', darkMode.value)
  localStorage.setItem('autoRefresh', autoRefresh.value)
  localStorage.setItem('refreshInterval', refreshInterval.value.toString())
  
  window.location.reload()
}

function resetSettings() {
  apiUrl.value = defaultConfig.apiUrl
  darkMode.value = false
  autoRefresh.value = false
  refreshInterval.value = 30
  localStorage.clear()
  window.location.reload()
}
</script>

<template>
  <div>
    <v-row class="mb-6">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-cog" class="mr-2" />
          Paramètres
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Configuration de l'application
        </p>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            <v-icon icon="mdi-api" class="mr-2" />
            Connexion API
          </v-card-title>
          <v-card-text>
            <v-text-field
              v-model="apiUrl"
              label="URL de l'API"
              variant="outlined"
              placeholder="http://localhost:8000/api/v1"
            />
            
            <v-btn
              color="primary"
              :href="apiUrl + '/docs'"
              target="_blank"
              variant="tonal"
            >
              <v-icon icon="mdi-open-in-new" class="mr-2" />
              Documentation API (Swagger)
            </v-btn>
          </v-card-text>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>
            <v-icon icon="mdi-palette" class="mr-2" />
            Apparence
          </v-card-title>
          <v-card-text>
            <v-switch
              v-model="darkMode"
              label="Mode sombre"
              color="primary"
            />
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>
            <v-icon icon="mdi-refresh" class="mr-2" />
            Comportement
          </v-card-title>
          <v-card-text>
            <v-switch
              v-model="autoRefresh"
              label="Rafraîchissement automatique"
              color="primary"
            />
            
            <v-slider
              v-model="refreshInterval"
              :disabled="!autoRefresh"
              label="Intervalle de rafraîchissement (secondes)"
              :min="5"
              :max="120"
              :step="5"
              thumb-label
            />
          </v-card-text>
        </v-card>

        <v-card class="mt-4">
          <v-card-title>
            <v-icon icon="mdi-information" class="mr-2" />
            À propos
          </v-card-title>
          <v-card-text>
            <v-list>
              <v-list-item>
                <v-list-item-title>Version</v-list-item-title>
                <template v-slot:append>
                  <span class="font-weight-bold">1.0.0</span>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Framework</v-list-item-title>
                <template v-slot:append>
                  <v-chip size="small">Vue 3 + Vuetify</v-chip>
                </template>
              </v-list-item>
              <v-list-item>
                <v-list-item-title>Backend</v-list-item-title>
                <template v-slot:append>
                  <v-chip size="small">FastAPI</v-chip>
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
          <v-card-title>Actions</v-card-title>
          <v-card-text class="d-flex gap-4">
            <v-btn color="primary" @click="saveSettings">
              <v-icon icon="mdi-content-save" class="mr-2" />
              Enregistrer
            </v-btn>
            <v-btn color="error" variant="outlined" @click="resetSettings">
              <v-icon icon="mdi-restore" class="mr-2" />
              Réinitialiser
            </v-btn>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>
