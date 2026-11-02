<script setup lang="ts">
/* 全站唯一的页面标题区：24/32 标题 + 一句说明 + 主操作区。
   顶栏面包屑不再重复标题（AdminLayout）。 */
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <div class="page-header">
    <div class="page-heading">
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.page-heading { min-width: 0; }
.page-title {
  margin: 0;
  color: var(--text);
  font-size: var(--font-size-title);
  line-height: var(--line-height-title);
  font-weight: 650;
  letter-spacing: -0.01em;
}
.page-subtitle {
  margin: 4px 0 0;
  max-width: 720px;
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}
.page-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
</style>
