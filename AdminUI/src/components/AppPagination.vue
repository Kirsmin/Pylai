<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  pageSize: number
  total: number
  unit?: string
}>()
const emit = defineEmits<{ (e: 'update:page', v: number): void }>()

const totalPages = computed(() => Math.ceil(props.total / props.pageSize) || 1)
const start = computed(() => (props.page - 1) * props.pageSize + 1)
const end = computed(() => Math.min(props.page * props.pageSize, props.total))

const windowPages = computed(() => {
  const total = totalPages.value
  const current = props.page
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  if (current <= 4) return [1, 2, 3, 4, 5, -1, total]
  if (current >= total - 3) return [1, -1, total - 4, total - 3, total - 2, total - 1, total]
  return [1, -1, current - 1, current, current + 1, -1, total]
})

function go(p: number) {
  if (p < 1 || p > totalPages.value) return
  emit('update:page', p)
}
</script>

<template>
  <div class="admin-pagination">
    <span class="muted small">
      {{ total > 0 ? `${start}-${end} / ${total}${unit ? ' ' + unit : ''}` : '无数据' }}
    </span>
    <div style="display:flex;gap:4px;">
      <button class="pg-btn" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
      <template v-for="(p, i) in windowPages" :key="`${p}-${i}`">
        <span v-if="p === -1" class="muted small" style="display:inline-flex;align-items:center;padding:0 4px;">…</span>
        <button v-else class="pg-btn" :class="{ active: p === page }" @click="go(p)">{{ p }}</button>
      </template>
      <button class="pg-btn" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
    </div>
  </div>
</template>
