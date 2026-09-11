<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <div class="page-header">
    <div class="page-heading">
      <h2 class="page-title">{{ title }}</h2>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div class="page-actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.page-heading { min-width: 0; }
.page-title {
  margin: 0;
  color: var(--text-primary);
  font-size: 19px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
.page-subtitle {
  margin: 4px 0 0;
  max-width: 720px;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.55;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
</style>
