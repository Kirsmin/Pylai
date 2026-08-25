<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import type { AdminBanHistoryItem, AdminBanInfo } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

const tab = ref<'active' | 'history'>('active')
const active = ref<AdminBanInfo[]>([])
const history = ref<AdminBanHistoryItem[]>([])
const total = ref(0)
const loading = ref(false)
const type = ref<string | null>(null)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('bans'))
const typeOptions = [
  { label: 'login', value: 'login' },
  { label: 'invite', value: 'invite' },
  { label: 'email', value: 'email' },
  { label: 'admin', value: 'admin' },
  { label: 'confirm', value: 'confirm' }
]
const historyTypeOptions = typeOptions.filter(i => i.value !== 'confirm')

function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({ skip: String((page.value - 1) * pageSize), take: String(pageSize) })
    if (type.value) params.set('type', type.value)
    if (tab.value === 'active') {
      const data = await authStore.request<{ success: boolean; total: number; bans: AdminBanInfo[] }>(`/api/admin/bans?${params.toString()}`)
      active.value = data?.bans ?? []; total.value = data?.total ?? 0
    } else {
      const data = await authStore.request<{ success: boolean; total: number; bans: AdminBanHistoryItem[] }>(`/api/admin/bans/history?${params.toString()}`)
      history.value = data?.bans ?? []; total.value = data?.total ?? 0
    }
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { loading.value = false }
}
function switchTab(v: 'active' | 'history') { tab.value = v; if (v === 'history' && type.value === 'confirm') type.value = null; page.value = 1; load() }
function search() { page.value = 1; load() }
function resetFilters() { type.value = null; page.value = 1; load() }
onMounted(load)

const ipVisible = ref(false)
const unbanIp = ref('')
const unbanIpType = ref<string | null>(null)
const unbanning = ref(false)
function openUnbanByIp() { unbanIp.value = ''; unbanIpType.value = null; ipVisible.value = true }
async function unbanByIp() {
  if (!unbanIp.value.trim()) return
  unbanning.value = true
  try {
    const params = new URLSearchParams()
    if (unbanIpType.value) params.set('type', unbanIpType.value)
    await authStore.request(`/api/admin/bans/ip/${encodeURIComponent(unbanIp.value.trim())}?${params.toString()}`, { method: 'DELETE' })
    message.success('已按 IP 执行解封'); ipVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '解封失败') }
  finally { unbanning.value = false }
}
async function unbanById(banId: string) {
  try {
    await authStore.request(`/api/admin/bans/${encodeURIComponent(banId)}`, { method: 'DELETE' })
    message.success('封禁已解除'); load()
  } catch (err) { message.error(err instanceof Error ? err.message : '解封失败') }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="封禁管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('DELETE','/api/admin/bans/ip/{ip}')" type="success" ghost @click="openUnbanByIp">按 IP 解封</NButton>
      </template>
    </PageHeader>

    <div class="admin-toolbar">
      <div class="segmented">
        <button type="button" :class="{active:tab==='active'}" @click="switchTab('active')">当前封禁</button>
        <button type="button" :class="{active:tab==='history'}" @click="switchTab('history')">封禁历史</button>
      </div>
      <NSelect v-model:value="type" placeholder="类型" clearable :options="tab==='active'?typeOptions:historyTypeOptions" style="width:150px" @update:value="search" />
      <NButton type="success" ghost @click="search">查询</NButton>
      <NButton quaternary @click="resetFilters">重置</NButton>
    </div>

    <div>
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="tab==='active' && active.length">
        <div style="display:flex;flex-direction:column;gap:8px;">
          <div v-for="ban in active" :key="ban.banId" class="admin-line-card" style="border-left:3px solid var(--warning);">
            <div style="display:flex;flex-direction:column;gap:4px;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <AppBadge tone="warning">{{ ban.type }}</AppBadge>
                <strong class="mono small">{{ ban.banId }}</strong>
              </div>
              <p class="muted small" style="margin:0;line-height:1.6;">
                {{ ban.type==='confirm' ? `${ban.userName||'未知用户'}（${ban.userUid}）` : ban.ip||'未知 IP' }}
                · 失败 {{ ban.failureCount }} 次
                · 到期 <DateTimeText :value="ban.banExpires" empty="永久" />
              </p>
            </div>
            <NPopconfirm v-if="endpointAllowed('DELETE','/api/admin/bans/{banId}')" @positive-click="unbanById(ban.banId)">
              <template #trigger><NButton size="small" quaternary type="error">解封</NButton></template>
              <span style="white-space:nowrap">解除该封禁？</span>
            </NPopconfirm>
          </div>
        </div>
      </template>
      <template v-else-if="tab==='history' && history.length">
        <div style="display:flex;flex-direction:column;gap:8px;">
          <div v-for="item in history" :key="item.id" class="admin-line-card">
            <div style="display:flex;flex-direction:column;gap:4px;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <AppBadge tone="neutral">{{ item.type }}</AppBadge>
                <strong class="mono small">#{{ item.id }} {{ item.banId }}</strong>
              </div>
              <p class="muted small" style="margin:0;line-height:1.6;">
                IP {{ item.ip }}
                · <DateTimeText :value="item.bannedAt" /> → <DateTimeText :value="item.banExpiresAt" />
                · <template v-if="item.unbannedAt">解封于 <DateTimeText :value="item.unbannedAt" /></template>
                <template v-else>未解封</template>
              </p>
            </div>
          </div>
        </div>
      </template>
      <NEmpty v-else description="没有封禁记录" class="admin-empty" />
      <AppPagination v-if="total>0" v-model:page="page" :page-size="pageSize" :total="total" @update:page="load" />
    </div>

    <NModal v-model:show="ipVisible" preset="card" style="width:min(92%,440px)" title="按 IP 解封">
      <div style="display:flex;flex-direction:column;gap:14px;">
        <label>
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">IP 地址</span>
          <input v-model="unbanIp" class="admin-input mono" placeholder="如 172.17.0.1" />
        </label>
        <label>
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">类型（留空则尝试 login / invite / admin）</span>
          <NSelect v-model:value="unbanIpType" :options="typeOptions.filter(o=>o.value!=='confirm')" clearable />
        </label>
        <div style="display:flex;justify-content:flex-end;">
          <NButton type="success" ghost :loading="unbanning" :disabled="!unbanIp.trim()" @click="unbanByIp">执行解封</NButton>
        </div>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
</style>
