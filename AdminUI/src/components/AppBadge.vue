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
  gap: 5px;
  padding: 3px 10px;
  border-radius: 99px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
  background: var(--surface-active);
  color: var(--text-secondary);
  border: 1px solid transparent;
  transition: all var(--transition-base);
}
.app-badge::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.7;
}
.tone-success { background: var(--success-soft); color: var(--success); }
.tone-info    { background: var(--info-soft);    color: var(--info); }
.tone-warning { background: var(--warning-soft); color: var(--warning); }
.tone-danger  { background: var(--danger-soft);  color: var(--danger); }
.tone-purple  { background: var(--purple-soft);  color: var(--purple); }
</style>
