<script setup lang="ts">
defineProps<{
  tone?: 'success' | 'info' | 'warning' | 'danger' | 'purple' | 'neutral'
}>()
</script>

<template>
  <span class="app-badge" :class="tone ? `tone-${tone}` : ''">
    <slot />
  </span>
</template>

<style scoped>
.app-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
  background: var(--surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  transition: all var(--transition-base);
}
.tone-success { background: var(--success-soft); color: var(--success); border-color: transparent; }
.tone-info { background: var(--info-soft); color: var(--info); border-color: transparent; }
.tone-warning { background: var(--warning-soft); color: var(--warning); border-color: transparent; }
.tone-danger { background: var(--danger-soft); color: var(--danger); border-color: transparent; }
.tone-purple { background: var(--purple-soft); color: var(--purple); border-color: transparent; }
</style>