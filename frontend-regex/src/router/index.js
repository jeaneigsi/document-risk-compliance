import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: 'Dashboard', icon: 'mdi-view-dashboard' },
  },
  {
    path: '/documents',
    name: 'documents',
    component: () => import('@/views/DocumentsView.vue'),
    meta: { title: 'Documents', icon: 'mdi-file-document' },
  },
  {
    path: '/search',
    name: 'search',
    component: () => import('@/views/SearchView.vue'),
    meta: { title: 'Recherche', icon: 'mdi-magnify' },
  },
  {
    path: '/experiments',
    name: 'experiments',
    component: () => import('@/views/ExperimentsView.vue'),
    meta: { title: 'Expériences', icon: 'mdi-flask' },
  },
  {
    path: '/experiments/:runId',
    name: 'experiment-run',
    component: () => import('@/views/ExperimentRunDetailView.vue'),
    meta: { title: 'Détail expérience', icon: 'mdi-chart-box-outline' },
  },
  {
    path: '/experiments/:runId/:strategy/:sampleId',
    name: 'experiment-sample-reader',
    component: () => import('@/views/ExperimentSampleReaderView.vue'),
    meta: { title: 'Lecture sample', icon: 'mdi-book-open-page-variant' },
  },
  {
    path: '/detection',
    name: 'detection',
    component: () => import('@/views/DetectionView.vue'),
    meta: { title: 'Détection', icon: 'mdi-alert-circle' },
  },
  {
    path: '/llm',
    name: 'llm',
    component: () => import('@/views/LLMView.vue'),
    meta: { title: 'Analyse LLM', icon: 'mdi-robot' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: 'Paramètres', icon: 'mdi-cog' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

export default router
