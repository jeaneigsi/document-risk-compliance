<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import VuePdfEmbed from 'vue-pdf-embed'
import 'vue-pdf-embed/dist/styles/annotationLayer.css'
import 'vue-pdf-embed/dist/styles/textLayer.css'
import { documentsApi } from '@/services/api'

const props = defineProps({
  title: { type: String, default: '' },
  documentId: { type: String, default: '' },
  filename: { type: String, default: '' },
  page: { type: Number, default: 1 },
  totalPages: { type: Number, default: 0 },
  highlights: { type: Array, default: () => [] },
  viewerHeight: { type: [Number, String], default: 640 },
  allowExpand: { type: Boolean, default: false },
})

const emit = defineEmits(['update:page', 'expand'])

const zoom = ref(1)
const renderError = ref('')
const renderKey = ref(0)
const pageScrollRef = ref(null)
const viewportWidth = ref(0)

const pdfSource = computed(() => {
  if (!props.documentId) return null
  return documentsApi.fileUrl(props.documentId)
})

const viewerBodyHeight = computed(() =>
  typeof props.viewerHeight === 'number' ? `${props.viewerHeight}px` : props.viewerHeight
)

const renderWidth = computed(() => {
  const baseWidth = Math.max(280, Math.floor((viewportWidth.value || 0) - 4))
  return Math.max(280, Math.round(baseWidth * zoom.value))
})

watch(
  () => [props.documentId, props.page],
  () => {
    renderError.value = ''
  }
)

watch(
  () => props.documentId,
  () => {
    zoom.value = 1
    renderKey.value += 1
  }
)

let resizeObserver = null

function measureViewport() {
  const element = pageScrollRef.value
  if (!element) return
  viewportWidth.value = element.clientWidth - 2
}

onMounted(() => {
  measureViewport()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      measureViewport()
    })
    if (pageScrollRef.value) resizeObserver.observe(pageScrollRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
})

function setPage(nextPage) {
  if (!props.totalPages) return
  const clamped = Math.max(1, Math.min(props.totalPages, Number(nextPage || 1)))
  emit('update:page', clamped)
}

function zoomIn() {
  zoom.value = Math.min(2.8, Number((zoom.value + 0.2).toFixed(2)))
}

function zoomOut() {
  zoom.value = Math.max(0.6, Number((zoom.value - 0.2).toFixed(2)))
}

function resetZoom() {
  zoom.value = 1
}

function onRenderFailed(error) {
  renderError.value = error?.message || 'Le rendu PDF a échoué.'
}

function onLoadingFailed(error) {
  renderError.value = error?.message || 'Le document PDF n’a pas pu être chargé.'
}

