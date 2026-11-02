<script setup lang="ts">
/* 四态统一渲染：Loading / Empty / Error / Forbidden。
   加载失败绝不再伪装成"没有数据"。 */
import { AlertCircle, Inbox, Lock } from '@vicons/tabler'

withDefaults(defineProps<{
  state: 'loading' | 'empty' | 'error' | 'forbidden'
  description?: string
  loadingText?: string
  emptyText?: string
  errorText?: string
  forbiddenText?: string
  retryable?: boolean
}>(), {
  loadingText: '加载中…',
  emptyText: '暂无数据',
  errorText: '加载失败',
  forbiddenText: '没有访问权限'
})

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="state-block" :data-state="state" role="status">
    <template v-if="state === 'loading'">
      <span class="state-spinner" aria-hidden="true" />
      <p class="state-text">{{ loadingText }}</p>
    </template>
    <template v-else-if="state === 'empty'">
      <NIcon class="state-icon" :component="Inbox" />
      <p class="state-text">{{ emptyText }}</p>
      <p v-if="description" class="state-desc">{{ description }}</p>
    </template>
    <template v-else-if="state === 'error'">
      <NIcon class="state-icon state-icon-danger" :component="AlertCircle" />
      <p class="state-text state-text-danger">{{ errorText }}</p>
      <p v-if="description" class="state-desc">{{ description }}</p>
      <button v-if="retryable" type="button" class="state-retry" @click="emit('retry')">重试</button>
    </template>
    <template v-else>
      <NIcon class="state-icon state-icon-warning" :component="Lock" />
      <p class="state-text">{{ forbiddenText }}</p>
      <p v-if="description" class="state-desc">{{ description }}</p>
    </template>
  </div>
</template>

<style scoped>
.state-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 180px;
  padding: var(--space-6);
  text-align: center;
}
.state-icon { font-size: 32px; color: var(--text-tertiary); }
.state-icon-danger { color: var(--danger); }
.state-icon-warning { color: var(--warning); }
.state-text { margin: 0; font-size: var(--font-size-body); line-height: var(--line-height-body); color: var(--text); font-weight: 600; }
.state-text-danger { color: var(--danger); }
.state-desc { margin: 0; font-size: var(--font-size-caption); line-height: var(--line-height-caption); color: var(--text-secondary); max-width: 420px; }
.state-retry {
  margin-top: var(--space-1);
  padding: 5px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
}
.state-retry:hover { border-color: var(--accent); }
.state-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: state-spin 0.8s linear infinite;
}
@keyframes state-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .state-spinner { animation-duration: 1.6s; }
}
</style>
