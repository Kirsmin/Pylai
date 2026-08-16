<script setup lang="ts">
withDefaults(defineProps<{
  page: number
  pageSize: number
  total: number
  unit?: string
}>(), {
  pageSize: 20,
  unit: '条'
})

const emit = defineEmits<{
  'update:page': [page: number]
}>()
</script>

<template>
  <div class="admin-pagination">
    <span class="muted">共 {{ total }} {{ unit }}</span>
    <NButton size="small" quaternary :disabled="page <= 1" @click="emit('update:page', page - 1)">上一页</NButton>
    <span class="mono muted-2">{{ page }}</span>
    <NButton size="small" quaternary :disabled="page * pageSize >= total" @click="emit('update:page', page + 1)">下一页</NButton>
  </div>
</template>