function overlayStyle(item) {
  const box = item?.bbox_2d || {}
  const left = Number(box.x1 || 0) * 100
  const top = Number(box.y1 || 0) * 100
  const width = Math.max(0, Number(box.x2 || 0) - Number(box.x1 || 0)) * 100
  const height = Math.max(0, Number(box.y2 || 0) - Number(box.y1 || 0)) * 100
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${width}%`,
    height: `${height}%`,
    borderColor: item.color || '#f97316',
    backgroundColor: item.fill || 'rgba(249, 115, 22, 0.18)',
  }
}
</script>

<template>
  <v-card class="pdf-viewer-card">
    <v-card-title class="viewer-head">
      <div class="viewer-copy">
        <div class="viewer-title">{{ title }}</div>
        <div class="viewer-filename">{{ filename || 'Aucun document sélectionné' }}</div>
      </div>
      <v-spacer />
      <div v-if="documentId" class="viewer-controls">
        <div class="viewer-control-block">
          <v-btn icon="mdi-magnify-minus-outline" variant="text" size="small" @click="zoomOut" />
          <span class="viewer-zoom-badge">{{ Math.round(zoom * 100) }}%</span>
          <v-btn icon="mdi-magnify-plus-outline" variant="text" size="small" @click="zoomIn" />
          <v-btn icon="mdi-fit-to-page-outline" variant="text" size="small" @click="resetZoom" />
          <div class="viewer-control-divider" />
          <v-btn icon="mdi-chevron-left" variant="text" size="small" :disabled="page <= 1" @click="setPage(page - 1)" />
          <v-text-field
            :model-value="page"
            type="number"
            density="compact"
            hide-details
            variant="outlined"
            class="page-input"
            @update:model-value="setPage($event)"
          />
          <span class="viewer-page-count">/ {{ totalPages || '?' }}</span>
          <v-btn icon="mdi-chevron-right" variant="text" size="small" :disabled="page >= totalPages" @click="setPage(page + 1)" />
        </div>

        <v-btn
          v-if="allowExpand"
          icon="mdi-arrow-expand-all"
          variant="text"
          size="small"
          title="Vue détaillée"
          @click="emit('expand')"
        />
      </div>
    </v-card-title>

    <v-card-text class="viewer-body">
      <v-alert v-if="!documentId" type="info" variant="tonal">
        Sélectionne un document pour afficher le PDF.
      </v-alert>
      <v-alert v-else-if="renderError" type="error" variant="tonal">
        {{ renderError }}
      </v-alert>
      <div v-else class="page-stage">
        <div ref="pageScrollRef" class="page-scroll" :style="{ height: viewerBodyHeight }">
          <div class="page-shell">
            <div class="page-render">
              <VuePdfEmbed
                :key="`${renderKey}-${documentId}-${page}`"
                class="pdf-embed"
                :source="pdfSource"
                :page="page"
                :width="renderWidth"
                text-layer
                annotation-layer
                @loading-failed="onLoadingFailed"
                @rendering-failed="onRenderFailed"
              />
              <div class="overlay-layer">
                <div
                  v-for="item in highlights"
                  :key="item.id"
                  class="overlay-box"
                  :style="overlayStyle(item)"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </v-card-text>
  </v-card>
</template>

<style scoped>
.pdf-viewer-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 42.5rem;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.viewer-head {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.viewer-copy {
  min-width: 0;
}

.viewer-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}

.viewer-filename {
  margin-top: 0.2rem;
  max-width: 28rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.78rem;
  color: #64748b;
}

.viewer-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.viewer-control-block {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  padding: 0.18rem 0.3rem;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.viewer-control-divider {
  width: 1px;
  height: 1.4rem;
  margin: 0 0.1rem;
  background: rgba(148, 163, 184, 0.35);
}

.viewer-page-count {
  font-size: 0.75rem;
  color: #64748b;
}

.viewer-zoom-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 3.15rem;
  height: 1.85rem;
  padding: 0 0.65rem;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 0.74rem;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
}

.viewer-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.page-input {
  max-width: 5rem;
}

.page-stage {
  display: flex;
  flex: 1;
  min-height: 0;
  min-width: 0;
  width: 100%;
  max-width: 100%;
  border-radius: 1.25rem;
  background: linear-gradient(180deg, rgba(241, 245, 249, 0.96), rgba(226, 232, 240, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.35);
  overflow: hidden;
}

.page-scroll {
  flex: 1;
  overflow: auto;
  height: 100%;
  width: 100%;
  max-width: 100%;
  padding: 1.1rem 1.15rem 1.2rem;
  scrollbar-width: thin;
}

.page-shell {
  display: flex;
  justify-content: flex-start;
  align-items: flex-start;
  width: max-content;
  min-width: 100%;
  min-height: 100%;
}

.page-render {
  position: relative;
  display: inline-block;
  width: max-content;
  min-width: 0;
  flex: 0 0 auto;
}

.pdf-embed {
  display: block;
  border-radius: 0.75rem;
  overflow: hidden;
  box-shadow: 0 0.625rem 2.5rem rgba(15, 23, 42, 0.16);
  background: #fff;
}

.pdf-embed :deep(.vue-pdf-embed__page) {
  position: relative;
  margin: 0;
}

.pdf-embed :deep(canvas) {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 0.75rem;
}

.pdf-embed :deep(.textLayer),
.pdf-embed :deep(.annotationLayer) {
  inset: 0;
}

.overlay-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.overlay-box {
  position: absolute;
  border: 0.125rem solid;
  border-radius: 0.625rem;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.35);
}

@media (max-width: 64rem) {
  .viewer-head {
    flex-direction: column;
  }

  .viewer-controls {
    width: 100%;
    justify-content: space-between;
  }
}

@media (max-width: 48rem) {
  .pdf-viewer-card {
    min-height: 32rem;
  }

  .viewer-filename {
    max-width: 100%;
  }

  .page-scroll {
    padding: 0.85rem;
  }

  .viewer-controls :deep(.v-btn) {
    min-width: 2.75rem;
    min-height: 2.75rem;
  }

  .viewer-controls {
    justify-content: flex-start;
  }

  .viewer-control-block {
    width: 100%;
    justify-content: center;
  }
}
</style>
