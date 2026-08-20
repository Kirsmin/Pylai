<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NAlert, NButton, NPopconfirm, NSpin } from 'naive-ui'
import { api, apiFetch } from '@/utils/api'

interface ThirdPartyLogin { provider: string; displayName: string; boundAt: string }
defineEmits<{ back: [] }>()
const logins = ref<ThirdPartyLogin[]>([])
const providers = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const names: Record<string, string> = { github: 'GitHub', facebook: 'Facebook', microsoft: 'Microsoft' }

async function load() {
  loading.value = true; error.value = ''
  try {
    const [loginData, providerData] = await Promise.all([
      api<{ logins: ThirdPartyLogin[] }>('/api/auth/account/external-logins'),
      api<{ providers: string[] }>('/api/auth/external-login/providers')
    ])
    logins.value = loginData.logins || []; providers.value = providerData.providers || []
  } catch (e) { error.value = e instanceof Error ? e.message : '加载失败，请重试' }
  finally { loading.value = false }
}
function isBound(provider: string) { return logins.value.some(l => l.provider.toLowerCase() === provider.toLowerCase()) }
async function bind(provider: string) {
  error.value = ''
  try {
    const res = await apiFetch('/api/auth/external-login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider }) })
    const location = res.headers.get('location')
    if (location) { window.location.href = location; return }
    const body = await res.json().catch(() => null); error.value = body?.error || '无法发起绑定'
  } catch { error.value = '网络错误，请重试' }
}
async function unbind(provider: string) {
  try { await api(`/api/auth/account/external-logins/${encodeURIComponent(provider.toLowerCase())}`, { method: 'DELETE' }); await load() }
  catch (e) { error.value = e instanceof Error ? e.message : '解绑失败，请重试' }
}
onMounted(load)
</script>

<template>
  <div class="manage-header"><NButton quaternary size="small" @click="$emit('back')">&lt;- 返回</NButton><span class="manage-title">第三方登录方式</span></div>
  <div v-if="loading" class="center"><NSpin /></div>
  <NAlert v-else-if="error" type="error" :bordered="false">{{ error }}</NAlert>
  <div v-else class="list">
    <div v-for="provider in providers" :key="provider" class="row">
      <div><strong>{{ names[provider] || provider }}</strong><small v-if="isBound(provider)">已绑定</small><small v-else>未绑定</small></div>
      <NPopconfirm v-if="isBound(provider)" positive-text="解绑" negative-text="取消" @positive-click="unbind(provider)"><template #trigger><NButton type="error" dashed size="small">解绑</NButton></template>解绑后该第三方凭据将无法登录。</NPopconfirm>
      <NButton v-else type="success" dashed size="small" @click="bind(provider)">绑定</NButton>
    </div>
    <div v-if="!providers.length" class="center">暂无可用第三方登录方式</div>
  </div>
</template>

<style scoped>
.manage-header,.row{display:flex;align-items:center;justify-content:space-between;gap:12px}.manage-title{font-size:18px;font-weight:600}.center{text-align:center;padding:32px 0}.list{display:flex;flex-direction:column;gap:10px}.row{border:1px dashed var(--input-border);border-radius:10px;padding:12px}.row>div{display:flex;flex-direction:column;gap:4px}.row small{color:var(--text-tertiary)}
</style>
