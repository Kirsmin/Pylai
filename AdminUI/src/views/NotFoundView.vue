<script setup lang="ts">
import { useRouter } from 'vue-router'
import { FileOff } from '@vicons/tabler'

const router = useRouter()
function goHome() {
  void router.push('/')
}
</script>

<template>
  <div class="not-found">
    <NIcon class="not-found-icon" :component="FileOff" />
    <p class="not-found-code mono">404</p>
    <h1 class="not-found-title">页面不存在</h1>
    <p class="not-found-desc">你访问的地址没有对应的页面，可能已被移动或删除。</p>
    <NButton type="primary" @click="goHome">返回概览</NButton>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 50vh;
  text-align: center;
}
.not-found-icon { font-size: 40px; color: var(--text-tertiary); }
.not-found-code { margin: 0; font-size: 15px; font-weight: 700; color: var(--text-tertiary); }
.not-found-title { margin: 0; font-size: var(--font-size-title); line-height: var(--line-height-title); font-weight: 650; color: var(--text); }
.not-found-desc { margin: 0 0 var(--space-3); font-size: var(--font-size-body); line-height: var(--line-height-body); color: var(--text-secondary); }
</style>
