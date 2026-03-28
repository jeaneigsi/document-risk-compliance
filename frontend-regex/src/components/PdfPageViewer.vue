<script setup>
import { computed, ref, watch } from 'vue'
import { documentsApi } from '@/services/api'

const props = defineProps({
  title: { type: String, default: '' },
  documentId: { type: String, default: '' },
  filename: { type: String, default: '' },
  page: { type: Number, default: 1 },
  totalPages: { type: Number, default: 0 },
  renderScale: { type: Number, default: 1.6 },
  highlights: { type: Array, default: () => [] },
  viewerHeight: { type: [Number, String], default: 640 },
  allowExpand: { type: Boolean, default: false },
})

const emit = defineEmits(['update:page', 'expand'])
const zoom = ref(1)

const imageUrl = computed(() => {
  if (!props.documentId || props.page < 1) return ''
  return documentsApi.renderPageUrl(props.documentId, props.page, props.renderScale * zoom.value)
})

watch(
  () => props.documentId,
  () => {
    zoom.value = 1
  }
)

function setPage(nextPage) {
  if (!props.totalPages) return
  const clamped = Math.max(1, Math.min(props.totalPages, Number(nextPage || 1)))
  emit('update:page', clamped)
}

function zoomIn() {
  zoom.value = Math.min(3, Number((zoom.value + 0.2).toFixed(2)))
}

function zoomOut() {
  zoom.value = Math.max(0.6, Number((zoom.value - 0.2).toFixed(2)))
}

function resetZoom() {
  zoom.value = 1
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
    <v-card-title class="d-flex align-center">
      <div>
        <div class="text-subtitle-1 font-weight-bold">{{ title }}</div>
        <div class="text-caption text-medium-emphasis">{{ filename || 'No document selected' }}</div>
      </div>
      <v-spacer />
      <div v-if="documentId" class="d-flex align-center ga-2">
        <v-btn icon="mdi-magnify-minus-outline" variant="text" @click="zoomOut" />
        <v-chip size="small" color="primary" variant="tonal">{{ Math.round(zoom * 100) }}%</v-chip>
        <v-btn icon="mdi-magnify-plus-outline" variant="text" @click="zoomIn" />
        <v-btn icon="mdi-fit-to-page-outline" variant="text" @click="resetZoom" />
        <v-btn icon="mdi-chevron-left" variant="text" :disabled="page <= 1" @click="setPage(page - 1)" />
        <v-text-field
          :model-value="page"
          type="number"
          density="compact"
          hide-details
          variant="outlined"
          class="page-input"
          @update:model-value="setPage($event)"
        />
        <span class="text-caption">/ {{ totalPages || '?' }}</span>
        <v-btn icon="mdi-chevron-right" variant="text" :disabled="page >= totalPages" @click="setPage(page + 1)" />
        <v-btn
          v-if="allowExpand"
          icon="mdi-arrow-expand-all"
          variant="text"
          title="Vue détaillée"
          @click="emit('expand')"
        />
      </div>
    </v-card-title>
    <v-card-text>
      <v-alert v-if="!documentId" type="info" variant="tonal">
        Select or upload a document to open the viewer.
      </v-alert>
      <div v-else class="page-stage">
        <div class="page-scroll" :style="{ height: typeof viewerHeight === 'number' ? `${viewerHeight}px` : viewerHeight }">
          <div class="page-canvas">
            <img :src="imageUrl" :alt="`${filename} page ${page}`" class="page-image" />
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
    </v-card-text>
  </v-card>
</template>

<style scoped>
.pdf-viewer-card {
  height: 100%;
  min-height: 680px;
}

.page-input {
  max-width: 84px;
}

.page-stage {
  width: 100%;
  border-radius: 20px;
  background:
    linear-gradient(180deg, rgba(241, 245, 249, 0.96), rgba(226, 232, 240, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.35);
}

.page-scroll {
  overflow: auto;
  padding: 16px;
  scrollbar-width: thin;
}

.page-canvas {
  position: relative;
  width: max-content;
  max-width: none;
}

.page-image {
  display: block;
  width: auto;
  max-width: none;
  height: auto;
  min-width: 100%;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(15, 23, 42, 0.18);
}

.overlay-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.overlay-box {
  position: absolute;
  border: 2px solid;
  border-radius: 10px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.35);
}
</style>
