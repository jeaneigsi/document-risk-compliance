<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import MarkdownSurface from '@/components/MarkdownSurface.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()

onMounted(async () => {
  await store.fetchExperimentRun(route.params.runId)
})

const run = computed(() => store.currentExperimentRun)
const reports = computed(() => run.value?.result?.comparison?.reports || {})
const activeStrategy = computed(() => reports.value[route.params.strategy] || null)
const sample = computed(() => (
  activeStrategy.value?.rows || []
).find((row) => row.sample_id === route.params.sampleId) || null)

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2)
}
</script>

<template>
  <div class="sample-reader">
    <div class="reader-shell">
      <div class="reader-topbar">
        <v-btn variant="text" prepend-icon="mdi-arrow-left" @click="router.push({ name: 'experiment-run', params: { runId: route.params.runId } })">
          Retour au detail
        </v-btn>
        <div class="reader-meta">
          <span>{{ route.params.strategy }}</span>
          <span>{{ route.params.sampleId }}</span>
        </div>
      </div>

      <v-alert v-if="!sample" type="warning" variant="tonal">
        Sample introuvable dans cette run.
      </v-alert>

      <template v-else>
        <section class="reader-hero">
          <div>
            <div class="hero-kicker">Exercice du benchmark</div>
            <h1>{{ sample.sample_id }}</h1>
            <p>{{ sample.query }}</p>
          </div>
          <div class="hero-stats">
            <div>
              <span>Recall</span>
              <strong>{{ (sample.recall_at_k || 0).toFixed(3) }}</strong>
            </div>
            <div>
              <span>MRR</span>
              <strong>{{ (sample.mrr || 0).toFixed(3) }}</strong>
            </div>
            <div>
              <span>nDCG</span>
              <strong>{{ (sample.ndcg_at_k || 0).toFixed(3) }}</strong>
            </div>
            <div>
              <span>Best rank</span>
              <strong>{{ sample.best_relevant_rank || '-' }}</strong>
            </div>
          </div>
        </section>

        <section class="reader-section">
          <div class="section-head">
            <h2>Contexte du sample</h2>
          </div>
          <pre class="json-block">{{ formatJson(sample.sample_metadata) }}</pre>
        </section>

        <section class="reader-section">
          <div class="section-head">
            <h2>Gold attendu</h2>
            <span>{{ (sample.relevant_items || []).length }} passages</span>
          </div>
          <div class="reader-grid">
            <article v-for="item in sample.relevant_items || []" :key="item.id" class="reader-card gold">
              <header class="card-head">
                <strong>{{ item.id }}</strong>
                <span>relevance {{ (item.relevance || 0).toFixed(3) }}</span>
              </header>
              <MarkdownSurface :source="item.text" empty-label="Aucun texte gold" />
              <pre class="json-block">{{ formatJson(item.metadata) }}</pre>
            </article>
          </div>
        </section>

        <section class="reader-section">
          <div class="section-head">
            <h2>Passages recuperes</h2>
            <span>{{ (sample.retrieved_items || []).length }} reponses</span>
          </div>
          <div class="reader-grid">
            <article
              v-for="item in sample.retrieved_items || []"
              :key="`${sample.sample_id}-${item.id}-${item.rank}`"
              class="reader-card"
              :class="{ gold: item.is_relevant }"
            >
              <header class="card-head">
                <strong>#{{ item.rank }} {{ item.id }}</strong>
                <span>score {{ (item.score || 0).toFixed(6) }}</span>
              </header>
              <MarkdownSurface :source="item.text" empty-label="Aucun texte retourne" />
              <pre class="json-block">{{ formatJson(item.metadata) }}</pre>
            </article>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.sample-reader {
  min-height: 100%;
  padding: clamp(16px, 2vw, 28px);
  background:
    radial-gradient(circle at top right, rgba(var(--v-theme-primary), 0.12), transparent 28%),
    linear-gradient(180deg, rgba(var(--v-theme-surface), 1), rgba(var(--v-theme-surface-bright), 1));
}

.reader-shell {
  max-width: 1320px;
  margin: 0 auto;
}

.reader-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.reader-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.reader-meta span {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  border-radius: 999px;
  padding: 6px 12px;
}

.reader-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(280px, 0.9fr);
  gap: 18px;
  padding: clamp(18px, 2.2vw, 28px);
  border-radius: 28px;
  background: color-mix(in srgb, rgb(var(--v-theme-surface)) 90%, rgb(var(--v-theme-primary)) 10%);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.08);
  margin-bottom: 22px;
}

.hero-kicker {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.78rem;
  margin-bottom: 10px;
  opacity: 0.7;
}

.reader-hero h1 {
  font-size: clamp(1.5rem, 1.1rem + 1.3vw, 2.4rem);
  line-height: 1.05;
  margin-bottom: 12px;
}

.reader-hero p {
  max-width: 76ch;
  line-height: 1.65;
  opacity: 0.92;
}

.hero-stats {
  display: grid;
  gap: 12px;
  align-content: start;
}

.hero-stats > div {
  padding: 14px;
  border-radius: 18px;
  background: rgba(var(--v-theme-on-surface), 0.04);
}

.hero-stats span {
  display: block;
  opacity: 0.65;
  font-size: 0.78rem;
}

.hero-stats strong {
  display: block;
  font-size: 1.18rem;
  margin-top: 6px;
}

.reader-section {
  margin-bottom: 22px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.section-head h2 {
  font-size: 1.15rem;
}

.reader-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.reader-card {
  padding: 18px;
  border-radius: 22px;
  background: rgba(var(--v-theme-surface), 0.94);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.08);
}

.reader-card.gold {
  border-color: rgba(var(--v-theme-success), 0.35);
  background: color-mix(in srgb, rgb(var(--v-theme-surface)) 92%, rgb(var(--v-theme-success)) 8%);
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.json-block {
  white-space: pre-wrap;
  word-break: break-word;
  margin-top: 14px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(var(--v-theme-on-surface), 0.05);
  font-size: 0.82rem;
}

@media (max-width: 900px) {
  .reader-hero {
    grid-template-columns: 1fr;
  }
}
</style>
