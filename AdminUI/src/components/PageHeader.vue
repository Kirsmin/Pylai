<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string | null
}>()
</script>

<template>
  <header class="admin-page-head">
    <div>
      <h1 class="admin-page-title">{{ title }}</h1>
      <p v-if="subtitle" class="admin-page-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="admin-head-actions">
      <slot name="actions" />
    </div>
  </header>
</template>
