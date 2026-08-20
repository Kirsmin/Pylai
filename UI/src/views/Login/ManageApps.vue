<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NAlert, NButton, NPopconfirm, NSpin } from 'naive-ui'
import { api } from '@/utils/api'
import type { ScopeInfo } from '@/types/api'

interface AuthorizedApp { id: string; clientId: string; displayName: string; description?: string | null; logoUrl?: string | null; authorizedAt: string; scopes: ScopeInfo[] }
defineEmits<{ back: [] }>()
const apps = ref<AuthorizedApp[]>([])
const loading = ref(false)
const error = ref('')
const failedLogos = ref(new Set<string>())
const expanded = ref(new Set<string>())

function scopeNames(app: AuthorizedApp) { return app.scopes.length ? app.scopes.map(s => s.displayName).join(' · ') : '无' }
function toggle(id: string) { const set = expanded.value; set.has(id) ? set.delete(id) : set.add(id) }

async function load() {
  loading.value = true; error.value = ''
  try {
    const data = await api<{ apps: AuthorizedApp[] }>('/api/auth/account/authorized-apps')
    apps.value = data.apps || []
  } catch (e) { error.value = e instanceof Error ? e.message : '加载失败，请重试' }
  finally { loading.value = false }
}
async function revoke(id: string) {
  try { await api(`/api/auth/account/authorized-apps/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load() }
  catch (e) { error.value = e instanceof Error ? e.message : '撤销失败，请重试' }
}
onMounted(load)
</script>

<template>
  <div class="manage-header"><NButton quaternary size="small" @click="$emit('back')">&lt;- 返回</NButton><span class="manage-title">管理已授权应用</span></div>
  <div v-if="loading" class="center"><NSpin /></div>
  <NAlert v-else-if="error" type="error" :bordered="false">{{ error }}</NAlert>
  <div v-else-if="!apps.length" class="empty">暂无已授权应用</div>
  <div v-else class="list">
    <div v-for="app in apps" :key="app.id" class="card">
      <div class="row">
        <img v-if="app.logoUrl && !failedLogos.has(app.id)" :src="app.logoUrl" alt="" class="logo" @error="failedLogos.add(app.id)" />
        <strong class="name">{{ app.displayName }}</strong>
        <NPopconfirm positive-text="确定" negative-text="取消" @positive-click="revoke(app.id)"><template #trigger><NButton type="error" dashed size="small">撤销授权</NButton></template>此操作无法撤销，确定吗？</NPopconfirm>
      </div>
      <small>{{ app.authorizedAt }}</small><div>{{ app.description || '暂无应用描述' }}</div>
      <div class="scopes" :class="{ expanded: expanded.has(app.id) }" @click="toggle(app.id)">授权：<span>{{ scopeNames(app) }}</span></div>
    </div>
  </div>
</template>

<style scoped>
.manage-header,.row{display:flex;align-items:center;justify-content:space-between;gap:12px}.manage-title{font-size:18px;font-weight:600}.center,.empty{text-align:center;padding:32px 0}.list{max-height:360px;overflow:auto;display:flex;flex-direction:column;gap:12px}.card{border:1px dashed var(--success-color);border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:8px}.logo{width:20px;height:20px;object-fit:contain}.name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.scopes{font-size:12px;display:flex;gap:4px;cursor:pointer}.scopes span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.scopes.expanded span{white-space:normal;overflow:visible}
</style>
