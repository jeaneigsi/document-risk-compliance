<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps({
  source: {
    type: String,
    default: '',
  },
  emptyLabel: {
    type: String,
    default: '-',
  },
})

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const rendered = computed(() => {
  const content = String(props.source || '').trim()
  if (!content) {
    return `<p>${props.emptyLabel}</p>`
  }
  return md.render(content)
})
</script>

<template>
  <article class="markdown-surface" v-html="rendered" />
</template>

<style scoped>
.markdown-surface {
  color: rgba(var(--v-theme-on-surface), 0.9);
  line-height: 1.72;
  font-size: 0.98rem;
}

.markdown-surface :deep(*:first-child) {
  margin-top: 0;
}

.markdown-surface :deep(*:last-child) {
  margin-bottom: 0;
}

.markdown-surface :deep(h1),
.markdown-surface :deep(h2),
.markdown-surface :deep(h3),
.markdown-surface :deep(h4) {
  line-height: 1.2;
  margin: 1.2rem 0 0.7rem;
  font-weight: 700;
}

.markdown-surface :deep(h1) {
  font-size: clamp(1.6rem, 1.2rem + 1.3vw, 2.3rem);
}

.markdown-surface :deep(h2) {
  font-size: clamp(1.25rem, 1.05rem + 0.9vw, 1.8rem);
}

.markdown-surface :deep(h3) {
  font-size: clamp(1.05rem, 0.95rem + 0.5vw, 1.3rem);
}

.markdown-surface :deep(p),
.markdown-surface :deep(ul),
.markdown-surface :deep(ol),
.markdown-surface :deep(blockquote),
.markdown-surface :deep(pre) {
  margin: 0.7rem 0 1rem;
}

.markdown-surface :deep(ul),
.markdown-surface :deep(ol) {
  padding-left: 1.35rem;
}

.markdown-surface :deep(li) {
  margin: 0.25rem 0;
}

.markdown-surface :deep(blockquote) {
  margin-left: 0;
  padding: 0.8rem 1rem;
  border-left: 3px solid rgba(var(--v-theme-primary), 0.55);
  background: color-mix(in srgb, rgb(var(--v-theme-surface)) 78%, rgb(var(--v-theme-primary)) 22%);
  border-radius: 0 14px 14px 0;
}

.markdown-surface :deep(code) {
  background: rgba(var(--v-theme-on-surface), 0.08);
  padding: 0.12rem 0.35rem;
  border-radius: 6px;
  font-size: 0.92em;
}

.markdown-surface :deep(pre) {
  overflow: auto;
  padding: 1rem;
  border-radius: 14px;
  background: rgba(var(--v-theme-on-surface), 0.06);
}

.markdown-surface :deep(pre code) {
  padding: 0;
  background: transparent;
}

.markdown-surface :deep(hr) {
  border: 0;
  height: 1px;
  margin: 1.2rem 0;
  background: rgba(var(--v-theme-on-surface), 0.12);
}

.markdown-surface :deep(a) {
  color: rgb(var(--v-theme-primary));
}
</style>
