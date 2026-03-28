<script setup>
import { ref, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const drawer = ref(true)
const rail = ref(false)
const darkMode = ref(false)

onMounted(() => {
  store.fetchHealth()
})
</script>

<template>
  <v-app :theme="darkMode ? 'dark' : 'light'">
    <v-navigation-drawer
      v-model="drawer"
      :rail="rail"
      permanent
      color="primary"
    >
      <v-list-item
        :prepend-avatar="rail ? undefined : undefined"
        prepend-icon="mdi-flask"
        title="Docs Regex"
        nav
        class="my-2"
      >
        <template v-slot:append>
          <v-btn
            :icon="rail ? 'mdi-chevron-right' : 'mdi-chevron-left'"
            variant="text"
            @click="rail = !rail"
          />
        </template>
      </v-list-item>

      <v-divider />

      <v-list density="compact" nav>
        <v-list-item
          v-for="item in [
            { title: 'Dashboard', icon: 'mdi-view-dashboard', to: '/' },
            { title: 'Documents', icon: 'mdi-file-document', to: '/documents' },
            { title: 'Recherche', icon: 'mdi-magnify', to: '/search' },
            { title: 'Détection', icon: 'mdi-alert-circle', to: '/detection' },
            { title: 'Analyse LLM', icon: 'mdi-robot', to: '/llm' },
            { title: 'Compare 2 Docs', icon: 'mdi-file-compare', to: '/compare' },
            { title: 'Expériences', icon: 'mdi-flask', to: '/experiments' },
            { title: 'Paramètres', icon: 'mdi-cog', to: '/settings' },
          ]"
          :key="item.title"
          :to="item.to"
          :prepend-icon="item.icon"
          :title="item.title"
          color="white"
          rounded="lg"
        />
      </v-list>

      <template v-slot:append>
        <v-list density="compact" nav>
          <v-list-item
            :prepend-icon="darkMode ? 'mdi-weather-night' : 'mdi-weather-sunny'"
            :title="darkMode ? 'Mode clair' : 'Mode sombre'"
            @click="darkMode = !darkMode"
            color="white"
            rounded="lg"
          />
        </v-list>
      </template>
    </v-navigation-drawer>

    <v-app-bar flat color="surface" class="border-b">
      <v-app-bar-title class="text-h6">
        <v-icon icon="mdi-flask-outline" class="mr-2" />
        Docs Regex - Détection d'Incohérences Documentaires
      </v-app-bar-title>
      <v-spacer />
      <v-chip
        :color="store.isHealthy ? 'success' : 'error'"
        :prepend-icon="store.isHealthy ? 'mdi-check-circle' : 'mdi-alert-circle'"
        class="mr-4"
      >
        {{ store.health?.status || 'Unknown' }}
      </v-chip>
      <v-btn icon="mdi-refresh" @click="store.fetchHealth" />
    </v-app-bar>

    <v-main>
      <v-container fluid class="pa-6">
        <router-view />
      </v-container>
    </v-main>

    <v-snackbar
      v-model="store.error"
      color="error"
      timeout="5000"
    >
      {{ store.error }}
      <template v-slot:actions>
        <v-btn variant="text" @click="store.error = null">
          Fermer
        </v-btn>
      </template>
    </v-snackbar>
  </v-app>
</template>

<style scoped>
.border-b {
  border-bottom: 1px solid rgba(0, 0, 0, 0.12) !important;
}
</style>
