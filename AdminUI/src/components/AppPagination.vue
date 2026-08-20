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
      <button
        v-for="p in totalPages"
        :key="p"
        class="pg-btn"
        :class="{ active: p === page }"
        @click="go(p)"
      >{{ p }}</button>
      <button class="pg-btn" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.pg-btn {
  min-width: 32px; height: 32px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.pg-btn:hover:not(:disabled) {
  border-color: var(--border-strong);
  color: var(--text-primary);
  background: var(--surface-hover);
}
.pg-btn.active {
  background: var(--success);
  color: #fff;
  border-color: var(--success);
}
.pg-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>