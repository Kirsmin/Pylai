<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'success' | 'danger' | 'warning' | 'info' | 'purple' | 'neutral'
  dot?: boolean
}>(), {
  tone: 'neutral',
  dot: true
})
</script>

<template>
  <span class="app-badge" :class="`tone-${tone}`">
    <i v-if="dot" class="app-badge-dot" />
    <span class="app-badge-text"><slot /></span>
  </span>
</template>
