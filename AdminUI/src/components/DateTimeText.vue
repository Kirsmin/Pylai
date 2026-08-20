<script setup lang="ts">
defineProps<{
  value: string | null | undefined
  empty?: string
}>()

function fmt(v: string | null | undefined): string {
  if (!v) return ''
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  return d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <span class="mono small muted">{{ value ? fmt(value) : (empty || '—') }}</span>
</template>