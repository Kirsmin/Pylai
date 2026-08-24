<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { NButton, NDivider } from 'naive-ui'
import { api, apiFetch, csrfHeaders } from '@/utils/api'

const props = defineProps<{ initialError?: string }>()
const providers = ref<string[]>([])
const error = ref(props.initialError || '')
const names: Record<string, string> = { github: 'GitHub', facebook: 'Facebook', microsoft: 'Microsoft' }
watch(() => props.initialError, (v) => { error.value = v || '' })

onMounted(async () => {
  try {
    const data = await api<{ providers: string[] }>('/api/auth/external-login/providers')
    providers.value = data.providers || []
  } catch { providers.value = [] }
})

async function start(provider: string) {
  error.value = ''
  try {
    const res = await apiFetch('/api/auth/external-login', { method: 'POST', headers: { 'Content-Type': 'application/json', ...csrfHeaders() }, body: JSON.stringify({ provider }) })
    const location = res.headers.get('location')
    if (location) { window.location.href = location; return }
    const data = await res.json().catch(() => null)
    error.value = data?.error || '外部登录不可用'
  } catch { error.value = '网络错误，请重试' }
}
</script>

<template>
  <template v-if="providers.length">
    <NDivider style="margin: 8px 0">或使用第三方账号登录</NDivider>
    <div class="external-row">
      <NButton v-for="provider in providers" :key="provider" quaternary dashed @click="start(provider)">{{ names[provider] || provider }}</NButton>
    </div>
  </template>
  <p v-if="error" class="error-msg">{{ error }}</p>
</template>

<style scoped>
.external-row { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; width: 100%; }
.error-msg { color: var(--error-color); margin: 0; }
</style>
