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
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
  background: var(--surface-active);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}
.tone-success { background: var(--success-soft); color: var(--success); border-color: color-mix(in srgb, var(--success) 22%, transparent); }
.tone-info    { background: var(--info-soft);    color: var(--info);    border-color: color-mix(in srgb, var(--info) 22%, transparent); }
.tone-warning { background: var(--warning-soft); color: var(--warning); border-color: color-mix(in srgb, var(--warning) 22%, transparent); }
.tone-danger  { background: var(--danger-soft);  color: var(--danger);  border-color: color-mix(in srgb, var(--danger) 22%, transparent); }
.tone-purple  { background: var(--purple-soft);  color: var(--purple);  border-color: color-mix(in srgb, var(--purple) 22%, transparent); }
</style>
